"""SYNTHETIC test data for the name matcher. None of it describes a real school.

Everything here is generated from word patterns for tests and benchmarks and
must never reach the site: the records mimic the *shape* of NCES names (``"Ashford
Area SD"``, ``"BRIARTON ISD"``, ``"Lincoln El Sch"``), not any real district or
school. Ids start with ``SYN-``, county codes start with ``9`` (no US state has a
FIPS code in the 90s), and coordinates sit on an arbitrary grid.

Two parts:

* :func:`build_directory` generates a directory of any size, state by state,
  with the naming habits of each state's NCES records, and remembers for every
  record its *identity*: the parts a listing must repeat to mean it (town or
  namesake, level, qualifier, numbers, affiliation).
* :func:`build_cases` writes listings for records the way closings lists spell
  them (abbreviations either way, noise, case), including listings aimed at the
  wrong state or county or with a changed level or number, listings that name a
  church or faith beside a town's name (``"Ashfield Catholic Schools"``),
  colleges and universities named for a town (``"Ashfield College"``), and
  the town's own government, community places and churches (``"City of
  Ashfield"``, ``"Ashfield Senior Center"``) beside a district named
  ``"Ashfield City"``, ``"Ashfield Exempted Village"`` or ``"Ashfield Town"``.
  Maine's districts are named by code (``"RSU 13"``, ``"RSU 17/MSAD 17"``,
  ``"MSAD 27"``) and Kansas's by town with a ``USD`` number only listings give,
  so some listings begin with a district code (``"RSU 13 - Ashfield"``, ``"USD
  320 Ashfield"``, ``"RSU 13 Lincoln Elementary"``), some with a wrong one.
  Some towns have a neighbour named for its direction from them, in the same
  county (``"Ashfield"`` and ``"East Ashfield"``, NCES-style), and listings
  abbreviate directions (``"E. Ashfield Schools"``, ``"No. Ashfield SD"``),
  including for towns that have no such neighbour (``"W. Ashfield Public
  Schools"`` names nothing).
  Some listings are only a town's name (``"Ashfield"``, ``"ASHFIELD - Closed"``):
  that is the town's district when one is named for it, and nothing else,
  never a school named for the town. Some districts are named for more than
  their town (``"Ashfield Valley Unified"``, whose high school is ``"Ashfield
  High"``), and some towns whose district is named otherwise (``"Abernathy
  County"``, ``"RSU 13"``) have a private school named for them (``"Village
  School of Ashfield"``, ``"The Ashfield School"``).
  Each state has made-up charter networks (``"SOLVANE HIGH SCHOOLS"``,
  ``"Tessaly Academy"``, ``"Corvane Public Schools"``) with campuses in counties
  far apart; a listing of the network's name from one market means its one
  campus there, or nothing when the market holds two. Some listings name an
  ordinary district from the county beside its own, which holds one of its
  schools: that is the district, whole.
  Each state also has made-up charter districts named as one academy
  (``"Arvenne Academy"``, ``"BELVORA ACADEMY"``) in one town, whose schools add
  a level or a part to that name (``"Arvenne Academy Middle"``, ``"BELVORA
  ACADEMY UPPER EL"``, ``"CINDRAL ACADEMY-LOWER"``): the district's name alone
  names the district, never the school that adds only a level to it.
  And each state has two districts named for a town that lies far from them:
  one bears the town's district's very name (two ``"ASHFIELD ISD"``, as Texas
  has two ``"EDGEWOOD ISD"``), the other spells the town's name as a plural
  (``"Ashfields Local"`` beside the town of Ashfield's ``"Ashfield Local"``).
  The town's name from the namesake's county names the namesake; from the
  town's county, the town's district; statewide, neither, or the namesake that
  spells it so.
  Some names end with a bracket, as NCES writes them: every Arizona
  district's with its entity number (``"Ashfield School District (4231)"``),
  two districts of one name in Washington, Michigan and Arkansas with their
  counties' names (``"Ashfield Public Schools (Abernathy)"``, in Abernathy
  County), and some New York districts with a second name they are known by
  (``"ASHFIELD CENTRAL SCHOOL DISTRICT (LAKE VESPER)"``), which their high
  school bears (``"LAKE VESPER HIGH SCHOOL"``). Some listings name such a
  district by its second name, its high school, or its name and county
  (``"Ashfield Public Schools - Abernathy County"``).
  Some listings say a municipal word a district's NCES name does not
  (``"Ashfield City Schools"`` or ``"Ashfield Township School District"`` for
  ``"Ashfield School District"``), or leave out one it says (``"Ashfield Schools"``
  for ``"Ashfield Township School District"``): that is the district unless
  another in scope bears the rest of its name; and some name the town's
  government in words no school says (``"Ashfield, Town of"``, ``"Ashfield
  Borough"``).
  And a few markets span two states whose namesakes lie on either side of the
  market's counties (as WMUR's Boston market spans Massachusetts and New
  Hampshire): the market's state names a district by its town alone
  (``"Ashfield"``, with ``"Ashfield High"``), the other state's county beside it
  by its town and legal form (``"Ashfield School District"``, with ``"Ashfield
  High School"``), and a school of one person's name is in both. Most such
  counties lie just past the market's; some far from it.
  And New Jersey, Pennsylvania, Michigan and Ohio have townships of one name in
  two counties, each running a district NCES writes its own way (``"Township of
  Ashfield School District"``, ``"Ashfield Township School District"``,
  ``"Ashfield Township Public School District"``, ``"Ashfield School
  District"``): a listing of the name, in either word order, with ``Township``
  or without, names both and so neither, unless a point much nearer one tells,
  or counties that hold one and lie beyond a list's reach of the other; one
  that says ``Township`` names only the districts whose names say it.
  And each state has private schools whose names begin with a place word or
  hold one after a word that names no place (``"Village Christian Academy"``,
  ``"Town & Country Day School"``, ``"City Academy"``, ``"Kid City Academy"``):
  the word is the name's own, and a listing that leaves it out (``"Christian
  Academy"``, ``"Country Day School"``, ``"Academy"``, ``"Kids Academy"``) names
  none of them.
  Every school carries NCES-style grades (:data:`GRADE_SPANS`), and some names
  leave out the level the grades make them, as NCES often does (``"Dunbar"`` and
  ``"Dunbar School"`` of K-5, a parish's ``"ST JOSEPH SCHOOL"`` of PK-8), beside a
  namesake in the county whose name says it (``"Dunbar Elementary School"``,
  ``"ST JOSEPH ELEMENTARY SCHOOL"``): a listing that says the level
  (``"Dunbar Elementary"``, ``"St. Joseph Elementary"``) names both, and so
  neither. A school of other grades (a 6-8 ``"Dunbar School"``) is none of that
  level, and one that teaches the level's grades and far more (a K-12 school for
  ``Elementary``, a PK-8 one for ``Preschool``) may be meant, and so leaves the
  listing no answer either (:data:`TAUGHT`).
  The expected answer comes from the identities, not from the matcher: a
  listing should match a record exactly when that record is the only one in
  the listing's scope whose identity the listing is compatible with. With
  counties given, that scope reaches the counties just past them
  (:class:`~snowlight.match.index.CountyGrid`), where a closings list strays:
  a record there that the listing fits leaves it no answer, and is never one.
"""

import math
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace

from snowlight.match import DirectoryRecord, lexicon
from snowlight.match.index import CountyGrid, haversine_km

STATES: tuple[str, ...] = (
    "AL", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
    "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA",
    "WA", "WV", "WI", "WY",
)  # fmt: skip

# Town names are a prefix and a suffix. Prefixes differ by at least two letters
# from each other so no two towns are one typo apart.
TOWN_PREFIXES: tuple[str, ...] = (
    "Ash", "Birch", "Cedar", "Dover", "Elk", "Fern", "Glen", "Hazel", "Iron", "Juniper",
    "Kings", "Laurel", "Marble", "North", "Oak", "Pine", "Quarry", "Red", "Silver", "Thorn",
    "Ulster", "Violet", "Willow", "Yarrow", "Amber", "Bram", "Clear", "Deer", "Eagle", "Fox",
    "Granite", "Heron", "Indigo", "Jasper", "Kestrel", "Lark", "Marsh", "Nettle", "Otter",
    "Pebble", "Quill", "Raven", "Sable", "Tamarack", "Vale", "Wren", "Zephyr", "Briar",
    "Copper", "Dusk",
)  # fmt: skip
TOWN_SUFFIXES: tuple[str, ...] = (
    "field", "ford", "ton", "ville", "wood", "dale", "brook", "burg", "haven", "ridge",
    "port", "mont", "crest", "view", "water", "stead", "wick", "bury", "land", "hollow",
)  # fmt: skip
COUNTY_ROOTS: tuple[str, ...] = (
    "Abernathy", "Blackwell", "Carrow", "Delacroix", "Ellery", "Fairbairn", "Gorham",
    "Halloway", "Ingersoll", "Jarrell", "Kinsey", "Lorimer", "Merriwether", "Norcross",
    "Oglesby", "Pendleton", "Quimby", "Rutledge", "Standish", "Tolliver", "Upshaw",
    "Vickery", "Whitlock", "Yardley", "Zimmer", "Ashcombe", "Bellamy", "Crowder", "Dunleavy",
    "Everly", "Fenwick", "Garrity", "Hollister", "Ivers", "Kimbrough",
)  # fmt: skip
NAMESAKES: tuple[str, ...] = (
    "Lincoln", "Washington", "Jefferson", "Franklin", "Roosevelt", "Kennedy", "Madison",
    "Monroe", "Jackson", "Garfield", "Hamilton", "Edison", "Whittier", "Longfellow",
    "Emerson", "Hawthorne", "Irving", "Carver", "Douglass", "Tubman", "Keller", "Earhart",
    "Audubon", "Bryant", "Cleveland", "Coolidge", "Eisenhower", "Grant", "Harding",
    "Truman", "Wilson", "Oak Grove", "Maple Ridge", "Cedar Hill", "Pine View",
    "Willow Creek", "Meadowbrook", "Sunnyside", "Riverside", "Lakeview", "Hillcrest",
    "Fairview", "Highland", "Parkside", "Brookside", "Westwood", "Eastwood", "Valley View",
    "Green Acres", "Prairie View", "Rolling Hills", "Spring Creek", "Stony Point",
    "Clearwater", "Bayside", "Crestview", "Glenwood", "Heritage", "Liberty", "Independence",
    "Pioneer", "Frontier", "Summit", "Horizon", "Discovery", "Legacy", "Centennial",
    "Mount Olive", "Mount Pleasant", "Fort Hill", "Martin Luther King Jr",
)  # fmt: skip
# People and streets a school may be named for: generic given names and surnames,
# combined at random, so the directory has as many distinct names as NCES does.
GIVEN_NAMES: tuple[str, ...] = (
    "Amelia", "Benjamin", "Clara", "Daniel", "Eleanor", "Frederick", "Grace", "Henry",
    "Iris", "James", "Katherine", "Louis", "Margaret", "Nathan", "Olivia", "Philip", "Ruth",
    "Samuel", "Theodore", "Vera", "Walter", "Agnes", "Bernard", "Cecilia", "Douglas",
    "Edith", "Francis", "Gilbert", "Harriet", "Irene", "Julian", "Lillian", "Marcus",
    "Nora", "Oscar", "Pearl", "Raymond", "Sylvia", "Thelma", "Victor", "Warren", "Alma",
    "Calvin", "Dorothy", "Elmer", "Florence", "Gordon", "Hazel", "Isaac", "Josephine",
)  # fmt: skip
SURNAMES: tuple[str, ...] = (
    "Abbott", "Barlow", "Calloway", "Dempsey", "Eastman", "Fairchild", "Galloway", "Hargrove",
    "Ingram", "Jennings", "Kendrick", "Langston", "Maddox", "Newcomb", "Ogden", "Prescott",
    "Quinlan", "Radcliffe", "Sheffield", "Thornton", "Underwood", "Vaughn", "Whitaker",
    "Yancey", "Ashby", "Bingham", "Crandall", "Dunbar", "Ellsworth", "Fulton", "Gentry",
    "Holloway", "Irwin", "Judson", "Kirkland", "Lockhart", "Merrill", "Nash", "Oakes",
    "Pickett", "Ramsey", "Sutton", "Talbot", "Upton", "Vance", "Winslow", "Yates",
    "Albright", "Beckett", "Chandler", "Draper", "Emery", "Fletcher", "Garner", "Hollis",
    "Jarvis", "Kestrand", "Lowell", "Mercer", "Norwood", "Osborne", "Pratt", "Rowland",
    "Sinclair", "Tanner", "Upshur", "Wade", "Wheeler", "Ward", "Stanton", "Randolph",
)  # fmt: skip
LEVEL_SURNAMES: tuple[str, ...] = tuple(
    head + tail
    for head in ("Dunm", "Harb", "Quov", "Lorb", "Mesk", "Pord", "Sallw")
    for tail in ("ore", "ick", "ane", "ery", "ond", "ell", "and", "ison", "urst", "eth")
)
"""Surnames of :meth:`_Generator.levels`' groups, which no person of a school bears, as
many as :data:`SURNAMES`: a school of a surname alone, and one named for a person of
it, are another pair (:meth:`_Generator.forenames`)."""
SURNAME_HEADS: tuple[str, ...] = (
    "Ash", "Brock", "Cal", "Dal", "Ever", "Fair", "Gar", "Hart", "Kel", "Lang", "Mar",
    "Nor", "Pem", "Rad", "Sel", "Tal", "Wat", "Whit", "Bur", "Chal", "Dor", "Fen", "Gil",
    "Hal", "Kim", "Lind", "Mont", "Ros", "Stan", "Wal",
)  # fmt: skip
SURNAME_TAILS: tuple[str, ...] = (
    "well", "ton", "ley", "wick", "more", "den", "ford", "by", "stone", "field", "worth",
    "ridge", "ham", "man", "son", "ing", "ard", "rick", "win", "cott",
)  # fmt: skip
ALL_SURNAMES: tuple[str, ...] = SURNAMES + tuple(
    head + tail for head in SURNAME_HEADS for tail in SURNAME_TAILS
)
STREETS: tuple[str, ...] = (
    "Main", "Elm", "Park", "Cherry", "Walnut", "Chestnut", "Spruce", "Church", "Mill",
    "Water", "Market", "Union", "Center", "Bridge", "Maple", "Locust", "Poplar", "Grove",
)  # fmt: skip
STREET_KINDS: tuple[tuple[str, str], ...] = (
    ("Street", "St"),
    ("Street", "St."),
    ("Avenue", "Ave"),
    ("Road", "Rd"),
)
SAINTS: tuple[str, ...] = (
    "Mary", "Joseph", "Patrick", "Anne", "Michael", "Francis", "John", "Paul", "Peter",
    "Catherine", "Thomas", "Brigid", "Agnes", "Gregory", "Monica", "Vincent", "Rose",
)  # fmt: skip

# Faiths a listing may name beside a town, and the ones private schools here carry.
FAITHS: tuple[str, ...] = (
    "Catholic", "Christian", "Lutheran", "Baptist", "Jewish", "Islamic", "Episcopal",
    "Adventist", "Mennonite",
)  # fmt: skip
SYSTEM_FAITHS: tuple[str, ...] = ("Catholic", "Christian", "Lutheran")
# How a listing names a college or university for a town.
COLLEGE_FORMS: tuple[str, ...] = (
    "{town} College", "{town} University", "University of {town}", "{town} Community College",
    "{town} State University", "{town} Technical College", "{town} Univ.", "College of {town}",
    "{town} Seminary",
)  # fmt: skip
# How a listing names a town's government beside a district named for the town
# as a city, a village or a town: "City of Ashfield" beside "Ashfield City".
GOVERNMENT_OF: dict[str, str] = {
    "City": "City of {town}",
    "Village": "Village of {town}",
    "Town": "Town of {town}",
}
# Other civic bodies a closings list carries under a town's name.
CIVIC_FORMS: tuple[str, ...] = (
    "{town} City Hall", "{town} Village Hall", "{town} Town Hall", "{town} Town Offices",
    "City of {town} Offices", "{town} City Council", "{town} Senior Center",
    "{town} Sr. Citizens Center", "{town} Community Center", "{town} Public Library",
    "{town} Hospital", "{town} Health Center", "{town} Police Dept.", "{town} Water Department",
    "{town} Parks & Recreation", "{town} YMCA", "{town} Meals on Wheels",
    "First Baptist Church of {town}", "{town} United Methodist Church", "{town} Church",
    "Borough of {town}", "Township of {town}", "{town} Municipal Court",
)  # fmt: skip

# Compass directions a town's neighbour is named for, and how listings shorten them.
DIRECTIONS: tuple[str, ...] = ("North", "South", "East", "West")
DIRECTION_FORMS: dict[str, tuple[str, ...]] = {
    "North": ("N.", "N", "No."),
    "South": ("S.", "S", "So."),
    "East": ("E.", "E"),
    "West": ("W.", "W"),
}
_NEIGHBOUR_SHARE = 0.12
"""The share of districts whose town has a neighbour named for its direction."""
_VALLEY_SHARE = 0.3
"""The share of California's and plain states' districts named for more than their
town (``"Ashfield Valley Unified"``), each with a high school named for the town."""
_VALLEY_DISTRICT: dict[str, str] = {"ca": "{town} Valley Unified", "plain": "{town} Valley SD"}
_VALLEY_HIGH: tuple[str, ...] = ("{town} High", "{town} High School", "{town} Senior High")
_TOWN_PRIVATE_SHARE = 0.25
"""The share of towns whose schools none is named for that get a private school
named for them (``"Village School of Ashfield"``)."""
TOWN_PRIVATE_FORMS: tuple[str, ...] = ("Village School of {town}", "The {town} School")

# Charter networks: made-up brands, each with campuses in counties far apart.
NETWORK_BRANDS: tuple[str, ...] = (
    "Solvane", "Tessaly", "Corvane", "Mireth", "Pellandra", "Zorwick", "Aldervane", "Brisca",
    "Calloran", "Dravenly", "Estmere", "Ombrelle",
)  # fmt: skip
NETWORK_KINDS: tuple[str, ...] = ("high", "academy", "system")
"""How a network is named: as high schools (``"SOLVANE HIGH SCHOOLS"``, campuses
``"SOLVANE H S OF ASHFIELD"``), as an academy (``"Tessaly Academy"``, campuses
``"Tessaly Academy - Ashfield"``) or as a school system (``"Corvane Public Schools"``,
campuses ``"Corvane Ashfield Academy"`` and ``"Corvane Ashfield College Preparatory"``)."""
NETWORK_STYLE = "network"
NETWORK_FORM = "network"
"""The :attr:`Identity.form` of a network and its campuses: no other listing names them."""
_NETWORKS_PER_STATE = 2
_NETWORK_APART_KM = 150.0
"""A network's counties lie at least this far apart, well beyond the matcher's reach."""
_NETWORK_COUNTIES = 4
_CAMPUS_FORMS: dict[str, tuple[str, ...]] = {
    "high": ("{B} H S OF {T}", "{B} H S - {T}", "{B} HIGH SCHOOL-{T}"),
    "academy": ("{b} Academy - {t}", "{b} Academy {t}"),
    "system": ("{b} {t} Academy", "{b} {t} College Preparatory"),
}

# Charter districts named as one academy, in one county, whose schools add a
# level or a part to the district's name.
ACADEMY_BRANDS: tuple[str, ...] = (
    "Arvenne", "Belvora", "Cindral", "Delmora", "Evandine", "Falmira", "Gorvelle", "Hestra",
    "Ilvane", "Jorvina", "Kelvara", "Lumira",
)  # fmt: skip
ACADEMY_STYLE = "academy"
ACADEMY_FORM = "academy"
"""The :attr:`Identity.form` of such a district and its schools: no other listing names them."""
NAMESAKE_STYLE = "namesake"
_NAMESAKES_PER_STATE = 2
_NAMESAKE_APART_KM = 150.0
"""A namesake lies in a county at least this far from its town's, well beyond the
matcher's reach."""
_NAMESAKE_PLURAL_SHARE = 0.4
_NAMESAKE_STYLES = frozenset({"me", "ks"})
"""States whose districts are named by code, which have no namesakes."""
_CHARTER_STYLES = frozenset({NETWORK_STYLE, ACADEMY_STYLE, NAMESAKE_STYLE})

# Markets of two states whose namesakes lie on either side of the counties.
BORDER_STYLE = "border"
BORDER_PAIRS: tuple[tuple[str, str], ...] = (("MA", "NH"), ("MO", "KS"), ("GA", "AL"), ("OH", "IN"))
"""A market's state, and a second state of the market (as WMUR's Boston market spans
Massachusetts and New Hampshire): see :meth:`_Generator.borders`."""
_BORDER_TOWNS = 4
_BORDER_NEAR_KM = (10.0, 40.0)
"""How far from the market's county the other state's county of a namesake lies,
mostly: within reach of the market, where a list strays."""
_BORDER_FAR_KM = (170.0, 230.0)
"""How far it lies otherwise: beyond reach, where a list does not."""
_BORDER_FAR_SHARE = 0.25
ACROSS_STYLE = "across"
ACROSS_PAIRS: tuple[tuple[str, str], ...] = (("MO", "KS"), ("TN", "VA"), ("KY", "OH"), ("IN", "IL"))
"""Two states of one market, each of which writes a town's district its own way (as
Missouri's ``"KANSAS CITY 33"`` and Kansas's ``"Kansas City"``, Tennessee's
``"Bristol"`` and Virginia's ``"Bristol City Public Schools"``): see
:meth:`_Generator.across`."""
_ACROSS_TOWNS = 4
_ACROSS_TWIN_KM = (1.0, 8.0)
"""How far apart twin towns across a state line lie, mostly: a list's point cannot
tell them apart."""
_ACROSS_APART_KM = (35.0, 160.0)
"""How far apart they lie otherwise: a point beside one of them tells them apart when
the other lies beyond a market's reach of it (:data:`NEAR_REACH_KM`), never within."""
_ACROSS_APART_SHARE = 0.4
NEAR_RATIO = 2.0
NEAR_SLACK_KM = 10.0
NEAR_MAX_KM = 160.0
NEAR_REACH_KM = 80.0
"""The rule a point breaks a tie by, read in whole states: the nearest wins when the
next lies at least ``NEAR_RATIO`` times as far plus ``NEAR_SLACK_KM``, it lies within
``NEAR_MAX_KM``, and every other lies farther than ``NEAR_REACH_KM`` from the point.
One within a market's reach is as much the market's: its point says nothing of which
the list means."""
SYSTEM_STYLE = "system"
"""A school system NCES splits into districts: see :meth:`_Generator.systems`."""
SYSTEM_KINDS: dict[str, tuple[str, ...]] = {
    "MT": ("mt_levels", "mt_levels", "mt_office", "mt_office_city", "mt_apart"),
    "CA": ("ca_union", "ca_office_city"),
    "AZ": ("az_levels",),
    "IL": ("il_levels",),
    "NY": ("ny_city",),
}
"""The school systems each state gets, by the NCES naming habit they imitate:

* ``mt_levels``: Montana's town districts of one name, one per level, at one office
  (``"Billings Elem"`` and ``"Billings H S"``);
* ``mt_office``: an elementary district named for its town and a high school
  district of another name at the same office (``"Kalispell Elem"`` and
  ``"Flathead H S"``); ``mt_office_city`` the same for a town that ends ``City``,
  whose high school district is its county's (``"Miles City Elem"`` and ``"Custer
  County H S"``);
* ``mt_apart``: the same pair with an office each (``"Boulder Elem"`` and
  ``"Jefferson H S"``), which is no system;
* ``ca_union``: California's ``"Julian Union Elementary"`` and ``"Julian Union
  High"``, an office each; ``ca_office_city`` its ``"Petaluma City Elementary"``
  and ``"Petaluma Joint Union High"``, at one office;
* ``az_levels``: Arizona's ``"Phoenix Elementary District (4256)"`` and ``"Phoenix
  Union High School District (4286)"``;
* ``il_levels``: Illinois's ``"Streator ESD 44"`` and ``"Streator Twp HSD 40"``;
* ``ny_city``: a city whose system NCES splits into geographic districts, as New
  York City's (``"NEW YORK CITY GEOGRAPHIC DISTRICT # 1"``, ``"NYC SPECIAL SCHOOLS
  - DISTRICT 75"``), beside a charter school of the city's name."""
SYSTEM_FORM = "system"
CITY_CHARTER = "ny_charter"
"""The :attr:`Identity.form` prefix of a system's records: ``"system:<kind>:<name>"``."""
TOWNSHIP_STYLE = "township"
TOWNSHIP_STATES: tuple[str, ...] = ("NJ", "PA", "MI", "OH")
"""States whose townships run school districts, two of one name in two counties: New
Jersey's ``"Union Township School District"`` (Hunterdon County) and ``"Township of
Union School District"`` (Union County). See :meth:`_Generator.townships`."""
_TOWNSHIP_TOWNS = 6
_TOWNSHIP_APART_KM = (30.0, 140.0)
"""How far apart two townships of one name lie: in two counties, some within a
market's reach of each other and some beyond it."""
TOWNSHIP_NAMES: tuple[tuple[str, str | None], ...] = (
    ("Township of {town} School District", "Township"),
    ("{town} Township School District", "Township"),
    ("{town} Township Public School District", "Township"),
    ("{town} School District", None),
)
"""How NCES writes a township's district, and the qualifier its name says: the word
order and the legal form are no part of the name, and New Jersey's names leave out
``Township`` as often as they say it (``"Cherry Hill School District"``)."""
TOWNSHIP_PAIRS: tuple[tuple[int, int], ...] = ((0, 1), (0, 2), (1, 2), (0, 3), (1, 3), (2, 3))
"""Which two of :data:`TOWNSHIP_NAMES` two townships of one name are written with."""
LEADING_STYLE = "leading"
_LEADING_PER_STATE = 3
LEADING_WORDS: tuple[str, ...] = (
    "Kid", "Tiny", "Bright", "Merry", "Sunny", "Wonder", "Jolly", "Dandy",
)  # fmt: skip
"""Made-up words a school's name puts before a place word (``"Kid City Academy"``)."""
_LeftOut = tuple[str, tuple[str, ...], str | None]
"""A listing that leaves out a school's place word: its text, the base and noun it says."""
LEADING_SCHOOLS: tuple[tuple[str, tuple[str, ...], str, bool, tuple[_LeftOut, ...]], ...] = (
    (
        "Village {f} Academy",
        ("Village",),
        "Academy",
        True,
        (("{f} Academy", (), "Academy"), ("{F} ACADEMY", (), "Academy")),
    ),
    (
        "Village {f} School",
        ("Village",),
        "School",
        True,
        (("{f} School", (), "School"), ("{f}", (), None)),
    ),
    (
        "Town & Country Day School",
        ("Town & Country Day",),
        "School",
        False,
        (
            ("Country Day School", ("Country Day",), "School"),
            ("Country Day", ("Country Day",), None),
            ("COUNTRY DAY SCHOOL", ("Country Day",), "School"),
        ),
    ),
    (
        "City Academy",
        ("City",),
        "Academy",
        False,
        (("Academy", (), "Academy"), ("The Academy", (), "Academy"), ("ACADEMY", (), "Academy")),
    ),
    (
        "{w} City Academy",
        ("{w} City",),
        "Academy",
        False,
        (
            ("{w} Academy", ("{w}",), "Academy"),
            ("{w}s Academy", ("{w}s",), "Academy"),
            ("{W} ACADEMY", ("{w}",), "Academy"),
        ),
    ),
    (
        "Village Montessori School",
        ("Village", "Montessori"),
        "School",
        False,
        (("Montessori School", ("Montessori",), "School"), ("Montessori", ("Montessori",), None)),
    ),
    (
        "{w} Village Academy",
        ("{w} Village",),
        "Academy",
        False,
        (("{w} Academy", ("{w}",), "Academy"), ("{w}s Academy", ("{w}s",), "Academy")),
    ),
    (
        "{w} Town School",
        ("{w} Town",),
        "School",
        False,
        (("{w} School", ("{w}",), "School"), ("{W} SCHOOL", ("{w}",), "School")),
    ),
)
"""Private schools whose names begin with a place word (``Village``, ``City``, ``Town``)
or hold one after a word that is no place's name, and how a listing that leaves the
word out names them: the name (``{f}`` a faith, ``{w}`` one of :data:`LEADING_WORDS`),
its base and noun, whether it has a faith, and the listings without the place word.
``"Christian Academy"`` is not ``"Village Christian Academy"``, ``"Country Day
School"`` not ``"Town & Country Day School"``, ``"Academy"`` not ``"City Academy"``
and ``"Kids Academy"`` not ``"Kid City Academy"``: the word is the name's own, not a
qualifier a list may leave out."""
LEVEL_STYLE = "level"
GRADE_SPANS: dict[str, tuple[str, str, str]] = {
    "PK-KG": ("PK", "KG", "Elementary"),
    "PK-1": ("PK", "01", "Elementary"),
    "PK-2": ("PK", "02", "Elementary"),
    "K-5": ("KG", "05", "Elementary"),
    "3-5": ("03", "05", "Elementary"),
    "PK-8": ("PK", "08", "Elementary"),
    "5-8": ("05", "08", "Middle"),
    "6-8": ("06", "08", "Middle"),
    "7-9": ("07", "09", "Middle"),
    "9-12": ("09", "12", "High"),
    "7-12": ("07", "12", "High"),
    "K-12": ("KG", "12", "Other"),
}
"""Grade spans a generated school teaches, as NCES codes its lowest and highest grade,
and the NCES level it is."""
LEVEL_SPANS: dict[str, str] = {
    "elementary": "K-5",
    "primary": "PK-2",
    "intermediate": "3-5",
    "middle": "6-8",
    "juniorhigh": "7-9",
    "high": "9-12",
    "prekindergarten": "PK-KG",
}
"""The grades of a generated school whose name says its level."""
TAUGHT: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "PK-KG": (frozenset({"prekindergarten", "elementary", "primary"}), frozenset()),
    "PK-1": (frozenset({"prekindergarten", "elementary", "primary"}), frozenset()),
    "K-5": (frozenset({"elementary", "primary"}), frozenset({"intermediate"})),
    "PK-8": (
        frozenset({"elementary"}),
        frozenset({"prekindergarten", "primary", "intermediate", "middle", "juniorhigh"}),
    ),
    "5-8": (frozenset({"middle", "juniorhigh", "intermediate"}), frozenset()),
    "6-8": (frozenset({"middle", "juniorhigh", "intermediate"}), frozenset()),
    "9-12": (frozenset({"high"}), frozenset()),
    "7-12": (frozenset({"high", "juniorhigh"}), frozenset({"middle"})),
    "K-12": (
        frozenset(),
        frozenset({"elementary", "primary", "intermediate", "middle", "juniorhigh", "high"}),
    ),
}
"""The oracle's reading of a school whose name says no level, by its grades: the levels
a listing names it by, and the levels a listing may mean it by, though not surely.

A school of K-5 is an elementary or a primary school, and teaches an intermediate
school's grades 4 and 5 among others; one of PK-8 is an elementary school, and teaches
the grades of a preschool, a primary, an intermediate, a middle and a junior high
school among many more; one of 6-8 is a middle, an intermediate or a junior high
school; one of K-12 teaches every level's grades and is none of them; none of them
is a high school but one of 9-12 or 7-12. A listing that says a level these leave
out names no such school."""
_LEVEL_GROUPS_PER_STATE = 2
LEVEL_GROUPS: tuple[str, ...] = (
    "bare", "school", "parish", "control", "combined", "lone", "preschool", "junior",
)  # fmt: skip
"""Kinds of schools whose names leave out their level (:meth:`_Generator.levels`)."""
FORENAME_STYLE = "forename"
_FORENAME_GROUPS_PER_STATE = 3
FORENAME_GROUPS: tuple[str, ...] = (
    "pair", "pair_given", "lone_initials", "lone_initial", "lone_given", "exact", "two_initials",
    "bracket", "bracket_lone", "roman",
)  # fmt: skip
"""Kinds of schools named for a person in one county (:meth:`_Generator.forenames`)."""
FORENAME_SURNAMES: tuple[str, ...] = tuple(
    head + tail
    for head in ("Brax", "Corv", "Dren", "Falk", "Grem", "Hask", "Jorv", "Lorn", "Mirk", "Quen")
    for tail in ("combe", "stow", "wright", "more", "den", "holt")
)
"""Made-up surnames no other generated name bears, one per group of a state."""
FORENAME_INITIALS: tuple[str, ...] = ("R. D.", "A. B.", "W. T.", "H. L.", "E. M.", "G. P.")
ROMAN_INITIALS: tuple[str, ...] = ("J. I.", "C. V.", "R. V.", "J. V.", "U. X.")
"""Initials whose second letter is a Roman numeral after a district prefix's letter
(``"R-V"``): a person's, where they are dotted (``"J. I. Watson"``)."""
BRACKET_FORENAME_STATES: tuple[str, ...] = ("CA", "DE")
"""States whose NCES names give a person's forenames in brackets after the surname."""
PLURAL_STYLE = "plural"
_PLURAL_GROUPS_PER_STATE = 2
PLURAL_WORDS: tuple[str, ...] = (
    "Brook", "Oak", "Lake", "Park", "Grove", "Hill", "Meadow", "Pine", "Field", "Glade",
    "Ridge", "Spring",
)  # fmt: skip
"""Words a school may be named for with a plural's ``s`` or without it, two names."""
PLURAL_GROUPS: tuple[str, ...] = ("plural", "singular", "both")
_SPECIAL_STYLES = _CHARTER_STYLES | {
    BORDER_STYLE,
    SYSTEM_STYLE,
    ACROSS_STYLE,
    TOWNSHIP_STYLE,
    LEADING_STYLE,
    LEVEL_STYLE,
    FORENAME_STYLE,
    PLURAL_STYLE,
}
"""Records the ordinary listings leave alone: each has listings of its own."""
"""The charter networks, the academy districts and the namesakes, which only their
own listings name."""
_ACADEMIES_PER_STATE = 2
ACADEMY_SCHOOLS: dict[str, tuple[tuple[str, str | None, str | None], ...]] = {
    "levels": (
        ("{b} Academy Elementary", "elementary", None),
        ("{b} Academy Middle", "middle", None),
    ),
    "parts": (
        ("{B} ACADEMY MIDDLE", "middle", None),
        ("{B} ACADEMY UPPER EL", "elementary", "Upper"),
        ("{B} ACADEMY LOWER EL", "elementary", "Lower"),
    ),
    "hyphen": (
        ("{B} ACADEMY-MIDDLE", "middle", None),
        ("{B} ACADEMY-UPPER", None, "Upper"),
        ("{B} ACADEMY-LOWER", None, "Lower"),
    ),
}
"""How such a district's schools are named, as ``(form, level, part)``: each is the
district's name and a level (``"Arvenne Academy Elementary"`` and ``"Arvenne Academy
Middle"``), or one is and the rest add a part too (``"BELVORA ACADEMY MIDDLE"`` beside
``"BELVORA ACADEMY UPPER EL"`` and ``"BELVORA ACADEMY LOWER EL"``, ``"CINDRAL
ACADEMY-MIDDLE"`` beside ``"CINDRAL ACADEMY-UPPER"``)."""

BRACKET_STYLE = "bracket"
COUNTY_BRACKET_STATES = frozenset({"WA", "MI", "AR"})
"""States whose NCES names end two districts of one name with their counties'."""
ENTITY_NUMBER_STATES = frozenset({"AZ"})
"""States whose NCES names end every district's name with its entity number."""
SECOND_NAME_STATES = frozenset({"NY"})
"""States whose NCES names end some districts' names with a second name."""
_SECOND_NAMES_PER_STATE = 3
SECOND_NAMES: tuple[str, ...] = (
    "Lake Vesper", "Red Harrow", "Kestrequa", "Marlow Hills", "North Tamsin", "Brindle Point",
    "Coldwater Run", "Hollins Gap",
)  # fmt: skip
"""Made-up second names a district is known by (``"(LAKE VESPER)"``)."""

LEVELS: tuple[str, ...] = (
    "elementary", "elementary", "elementary", "elementary", "middle", "middle", "high",
    "high", "juniorhigh", "intermediate", "primary",
)  # fmt: skip

# How each level is spelled: NCES habits by state style, and listing habits.
LEVEL_NCES: dict[str, dict[str, tuple[str, ...]]] = {
    "plain": {
        "elementary": ("Elementary School", "Elementary", "Elem"),
        "middle": ("Middle School", "Middle"),
        "high": ("High School", "High", "Senior High School"),
        "juniorhigh": ("Junior High School", "Jr High"),
        "intermediate": ("Intermediate School", "Intermediate"),
        "primary": ("Primary School", "Primary"),
    },
    "pa": {
        "elementary": ("El Sch", "Elementary School"),
        "middle": ("MS", "Middle School"),
        "high": ("HS", "Senior High School"),
        "juniorhigh": ("Junior High School",),
        "intermediate": ("Intermediate School",),
        "primary": ("Primary School",),
    },
    "tx": {
        "elementary": ("EL", "ELEMENTARY"),
        "middle": ("MIDDLE", "MIDDLE SCHOOL"),
        "high": ("H S", "HIGH SCHOOL"),
        "juniorhigh": ("J H", "JUNIOR HIGH"),
        "intermediate": ("INT", "INTERMEDIATE"),
        "primary": ("PRI", "PRIMARY"),
    },
}
LEVEL_LISTING: dict[str, tuple[str, ...]] = {
    "elementary": ("Elementary School", "Elementary", "Elem.", "Elem", "ES", "Elementary Sch."),
    "middle": ("Middle School", "Middle", "MS", "Middle Sch"),
    "high": ("High School", "High", "HS", "H.S.", "Senior High", "Sr. High School"),
    "juniorhigh": ("Junior High", "Jr. High", "JHS", "Junior High School"),
    "intermediate": ("Intermediate", "Intermediate School", "Intermed."),
    "primary": ("Primary", "Primary School"),
}


@dataclass(frozen=True, slots=True)
class Identity:
    """What a listing has to say to mean a record: the test oracle's view of it."""

    kind: str
    base: tuple[str, ...]
    level: str | None = None
    noun: str | None = None
    qualifier: str | None = None
    numbers: tuple[str, ...] = ()
    affiliation: str | None = None
    legal: str | None = None
    saint: bool = False
    initial: str | None = None
    street: tuple[str, str] | None = None
    form: str | None = None
    """For a civic body (kind ``"civic"``): how the listing names it, ``"City of {town}"``.
    For a private school named for its town: its name (``"Village School of {town}"``),
    which a listing must repeat."""
    codes: tuple[str, ...] = ()
    """District codes, as series and number (``"RSU 13"``, ``"MSAD 17"``, ``"USD 320"``).
    On a district: the codes it answers to. On a listing: the codes it gives."""
    coded: bool = False
    """The district's name is only its codes (``"RSU 13"``): a listing must give one,
    and may add its town (:attr:`base`)."""
    hidden: bool = False
    """The district's codes are not in its name (Kansas's ``"USD 320"`` for ``"Ashfield"``),
    so no listing's code can be checked against it."""
    aliases: tuple[str, ...] = ()
    """Second names a district is known by, which a listing may give for its base
    (``"Lake Vesper"`` for ``"ASHFIELD CENTRAL SCHOOL DISTRICT (LAKE VESPER)"``)."""
    grades: str | None = None
    """A school's grades, a key of :data:`GRADE_SPANS`, when they are known. For a
    school whose name says no level, they say which levels a listing names it by
    (:data:`TAUGHT`); a school whose name says its level has that level's
    (:data:`LEVEL_SPANS`)."""
    surname: str | None = None
    """For a school named for a person: the surname, which the person's name in
    :attr:`base` ends with. A listing may name the school by it alone, leaving the
    forenames out (:func:`person_fit`)."""
    given: tuple[str, ...] = ()
    """The forenames before the surname as the name writes them: ``("Amelia",)``,
    ``("Amelia", "R.")``, initials only (``("R.", "D.")``). On a listing, the ones it
    says, which may be none."""
    bracketed: bool = False
    """The record's name gives its person's forenames in brackets after the surname,
    as California and Delaware write NCES names (``"Whitcombe (Clara) Elementary"``),
    which says they are a person's forenames."""


@dataclass(frozen=True, slots=True)
class SyntheticRecord:
    """A generated directory record and its identity."""

    record: DirectoryRecord
    identity: Identity
    style: str


@dataclass(frozen=True, slots=True)
class Case:
    """A labelled listing: the matcher should accept ``expected`` (an id) or nothing.

    A listing that names a school system NCES splits into districts names every
    one of them: ``expected`` and :attr:`also`, in any order (:attr:`targets`).
    """

    listing: str
    states: tuple[str, ...]
    expected: str | None
    counties: tuple[str, ...] | None = None
    near: tuple[float, float] | None = None
    note: str = ""
    category: str | None = None
    """The section a list files the listing under (``"Schools"``, ``"Churches"``)."""
    also: tuple[str, ...] = ()
    """The other records the listing names with ``expected``: a school system's districts."""

    @property
    def targets(self) -> frozenset[str]:
        """Every id the listing should name: ``expected`` and :attr:`also`; none for no match."""
        if self.expected is None:
            return frozenset()
        return frozenset((self.expected, *self.also))


# -- directory ------------------------------------------------------------------

_ROMAN = ("", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")
_COUNTY_STATES = frozenset({"AL", "GA", "TN", "KY", "VA", "NC", "SC", "FL", "MD", "WV", "LA"})


def _state_style(state: str) -> str:
    styles = {"TX": "tx", "PA": "pa", "MO": "mo", "OH": "oh", "CA": "ca", "IL": "il"}
    styles.update({"NY": "ny", "NJ": "nj", "IA": "iaw", "WI": "iaw", "IN": "in", "VT": "vt"})
    styles.update({"ME": "me", "KS": "ks"})
    if state in _COUNTY_STATES:
        return "county"
    return styles.get(state, "plain")


def _person_identity(person: str, level: str) -> Identity:
    """A school of ``level`` named for ``person``, ``"Given Surname"``."""
    given, surname = person.split(" ")
    return Identity("school", (person,), level=level, surname=surname, given=(given,))


def _upper_if(text: str, upper: bool) -> str:
    return text.upper() if upper else text


class _Generator:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)  # noqa: S311 - test data, not cryptography
        self.records: list[SyntheticRecord] = []
        self.count = {"district": 0, "school": 0}
        self.pools: dict[str, list[int]] = {}
        # Codes draw from their own generator, so the rest of the directory is
        # the same whichever states name their districts by code.
        self.code_rng = random.Random(seed + 1)  # noqa: S311 - test data, not cryptography
        # So do the towns named for a direction from another.
        self.direction_rng = random.Random(seed + 2)  # noqa: S311 - test data, not cryptography
        # And the districts named for more than their town, and the private
        # schools named for a town.
        self.place_rng = random.Random(seed + 3)  # noqa: S311 - test data, not cryptography
        # And the charter networks, which come after every state's districts.
        self.network_rng = random.Random(seed + 4)  # noqa: S311 - test data, not cryptography
        # And the charter districts named as one academy, after the networks.
        self.academy_rng = random.Random(seed + 5)  # noqa: S311 - test data, not cryptography
        # And the districts named for a town elsewhere, after the academies.
        self.namesake_rng = random.Random(seed + 6)  # noqa: S311 - test data, not cryptography
        # And the brackets NCES ends some names with.
        self.bracket_rng = random.Random(seed + 7)  # noqa: S311 - test data, not cryptography
        # And the namesakes on either side of a market's counties.
        self.border_rng = random.Random(seed + 8)  # noqa: S311 - test data, not cryptography
        # And the school systems NCES splits into districts.
        self.system_rng = random.Random(seed + 9)  # noqa: S311 - test data, not cryptography
        # And the twin towns across a state line.
        self.across_rng = random.Random(seed + 10)  # noqa: S311 - test data, not cryptography
        # And the townships of one name in two counties.
        self.township_rng = random.Random(seed + 11)  # noqa: S311 - test data, not cryptography
        # And the schools whose names begin with a place word, last of all.
        self.leading_rng = random.Random(seed + 12)  # noqa: S311 - test data, not cryptography
        self.county_roots: dict[str, str] = {}
        self.town_districts: dict[str, list[SyntheticRecord]] = defaultdict(list)
        self.counties: dict[str, list[tuple[str, str, tuple[float, float]]]] = {}
        self.county_towns: dict[str, list[tuple[str, tuple[float, float]]]] = defaultdict(list)
        self.county_districts: dict[str, list[SyntheticRecord]] = defaultdict(list)
        # And the schools whose names leave out their level, after them.
        self.level_rng = random.Random(seed + 13)  # noqa: S311 - test data, not cryptography
        # And the schools named for a person, and for a word with a plural's s or
        # without it, last of all.
        self.forename_rng = random.Random(seed + 14)  # noqa: S311 - test data, not cryptography
        self.plural_rng = random.Random(seed + 15)  # noqa: S311 - test data, not cryptography

    def _numbers(self, districts: int) -> None:
        """Fresh number pools for one state's district codes.

        Maine numbers its units and its administrative districts separately,
        from the same range, so the two series share numbers.
        """
        top = max(60, districts * 3 // 2)
        for series in ("RSU", "MSAD", "USD"):
            pool = list(range(1, top + 1)) if series != "USD" else list(range(101, 101 + top * 2))
            self.code_rng.shuffle(pool)
            self.pools[series] = pool

    def _coded_district(self, style: str, town: str) -> tuple[str, Identity]:
        """A Maine district named by code, or a Kansas one by town with a hidden number."""
        rng = self.code_rng
        self.rng.random()  # what the plain style draws, to keep the rest of the directory
        if style == "ks":
            code = f"USD {self.pools['USD'].pop()}"
            name = town if rng.random() < 0.8 else f"{town} Public Schools"
            return name, Identity("district", (town,), codes=(code,), hidden=True)
        pick = rng.random()
        if pick < 0.2:
            return f"{town} Public Schools", Identity("district", (town,))
        unit, administrative = self.pools["RSU"].pop(), self.pools["MSAD"].pop()
        width = "02d" if rng.random() < 0.5 else "d"
        codes: tuple[str, ...]
        if pick < 0.6:
            name, codes = f"RSU {unit:{width}}", (f"RSU {unit}",)
        elif pick < 0.85:
            name = f"RSU {unit:{width}}/MSAD {administrative:{width}}"
            codes = (f"RSU {unit}", f"MSAD {administrative}")
        else:
            name, codes = f"MSAD {administrative}", (f"MSAD {administrative}",)
        return name, Identity("district", (town,), codes=codes, coded=True)

    def _id(self, kind: str) -> str:
        self.count[kind] += 1
        prefix = "D" if kind == "district" else "S"
        return f"SYN-{prefix}-{self.count[kind]:07d}"

    def _add(  # noqa: PLR0913 - one argument per NCES column
        self,
        *,
        kind: str,
        name: str,
        identity: Identity,
        style: str,
        state: str,
        county: str,
        district_id: str | None,
        city: str,
        point: tuple[float, float],
    ) -> DirectoryRecord:
        """Add a record; a school gets the grades its identity says, or its level's."""
        span = None
        if kind == "school":
            span = identity.grades or LEVEL_SPANS.get(identity.level or "")
            if span is not None and identity.grades is None:
                identity = replace(identity, grades=span)
        low, high, level = GRADE_SPANS[span] if span is not None else (None, None, None)
        record = DirectoryRecord(
            id=self._id(kind),
            name=name,
            kind="district" if kind == "district" else "school",
            district_id=district_id,
            state=state,
            county_fips=county,
            city=city,
            lat=round(point[0], 6),
            lon=round(point[1], 6),
            county=f"{self.county_roots[county]} County",
            grade_low=low,
            grade_high=high,
            level=level,
        )
        self.records.append(SyntheticRecord(record, identity, style))
        if kind == "district" and style not in _SPECIAL_STYLES:
            self.county_districts[county].append(self.records[-1])
        return record

    def _near(self, point: tuple[float, float], spread: float) -> tuple[float, float]:
        rng = self.rng
        return (point[0] + rng.uniform(-spread, spread), point[1] + rng.uniform(-spread, spread))

    def _district_name(  # noqa: PLR0911, PLR0912 - one branch per state's naming habit
        self, style: str, town: str, county_root: str
    ) -> tuple[str, Identity]:
        rng = self.rng
        number = str(rng.randint(1, 12))
        if style in {"me", "ks"}:
            return self._coded_district(style, town)
        if style == "tx":
            legal = rng.choice(("ISD", "ISD", "CISD"))
            return f"{town.upper()} {legal}", Identity("district", (town,), legal=legal)
        if style == "mo":
            prefix = rng.choice(("R", "R", "C"))
            return f"{town.upper()} {prefix}-{_ROMAN[int(number)]}", Identity(
                "district", (town,), numbers=(number,)
            )
        if style == "pa":
            if rng.random() < 0.5:
                return f"{town} Area SD", Identity("district", (town,), qualifier="Area")
            return f"{town} SD", Identity("district", (town,))
        if style == "oh":
            pick = rng.random()
            if pick < 0.45:
                return f"{town} Local", Identity("district", (town,), qualifier="Local")
            if pick < 0.7:
                return f"{town} Exempted Village", Identity(
                    "district", (town,), qualifier="Village", legal="Exempted Village"
                )
            return f"{town} City", Identity("district", (town,), qualifier="City")
        if style == "vt":
            if rng.random() < 0.6:
                return f"{town} Town School District", Identity(
                    "district", (town,), qualifier="Town"
                )
            return f"{town} School District", Identity("district", (town,))
        if style == "ca":
            if rng.random() < 0.7:
                return f"{town} Unified", Identity("district", (town,), legal="Unified")
            return f"{town} Elementary", Identity("district", (town,), level="elementary")
        if style == "il":
            number = str(rng.randint(1, 399))
            legal = rng.choice(("CUSD", "SD", "CCSD"))
            return f"{town} {legal} {number}", Identity(
                "district", (town,), numbers=(number,), legal=legal
            )
        if style == "ny":
            legal = rng.choice(("CENTRAL", "UNION FREE"))
            return f"{town.upper()} {legal} SCHOOL DISTRICT", Identity(
                "district", (town,), legal=legal
            )
        if style == "nj":
            if rng.random() < 0.5:
                return f"{town} Township School District", Identity(
                    "district", (town,), qualifier="Township"
                )
            return f"{town} School District", Identity("district", (town,))
        if style == "iaw":
            return f"{town} Community School District", Identity(
                "district", (town,), legal="Community"
            )
        if style == "in":
            return f"{town} School Corporation", Identity("district", (town,))
        if style == "county":
            if rng.random() < 0.75:
                return f"{county_root} County", Identity(
                    "district", (county_root,), qualifier="County"
                )
            return f"{town} City", Identity("district", (town,), qualifier="City")
        if rng.random() < 0.5:
            return f"{town} School District", Identity("district", (town,))
        return f"{town} Public Schools", Identity("district", (town,))

    def _school_base(self, town: str, level: str) -> tuple[Identity, str]:
        """Pick what a public school is named for; return its identity and NCES spelling."""
        rng = self.rng
        pick = rng.random()
        if pick < 0.55:
            person = f"{rng.choice(GIVEN_NAMES)} {rng.choice(ALL_SURNAMES)}"
            initial = rng.choice("ABCDEFGHJKLMNPRSTW") if rng.random() < 0.5 else None
            given, surname = person.split(" ")
            written = f"{given} {initial}. {surname}" if initial else person
            forenames = (given, f"{initial}.") if initial else (given,)
            identity = Identity(
                "school", (person,), level=level, initial=initial, surname=surname, given=forenames
            )
            return identity, written
        if pick < 0.67:
            street, (long_form, short_form) = rng.choice(STREETS), rng.choice(STREET_KINDS)
            written = f"{street} {long_form if rng.random() < 0.5 else short_form}"
            base = f"{street} {long_form}"
            identity = Identity("school", (base,), level=level, street=(long_form, short_form))
            return identity, written
        base = rng.choice((*NAMESAKES, town, town, f"North {town}"))
        return Identity("school", (base,), level=level), base

    def _school_name(self, style: str, base: str, level: str) -> str:
        spelling = LEVEL_NCES.get(style, LEVEL_NCES["plain"])[level]
        name = f"{base} {self.rng.choice(spelling)}"
        return name.upper() if style == "tx" else name

    def _neighbour(
        self,
        *,
        parent: DirectoryRecord,
        identity: Identity,
        style: str,
        town: str,
        point: tuple[float, float],
    ) -> None:
        """A district named for its direction from ``parent``'s town, in the same county.

        ``"East Ashfield Area SD"`` beside ``"Ashfield Area SD"``, ``"NORTH
        ASHFIELD ISD"`` beside ``"ASHFIELD ISD"``, ``"West Abernathy County"``
        beside ``"Abernathy County"``: the parent's name with the direction
        before its base, and one or two schools named for the new town.
        """
        rng = self.direction_rng
        direction = rng.choice(DIRECTIONS)
        base = identity.base[0]
        named = f"{direction} {base}"
        name = parent.name.replace(base, named).replace(base.upper(), named.upper())
        codes = identity.codes
        if identity.hidden:
            # Kansas: a USD number of its own, from the other end of the pool.
            codes = (f"USD {self.pools['USD'].pop(0)}",)
        city = f"{direction} {town}"
        spot = (point[0] + rng.uniform(-0.05, 0.05), point[1] + rng.uniform(-0.05, 0.05))
        district = self._add(
            kind="district",
            name=name,
            identity=replace(identity, base=(named,), codes=codes),
            style=style,
            state=parent.state,
            county=parent.county_fips or "",
            district_id=None,
            city=city,
            point=spot,
        )
        for _ in range(rng.choice((1, 2))):
            level = identity.level or rng.choice(LEVELS)
            spelling = rng.choice(LEVEL_NCES.get(style, LEVEL_NCES["plain"])[level])
            school = f"{direction} {town} {spelling}"
            self._add(
                kind="school",
                name=school.upper() if style == "tx" else school,
                identity=Identity("school", (f"{direction} {town}",), level=level),
                style=style,
                state=parent.state,
                county=parent.county_fips or "",
                district_id=district.id,
                city=city,
                point=spot,
            )

    def _private(self, state: str, county: str, town: str, point: tuple[float, float]) -> None:
        rng = self.rng
        pick = rng.random()
        if pick < 0.4:
            saint = rng.choice(SAINTS)
            affiliation = "Catholic" if rng.random() < 0.5 else None
            spelled = f"St {saint}" if rng.random() < 0.5 else f"St. {saint}'s"
            name = f"{spelled} {affiliation + ' ' if affiliation else ''}School"
            identity = Identity(
                "school",
                (saint,),
                noun="School",
                affiliation=affiliation,
                saint=True,
                grades="PK-8",
            )
        elif pick < 0.65:
            base = rng.choice((*NAMESAKES, town))
            name = f"{base} Christian Academy"
            identity = Identity("school", (base,), noun="Academy", affiliation="Christian")
        elif pick < 0.8:
            name = f"{town} Montessori School"
            identity = Identity("school", (town, "Montessori"), noun="School")
        elif pick < 0.9:
            # A private school system named for its town: "Ashfield Christian Schools".
            affiliation = rng.choice(SYSTEM_FAITHS)
            name = f"{town} {affiliation} Schools"
            identity = Identity("school", (town,), noun="Schools", affiliation=affiliation)
        elif pick < 0.95:
            # A high school named for a college: "Ashfield College High School".
            name = f"{town} College High School"
            identity = Identity("school", (town, "College"), level="high")
        else:
            name = f"{town} University Academy"
            identity = Identity("school", (town, "University"), noun="Academy")
        upper = rng.random() < 0.6
        self._add(
            kind="school",
            name=_upper_if(name, upper),
            identity=identity,
            style="private",
            state=state,
            county=county,
            district_id=None,
            city=town,
            point=self._near(point, 0.2),
        )

    def _valley(
        self, style: str, town: str, district: Identity, name: str
    ) -> tuple[str, Identity, bool]:
        """Maybe rename a district for more than its town: ``"Ashfield Valley Unified"``.

        Returns the name, the identity and whether it was renamed.
        """
        form = _VALLEY_DISTRICT.get(style)
        if form is None or self.place_rng.random() >= _VALLEY_SHARE:
            return name, district, False
        legal = "Unified" if style == "ca" else None
        return form.format(town=town), Identity("district", (f"{town} Valley",), legal=legal), True

    def _town_private(self, state: str, county: str, town: str, point: tuple[float, float]) -> None:
        """A private school named for a town no public school is named for."""
        rng = self.place_rng
        form = rng.choice(TOWN_PRIVATE_FORMS)
        name = form.format(town=town)
        self._add(
            kind="school",
            name=name.upper() if rng.random() < 0.6 else name,
            identity=Identity("school", (town,), noun="School", form=form),
            style="private",
            state=state,
            county=county,
            district_id=None,
            city=town,
            point=(point[0] + rng.uniform(-0.05, 0.05), point[1] + rng.uniform(-0.05, 0.05)),
        )

    def state(self, index: int, state: str, districts: int, private: int) -> None:
        rng = self.rng
        style = _state_style(state)
        self._numbers(districts)
        center = (30.0 + (index // 10) * 3.5, -120.0 + (index % 10) * 5.5)
        towns = rng.sample(
            [p + s for p in TOWN_PREFIXES for s in TOWN_SUFFIXES],
            k=min(max(districts * 2, 40), len(TOWN_PREFIXES) * len(TOWN_SUFFIXES)),
        )
        county_count = max(4, min(99, districts // 5))
        counties = [
            (f"9{index:02d}{k:02d}", rng.choice(COUNTY_ROOTS), self._near(center, 1.6))
            for k in range(county_count)
        ]
        self.counties[state] = counties
        self.county_roots.update((fips, root) for fips, root, _point in counties)
        for d in range(districts):
            town = towns[d]
            county, county_root, county_point = counties[d % county_count]
            name, district_identity = self._district_name(style, town, county_root)
            name, district_identity, valley = self._valley(style, town, district_identity, name)
            identity = district_identity
            district_point = self._near(county_point, 0.15)
            self.county_towns[county].append((town, district_point))
            district = self._add(
                kind="district",
                name=name,
                identity=identity,
                style=style,
                state=state,
                county=county,
                district_id=None,
                city=town,
                point=district_point,
            )
            if (
                not valley
                and style not in _NAMESAKE_STYLES
                and identity.base == (town,)
                and identity.qualifier not in {"County", "Township"}
            ):
                self.town_districts[state].append(self.records[-1])
            named_for_town = valley
            for _ in range(rng.choice((1, 2, 3, 4, 6, 8, 10, 14))):
                level = rng.choice(LEVELS)
                if identity.level is not None:
                    level = identity.level
                identity, written = self._school_base(town, level)
                named_for_town = named_for_town or identity.base == (town,)
                school_county = county
                if rng.random() < 0.1:
                    school_county = counties[(d + 1) % county_count][0]
                self._add(
                    kind="school",
                    name=self._school_name(style, written, level),
                    identity=identity,
                    style=style,
                    state=state,
                    county=school_county,
                    district_id=district.id,
                    city=town,
                    point=self._near(district_point, 0.1),
                )
            if valley:
                high = self.place_rng.choice(_VALLEY_HIGH).format(town=town)
                self._add(
                    kind="school",
                    name=high,
                    identity=Identity("school", (town,), level="high"),
                    style=style,
                    state=state,
                    county=county,
                    district_id=district.id,
                    city=town,
                    point=district_point,
                )
            elif not named_for_town and self.place_rng.random() < _TOWN_PRIVATE_SHARE:
                self._town_private(state, county, town, district_point)
            if style != "me" and self.direction_rng.random() < _NEIGHBOUR_SHARE:
                self._neighbour(
                    parent=district,
                    identity=district_identity,
                    style=style,
                    town=town,
                    point=district_point,
                )
        for p in range(private):
            county, _root, county_point = counties[p % county_count]
            self._private(state, county, towns[p % len(towns)], county_point)

    def networks(self, state: str) -> None:
        """Charter networks whose campuses lie in counties of ``state`` far apart.

        Each network has an office and campuses in two to four counties at
        least :data:`_NETWORK_APART_KM` apart, one campus in some of them and two
        in others, in the counties' towns. A system's two campuses in one county
        share a town: an academy and a college preparatory school.
        """
        rng = self.network_rng
        brands = rng.sample(NETWORK_BRANDS, k=_NETWORKS_PER_STATE)
        for brand in brands:
            candidates = list(self.counties[state])
            rng.shuffle(candidates)
            chosen: list[tuple[str, str, tuple[float, float]]] = []
            for county in candidates:
                if all(haversine_km(county[2], other[2]) >= _NETWORK_APART_KM for other in chosen):
                    chosen.append(county)
                if len(chosen) == _NETWORK_COUNTIES:
                    break
            if len(chosen) < 2:  # pragma: no cover - every state's counties spread wide enough
                continue
            kind = rng.choice(NETWORK_KINDS)
            self._network(state, brand, kind, [c[0] for c in chosen])

    def _network(self, state: str, brand: str, kind: str, counties: list[str]) -> None:
        rng = self.network_rng
        office_town, office_point = rng.choice(self.county_towns[counties[0]])
        if kind == "high":
            name, level, noun = f"{brand.upper()} HIGH SCHOOLS", "high", None
        elif kind == "academy":
            name, level, noun = f"{brand} Academy", None, "Academy"
        else:
            name, level, noun = f"{brand} Public Schools", None, "Schools"
        district = self._add(
            kind="district",
            name=name.upper() if rng.random() < 0.5 else name,
            identity=Identity("district", (brand,), level=level, noun=noun, form=NETWORK_FORM),
            style=NETWORK_STYLE,
            state=state,
            county=counties[0],
            district_id=None,
            city=office_town,
            point=office_point,
        )
        doubled = rng.sample(range(len(counties)), k=max(1, len(counties) // 2))
        forms = _CAMPUS_FORMS[kind]
        for i, county in enumerate(counties):
            towns = self.county_towns[county]
            if i in doubled and kind == "system":
                picked = [(forms[0], rng.choice(towns)), (forms[1], None)]
            elif i in doubled:
                picked = [(rng.choice(forms), town) for town in rng.sample(towns, k=2)]
            else:
                picked = [(rng.choice(forms), rng.choice(towns))]
            last: tuple[str, tuple[float, float]] | None = None
            for form, where in picked:
                town, point = where if where is not None else last or towns[0]
                last = (town, point)
                campus = form.format(b=brand, t=town, B=brand.upper(), T=town.upper())
                campus_noun = "College Preparatory" if "College" in form else noun
                self._add(
                    kind="school",
                    name=campus,
                    identity=Identity(
                        "school", (brand, town), level=level, noun=campus_noun, form=NETWORK_FORM
                    ),
                    style=NETWORK_STYLE,
                    state=state,
                    county=county,
                    district_id=district.id,
                    city=town,
                    point=(
                        point[0] + rng.uniform(-0.03, 0.03),
                        point[1] + rng.uniform(-0.03, 0.03),
                    ),
                )

    def academies(self, state: str) -> None:
        """Charter districts named as one academy, each in one town of ``state``.

        ``"Arvenne Academy"`` with ``"Arvenne Academy Elementary"`` and ``"Arvenne
        Academy Middle"``, or ``"BELVORA ACADEMY"`` with ``"BELVORA ACADEMY
        MIDDLE"``, ``"BELVORA ACADEMY UPPER EL"`` and ``"BELVORA ACADEMY LOWER
        EL"`` (see :data:`ACADEMY_SCHOOLS`).
        """
        rng = self.academy_rng
        settled = [
            county for county, _root, _point in self.counties[state] if self.county_towns[county]
        ]
        for brand in rng.sample(ACADEMY_BRANDS, k=_ACADEMIES_PER_STATE):
            county = rng.choice(settled)
            town, point = rng.choice(self.county_towns[county])
            pattern = rng.choice(sorted(ACADEMY_SCHOOLS))
            upper = pattern != "levels"
            district = self._add(
                kind="district",
                name=_upper_if(f"{brand} Academy", upper),
                identity=Identity("district", (brand,), noun="Academy", form=ACADEMY_FORM),
                style=ACADEMY_STYLE,
                state=state,
                county=county,
                district_id=None,
                city=town,
                point=point,
            )
            for form, level, part in ACADEMY_SCHOOLS[pattern]:
                base = (brand,) if part is None else (brand, part)
                self._add(
                    kind="school",
                    name=form.format(b=brand, B=brand.upper()),
                    identity=Identity(
                        "school", base, level=level, noun="Academy", form=ACADEMY_FORM
                    ),
                    style=ACADEMY_STYLE,
                    state=state,
                    county=county,
                    district_id=district.id,
                    city=town,
                    point=(
                        point[0] + rng.uniform(-0.02, 0.02),
                        point[1] + rng.uniform(-0.02, 0.02),
                    ),
                )

    def namesakes(self, state: str) -> None:
        """Districts named for a town of ``state`` that lies far from them.

        Texas has two ``"EDGEWOOD ISD"``, one in the town of Edgewood and one
        named for a part of San Antonio 440 km away; Ohio an ``"Oak Hills Local"``
        in Cincinnati and an ``"Oak Hill Union Local"`` in the town of Oak Hill.
        Each namesake takes a town's district's name as it is (one that says no
        town qualifier: ``"ASHFIELD ISD"``, ``"Ashfield Public Schools"``), or
        with the town's name made plural (``"Ashfields Local"``), and lies in a
        county at least
        :data:`_NAMESAKE_APART_KM` from the town's that none of the town
        district's schools is in, in one of that county's towns, with two schools
        named for people.
        """
        rng = self.namesake_rng
        eligible = self.town_districts.get(state, [])
        counties = self.counties[state]
        home_points = {county: point for county, _root, point in counties}
        for item in rng.sample(eligible, k=min(_NAMESAKES_PER_STATE, len(eligible))):
            record = item.record
            assert record.county_fips is not None
            touched = {
                other.record.county_fips
                for other in self.records
                if other.record.district_id == record.id
            } | {record.county_fips}
            home = home_points[record.county_fips]
            far = [
                county
                for county, _root, point in counties
                if county not in touched
                and self.county_towns[county]
                and haversine_km(point, home) >= _NAMESAKE_APART_KM
            ]
            if not far:  # pragma: no cover - every state's counties spread wide enough
                continue
            county = rng.choice(far)
            host, point = rng.choice(self.county_towns[county])
            town = item.identity.base[0]
            # A town's district named "Ashfield City" or "Ashfield Local" says it is
            # the town's; one of that very name elsewhere is no namesake a list
            # could mean by the town's name, but one spelled otherwise is.
            plural = rng.random() < _NAMESAKE_PLURAL_SHARE or item.identity.qualifier is not None
            base = f"{town}s" if plural else town
            name = record.name.replace(town, base, 1).replace(town.upper(), base.upper(), 1)
            district = self._add(
                kind="district",
                name=name,
                identity=replace(item.identity, base=(base,)),
                style=NAMESAKE_STYLE,
                state=state,
                county=county,
                district_id=None,
                city=host,
                point=point,
            )
            for level, noun in (("elementary", "Elementary School"), ("high", "High School")):
                person = f"{rng.choice(GIVEN_NAMES)} {rng.choice(ALL_SURNAMES)}"
                self._add(
                    kind="school",
                    name=_upper_if(f"{person} {noun}", item.style == "tx"),
                    identity=_person_identity(person, level),
                    style=NAMESAKE_STYLE,
                    state=state,
                    county=county,
                    district_id=district.id,
                    city=host,
                    point=(
                        point[0] + rng.uniform(-0.02, 0.02),
                        point[1] + rng.uniform(-0.02, 0.02),
                    ),
                )

    def borders(self) -> None:
        """Namesakes in the two states of a market, on either side of its counties.

        For each of :data:`BORDER_PAIRS`, a few towns neither state has: in the
        market's state, in one of its counties, a district named by its town
        alone, as Massachusetts names them (``"Ashfield"``), with ``"Ashfield
        High"`` and a school named for a person; in the second state, in a
        county of its own beside that one, a district named by its town and
        legal form (``"Ashfield School District"``), with ``"Ashfield High
        School"`` and a school of the same person's name. Most such counties
        lie :data:`_BORDER_NEAR_KM` from the market's, where a list strays; some
        :data:`_BORDER_FAR_KM`, where it does not.
        """
        rng = self.border_rng
        for first, second in BORDER_PAIRS:
            if first not in self.counties or second not in self.counties:
                continue
            used = {
                item.record.city for item in self.records if item.record.state in {first, second}
            }
            fresh = [p + x for p in TOWN_PREFIXES for x in TOWN_SUFFIXES if p + x not in used]
            index = STATES.index(second)
            taken = {county for county, _root, _point in self.counties[second]}
            spare = [
                code
                for code in (f"9{index:02d}{k:02d}" for k in range(99, -1, -1))
                if code not in taken
            ]
            settled = [c for c in self.counties[first] if self.county_towns[c[0]]]
            for town, code in zip(rng.sample(fresh, k=_BORDER_TOWNS), spare, strict=False):
                county, _root, home = rng.choice(settled)
                far = rng.random() < _BORDER_FAR_SHARE
                away = rng.uniform(*(_BORDER_FAR_KM if far else _BORDER_NEAR_KM))
                heading = rng.uniform(0.0, 2 * math.pi)
                there = (
                    home[0] + away * math.sin(heading) / 111.2,
                    home[1] + away * math.cos(heading) / (111.2 * math.cos(math.radians(home[0]))),
                )
                self.county_roots[code] = rng.choice(COUNTY_ROOTS)
                self.counties[second].append((code, self.county_roots[code], there))
                person = f"{rng.choice(GIVEN_NAMES)} {rng.choice(ALL_SURNAMES)}"
                for state, place, name, noun in (
                    (first, county, town, "High"),
                    (second, code, f"{town} School District", "High School"),
                ):
                    where = home if state == first else there
                    district = self._add(
                        kind="district",
                        name=name,
                        identity=Identity("district", (town,)),
                        style=BORDER_STYLE,
                        state=state,
                        county=place,
                        district_id=None,
                        city=town,
                        point=where,
                    )
                    for school, identity in (
                        (f"{town} {noun}", Identity("school", (town,), level="high")),
                        (
                            f"{person} Elementary School",
                            _person_identity(person, "elementary"),
                        ),
                    ):
                        self._add(
                            kind="school",
                            name=school,
                            identity=identity,
                            style=BORDER_STYLE,
                            state=state,
                            county=place,
                            district_id=district.id,
                            city=town,
                            point=(where[0] + rng.uniform(-0.02, 0.02), where[1]),
                        )

    def across(self) -> None:
        """Twin towns across a state line, each state's district named its own way.

        For each of :data:`ACROSS_PAIRS`, a few towns neither state has: in a
        county of the first state, a district named as that state names a town's
        (:func:`_across_name`: Missouri's ``"ASHFIELD R-III"``, Tennessee's
        ``"Ashfield"``, Kentucky's ``"Ashfield Independent"``, Indiana's
        ``"Ashfield Community Schools"``); in a county of its own of the second
        state beside it, one named as the second names it (Kansas's
        ``"Ashfield"``, Virginia's ``"Ashfield City Public Schools"``, Ohio's
        ``"Ashfield Exempted Village"``, Illinois's ``"Ashfield CUSD 214"``). Each
        runs a high school named for the town and a school named for a person.
        Most twins lie :data:`_ACROSS_TWIN_KM` apart, as Kansas City's two halves
        or Bristol's; some :data:`_ACROSS_APART_KM`, within a market's reach of
        each other or beyond it.
        """
        rng = self.across_rng
        for first, second in ACROSS_PAIRS:
            used = {
                item.record.city for item in self.records if item.record.state in {first, second}
            }
            fresh = [p + x for p in TOWN_PREFIXES for x in TOWN_SUFFIXES if p + x not in used]
            index = STATES.index(second)
            taken = {county for county, _root, _point in self.counties[second]}
            spare = [
                code
                for code in (f"9{index:02d}{k:02d}" for k in range(99, -1, -1))
                if code not in taken
            ]
            settled = [c for c in self.counties[first] if self.county_towns[c[0]]]
            for town, code in zip(rng.sample(fresh, k=_ACROSS_TOWNS), spare, strict=False):
                county, _root, home = rng.choice(settled)
                apart = rng.random() < _ACROSS_APART_SHARE
                away = rng.uniform(*(_ACROSS_APART_KM if apart else _ACROSS_TWIN_KM))
                heading = rng.uniform(0.0, 2 * math.pi)
                office = (home[0] + rng.uniform(-0.05, 0.05), home[1] + rng.uniform(-0.05, 0.05))
                there = (
                    office[0] + away * math.sin(heading) / 111.2,
                    office[1]
                    + away * math.cos(heading) / (111.2 * math.cos(math.radians(office[0]))),
                )
                self.county_roots[code] = rng.choice(COUNTY_ROOTS)
                self.counties[second].append((code, self.county_roots[code], there))
                person = f"{rng.choice(GIVEN_NAMES)} {rng.choice(ALL_SURNAMES)}"
                for state, place, where in ((first, county, office), (second, code, there)):
                    name, identity = _across_name(rng, state, town)
                    district = self._add(
                        kind="district",
                        name=name,
                        identity=identity,
                        style=ACROSS_STYLE,
                        state=state,
                        county=place,
                        district_id=None,
                        city=town,
                        point=where,
                    )
                    upper = state == "MO"
                    for school, school_identity in (
                        (f"{town} High School", Identity("school", (town,), level="high")),
                        (
                            f"{person} Elementary School",
                            _person_identity(person, "elementary"),
                        ),
                    ):
                        self._add(
                            kind="school",
                            name=_upper_if(school, upper),
                            identity=school_identity,
                            style=ACROSS_STYLE,
                            state=state,
                            county=place,
                            district_id=district.id,
                            city=town,
                            point=(where[0] + rng.uniform(-0.01, 0.01), where[1]),
                        )

    def leading(self, state: str) -> None:
        """Private schools of ``state`` whose names begin with or hold a place word.

        :data:`_LEADING_PER_STATE` of :data:`LEADING_SCHOOLS`, each in a town of a
        county of the state: ``"Village Christian Academy"``, ``"Town & Country
        Day School"``, ``"City Academy"``, ``"Kid City Academy"``. The place word
        is part of the base a listing must say: see :func:`_leading_case`.
        """
        rng = self.leading_rng
        settled = [
            county for county, _root, _point in self.counties[state] if self.county_towns[county]
        ]
        for name, base, noun, faithful, _left_out in rng.sample(
            LEADING_SCHOOLS, k=_LEADING_PER_STATE
        ):
            county = rng.choice(settled)
            town, point = rng.choice(self.county_towns[county])
            faith = rng.choice(SYSTEM_FAITHS) if faithful else None
            word = rng.choice(LEADING_WORDS)
            upper = rng.random() < 0.5
            self._add(
                kind="school",
                name=_upper_if(name.format(f=faith, w=word), upper),
                identity=Identity(
                    "school",
                    tuple(part.format(w=word) for part in base),
                    noun=noun,
                    affiliation=faith,
                ),
                style=LEADING_STYLE,
                state=state,
                county=county,
                district_id=None,
                city=town,
                point=(point[0] + rng.uniform(-0.02, 0.02), point[1] + rng.uniform(-0.02, 0.02)),
            )

    def levels(self, state: str) -> None:
        """Schools of ``state`` whose names leave out the level their grades make them.

        :data:`_LEVEL_GROUPS_PER_STATE` groups of :data:`LEVEL_GROUPS`, each in one
        county of two districts or more, named for a surname (``{p}``) or a saint
        (``{s}``):

        * ``bare``: ``"{p} Elementary School"`` of one district and ``"{p}"`` of
          another, both K-5 (Massachusetts's ``"Lincoln"``);
        * ``school``: ``"{p} Elem"`` and ``"{p} School"``, both K-5 (Illinois's
          ``"Devonshire School"``);
        * ``parish``: private ``"ST {S} ELEMENTARY SCHOOL"`` and ``"ST {S}
          SCHOOL"``, both PK-8, in two towns;
        * ``control``: ``"{p} Elementary School"`` (K-5) and a 6-8 ``"{p} School"``;
        * ``combined``: ``"{p} Elementary School"`` (K-5) and a private K-12
          ``"{P} SCHOOL"``;
        * ``lone``: ``"{p}"`` (K-5), alone of its name;
        * ``preschool``: private ``"ST {S}'S LUTHERAN SCHOOL"`` (PK-1) and ``"ST
          {S} LUTHERAN SCHOOL"`` (PK-8), in two towns;
        * ``junior``: ``"{p} Junior High School"`` and a 5-8 ``"{p} School"``.

        See :func:`_level_case` for the listings that name them.
        """
        rng = self.level_rng
        counties = [
            county
            for county, _root, _point in self.counties[state]
            if len(self.county_districts[county]) > 1
        ]
        for kind in rng.sample(LEVEL_GROUPS, k=_LEVEL_GROUPS_PER_STATE):
            county = rng.choice(counties)
            first, second = rng.sample(self.county_districts[county], k=2)
            surname, saint = rng.choice(LEVEL_SURNAMES), rng.choice(SAINTS)
            members = self._level_group(kind, surname, saint)
            for position, (name, identity, district) in enumerate(members):
                owner = (first, second)[district] if district is not None else None
                # A private school lies in the town of the first district, or the second.
                where = owner if owner is not None else (first, second)[position % 2]
                point = where.record.point
                assert point is not None
                self._add(
                    kind="school",
                    name=name,
                    identity=identity,
                    style=LEVEL_STYLE,
                    state=state,
                    county=county,
                    district_id=owner.record.id if owner is not None else None,
                    city=where.record.city or "",
                    point=(
                        point[0] + rng.uniform(-0.03, 0.03),
                        point[1] + rng.uniform(-0.03, 0.03),
                    ),
                )

    def _level_group(  # noqa: PLR0911 - one return per kind of group
        self, kind: str, person: str, saint: str
    ) -> list[tuple[str, Identity, int | None]]:
        """The schools of one group of :meth:`levels`: name, identity, and which district runs it.

        The district is the first (``0``) or second (``1``) of the county's two, or
        none for a private school.
        """
        rng = self.level_rng
        elementary = rng.choice(("Elementary School", "Elementary", "Elem School", "Elem"))
        spelled = Identity("school", (person,), level="elementary")
        if kind == "bare":
            bare = Identity("school", (person,), grades="K-5")
            return [(f"{person} {elementary}", spelled, 0), (person, bare, 1)]
        if kind == "school":
            bare = Identity("school", (person,), grades="K-5")
            return [(f"{person} {elementary}", spelled, 0), (f"{person} School", bare, 1)]
        if kind == "parish":
            parish = Identity("school", (saint,), noun="School", saint=True, grades="PK-8")
            return [
                (
                    f"ST {saint.upper()} ELEMENTARY SCHOOL",
                    replace(parish, level="elementary"),
                    None,
                ),
                (f"ST {saint.upper()} SCHOOL", parish, None),
            ]
        if kind == "control":
            middle = Identity("school", (person,), grades="6-8")
            return [(f"{person} {elementary}", spelled, 0), (f"{person} School", middle, 1)]
        if kind == "combined":
            whole = Identity("school", (person,), grades="K-12")
            return [
                (f"{person} {elementary}", spelled, 0),
                (f"{person.upper()} SCHOOL", whole, None),
            ]
        if kind == "lone":
            return [(person, Identity("school", (person,), grades="K-5"), 0)]
        if kind == "preschool":
            lutheran = Identity(
                "school", (saint,), noun="School", affiliation="Lutheran", saint=True
            )
            plain = saint if saint.endswith("s") else f"{saint}'s"
            return [
                (f"ST {plain.upper()} LUTHERAN SCHOOL", replace(lutheran, grades="PK-1"), None),
                (f"ST {saint.upper()} LUTHERAN SCHOOL", replace(lutheran, grades="PK-8"), None),
            ]
        # "junior": a junior high school, and a 5-8 school whose name says no level.
        junior = Identity("school", (person,), level="juniorhigh")
        grades = Identity("school", (person,), grades="5-8")
        written = rng.choice(("Junior High School", "Jr High"))
        return [(f"{person} {written}", junior, 0), (f"{person} School", grades, 1)]

    def forenames(self, state: str) -> None:
        """Schools of ``state`` named for a person, some of one surname in one county.

        :data:`_FORENAME_GROUPS_PER_STATE` groups of :data:`FORENAME_GROUPS`, each a
        made-up surname (:data:`FORENAME_SURNAMES`, ``{S}``) and a level, in one
        county, written as NCES writes such names:

        * ``pair``: ``"R. D. {S} Elementary"`` and ``"Clara J. {S} Elementary"``;
        * ``pair_given``: ``"R. D. {S} Elementary"`` and ``"Clara {S} Elementary"``;
        * ``lone_initials``, ``lone_initial``, ``lone_given``: one of those alone;
        * ``exact``: ``"{S} Elementary"`` and ``"Clara J. {S} Elementary"``;
        * ``two_initials``: ``"R. D. {S} Elementary"`` and ``"A. B. {S} Elementary"``;
        * ``bracket``, ``bracket_lone``: California's and Delaware's ``"{S} (Clara J.)
          Elementary"`` or ``"{S} (Clara) Elementary"``, beside ``"R. D. {S}
          Elementary"`` or alone;
        * ``roman``: ``"J. I. {S} Elementary"``, initials whose second letter a
          district's number would be (``"R-V"``), alone.

        Initials are written ``"R. D."``, ``"R.D."`` or ``"R D"``. See
        :func:`_forename_case` for the listings that name them.
        """
        rng = self.forename_rng
        counties = [
            county
            for county, _root, _point in self.counties[state]
            if self.county_districts[county]
        ]
        style = _state_style(state)
        for kind, surname in zip(
            rng.sample(FORENAME_GROUPS, k=_FORENAME_GROUPS_PER_STATE),
            rng.sample(FORENAME_SURNAMES, k=_FORENAME_GROUPS_PER_STATE),
            strict=True,
        ):
            county = rng.choice(counties)
            district = rng.choice(self.county_districts[county])
            level = rng.choice(("elementary", "elementary", "middle", "high"))
            for name, identity in self._forename_group(kind, state, style, surname, level):
                point = district.record.point
                assert point is not None
                self._add(
                    kind="school",
                    name=name.upper() if style == "tx" else name,
                    identity=identity,
                    style=FORENAME_STYLE,
                    state=state,
                    county=county,
                    district_id=district.record.id,
                    city=district.record.city or "",
                    point=(
                        point[0] + rng.uniform(-0.03, 0.03),
                        point[1] + rng.uniform(-0.03, 0.03),
                    ),
                )

    def _forename_group(  # noqa: PLR0911 - one return per kind of group
        self, kind: str, state: str, style: str, surname: str, level: str
    ) -> list[tuple[str, Identity]]:
        """The schools of one group of :meth:`forenames`: their names and identities."""
        rng = self.forename_rng
        spelling = rng.choice(LEVEL_NCES.get(style, LEVEL_NCES["plain"])[level])
        given = rng.choice(GIVEN_NAMES)
        middle = rng.choice("ABCDEFGHJKLMNPRSTW")

        def named(parts: tuple[str, ...], *, bracketed: bool = False) -> tuple[str, Identity]:
            written = " ".join(parts)
            if all(len(part.rstrip(".")) == 1 for part in parts):
                written = rng.choice((written, written.replace(" ", ""), written.replace(".", "")))
            name = (
                f"{surname} ({written}) {spelling}"
                if bracketed
                else f"{written} {surname} {spelling}"
            )
            base = (" ".join((*(part.rstrip(".") for part in parts), surname)),)
            return name, Identity(
                "school", base, level=level, surname=surname, given=parts, bracketed=bracketed
            )

        initials = tuple(rng.choice(FORENAME_INITIALS).split())
        others = tuple(rng.choice([i for i in FORENAME_INITIALS if i[0] != initials[0][0]]).split())
        if kind == "pair":
            return [named(initials), named((given, f"{middle}."))]
        if kind == "pair_given":
            return [named(initials), named((given,))]
        if kind == "lone_initials":
            return [named(initials)]
        if kind == "lone_initial":
            return [named((given, f"{middle}."))]
        if kind == "lone_given":
            return [named((given,))]
        if kind == "exact":
            plain = Identity("school", (surname,), level=level)
            return [(f"{surname} {spelling}", plain), named((given, f"{middle}."))]
        if kind == "two_initials":
            return [named(initials), named(others)]
        bracketed = state in BRACKET_FORENAME_STATES
        forenames = (given, f"{middle}.") if rng.random() < 0.5 else (given,)
        if kind == "bracket":
            return [named(forenames, bracketed=bracketed), named(initials)]
        if kind == "bracket_lone":
            return [named(forenames, bracketed=bracketed)]
        # "roman": dotted initials whose second letter is a Roman numeral.
        roman = tuple(rng.choice(ROMAN_INITIALS).split())
        written = rng.choice((" ".join(roman), "".join(roman)))
        name = f"{written} {surname} {spelling}"
        base = (" ".join((*(part.rstrip(".") for part in roman), surname)),)
        return [(name, Identity("school", base, level=level, surname=surname, given=roman))]

    def plurals(self, state: str) -> None:
        """Schools of ``state`` named for a word with a plural's ``s`` or without it.

        :data:`_PLURAL_GROUPS_PER_STATE` groups of :data:`PLURAL_GROUPS` in one
        county each: ``plural`` is ``"{W}s Elementary"`` (or ``"The {W}s School"``)
        alone, ``singular`` ``"{W} Elementary"`` alone, and ``both`` the two side
        by side (:data:`PLURAL_WORDS`, ``{W}``). ``"Park Elementary"`` is not
        ``"Parks Elementary"``. See :func:`_plural_case`.
        """
        rng = self.plural_rng
        counties = [
            county
            for county, _root, _point in self.counties[state]
            if self.county_districts[county]
        ]
        style = _state_style(state)
        for kind, word in zip(
            rng.sample(PLURAL_GROUPS, k=_PLURAL_GROUPS_PER_STATE),
            rng.sample(PLURAL_WORDS, k=_PLURAL_GROUPS_PER_STATE),
            strict=True,
        ):
            county = rng.choice(counties)
            district = rng.choice(self.county_districts[county])
            level = rng.choice(("elementary", "elementary", "middle"))
            spelling = rng.choice(LEVEL_NCES.get(style, LEVEL_NCES["plain"])[level])
            members: list[tuple[str, Identity]] = []
            if kind in {"plural", "both"}:
                if rng.random() < 0.3:
                    school = Identity("school", (f"{word}s",), grades="K-5")
                    members.append((f"The {word}s School", school))
                else:
                    members.append(
                        (f"{word}s {spelling}", Identity("school", (f"{word}s",), level=level))
                    )
            if kind in {"singular", "both"}:
                members.append((f"{word} {spelling}", Identity("school", (word,), level=level)))
            for name, identity in members:
                point = district.record.point
                assert point is not None
                self._add(
                    kind="school",
                    name=name.upper() if style == "tx" else name,
                    identity=identity,
                    style=PLURAL_STYLE,
                    state=state,
                    county=county,
                    district_id=district.record.id,
                    city=district.record.city or "",
                    point=(
                        point[0] + rng.uniform(-0.03, 0.03),
                        point[1] + rng.uniform(-0.03, 0.03),
                    ),
                )

    def townships(self) -> None:
        """Two townships of one name in two counties of one state, each running a district.

        For each of :data:`TOWNSHIP_STATES`, a few towns the state has not: in a
        county of the state, a township's district written one way of
        :data:`TOWNSHIP_NAMES`; in a county of its own :data:`_TOWNSHIP_APART_KM`
        from it, the other township's district written another way (as New
        Jersey's ``"Township of Union School District"`` and ``"Union Township
        School District"``, or ``"Hamilton Township School District"`` and
        ``"Hamilton Township Public School District"``). Each runs two schools
        named for people. Nothing but a point much nearer one of them tells
        them apart: see :func:`_township_case`.
        """
        rng = self.township_rng
        for state in TOWNSHIP_STATES:
            used = {item.record.city for item in self.records if item.record.state == state}
            fresh = [p + x for p in TOWN_PREFIXES for x in TOWN_SUFFIXES if p + x not in used]
            index = STATES.index(state)
            taken = {county for county, _root, _point in self.counties[state]}
            spare = [
                code
                for code in (f"9{index:02d}{k:02d}" for k in range(99, -1, -1))
                if code not in taken
            ]
            settled = [c for c in self.counties[state] if self.county_towns[c[0]]]
            towns = rng.sample(fresh, k=_TOWNSHIP_TOWNS)
            for town, codes in zip(
                towns, zip(spare[0::2], spare[1::2], strict=False), strict=False
            ):
                _county, _root, home = rng.choice(settled)
                away = rng.uniform(*_TOWNSHIP_APART_KM)
                heading = rng.uniform(0.0, 2 * math.pi)
                office = (home[0] + rng.uniform(-0.05, 0.05), home[1] + rng.uniform(-0.05, 0.05))
                there = (
                    office[0] + away * math.sin(heading) / 111.2,
                    office[1]
                    + away * math.cos(heading) / (111.2 * math.cos(math.radians(office[0]))),
                )
                pair = rng.choice(TOWNSHIP_PAIRS)
                if rng.random() < 0.5:
                    pair = (pair[1], pair[0])
                for code, where, wording in zip(codes, (office, there), pair, strict=True):
                    self.county_roots[code] = rng.choice(COUNTY_ROOTS)
                    self.counties[state].append((code, self.county_roots[code], where))
                    written, qualifier = TOWNSHIP_NAMES[wording]
                    district = self._add(
                        kind="district",
                        name=written.format(town=town),
                        identity=Identity("district", (town,), qualifier=qualifier),
                        style=TOWNSHIP_STYLE,
                        state=state,
                        county=code,
                        district_id=None,
                        city=town,
                        point=where,
                    )
                    for level, noun in (
                        ("elementary", "Elementary School"),
                        ("middle", "Middle School"),
                    ):
                        person = f"{rng.choice(GIVEN_NAMES)} {rng.choice(ALL_SURNAMES)}"
                        self._add(
                            kind="school",
                            name=f"{person} {noun}",
                            identity=_person_identity(person, level),
                            style=TOWNSHIP_STYLE,
                            state=state,
                            county=code,
                            district_id=district.id,
                            city=town,
                            point=(where[0] + rng.uniform(-0.01, 0.01), where[1]),
                        )

    def systems(self, state: str) -> None:
        """School systems NCES splits into districts, as :data:`SYSTEM_KINDS` lists them.

        Each in a town the state has no other record in, so that only the
        system's own listings name it, in one of the state's settled counties.
        """
        kinds = SYSTEM_KINDS.get(state)
        if kinds is None or state not in self.counties:
            return
        rng = self.system_rng
        used = {item.record.city for item in self.records if item.record.state == state}
        fresh = [p + x for p in TOWN_PREFIXES for x in TOWN_SUFFIXES if p + x not in used]
        settled = [c for c in self.counties[state] if self.county_towns[c[0]]]
        for kind in kinds:
            town = fresh.pop(rng.randrange(len(fresh)))
            other = fresh.pop(rng.randrange(len(fresh)))
            county, root, home = rng.choice(settled)
            if kind == "ny_city":
                second = rng.choice([c for c in settled if c[0] != county] or settled)
                self._city_system(state, town, (county, home), (second[0], second[2]))
            else:
                self._town_system(state, kind, town, other, (county, root, home))

    def _system_district(  # noqa: PLR0913, PLR0917 - one argument per NCES column
        self,
        state: str,
        name: str,
        identity: Identity,
        county: str,
        city: str,
        office: tuple[float, float],
        schools: Sequence[tuple[str, Identity]],
    ) -> DirectoryRecord:
        """One district of a system, at ``office``, with its ``schools`` (names and identities)."""
        district = self._add(
            kind="district",
            name=name,
            identity=identity,
            style=SYSTEM_STYLE,
            state=state,
            county=county,
            district_id=None,
            city=city,
            point=office,
        )
        rng = self.system_rng
        for school, school_identity in schools:
            self._add(
                kind="school",
                name=school,
                identity=school_identity,
                style=SYSTEM_STYLE,
                state=state,
                county=county,
                district_id=district.id,
                city=city,
                point=(office[0] + rng.uniform(-0.03, 0.03), office[1] + rng.uniform(-0.03, 0.03)),
            )
        return district

    def _person_school(self, level: str) -> tuple[str, Identity]:
        rng = self.system_rng
        person = f"{rng.choice(GIVEN_NAMES)} {rng.choice(ALL_SURNAMES)}"
        return f"{person} School", _person_identity(person, level)

    def _town_system(
        self,
        state: str,
        kind: str,
        town: str,
        other: str,
        where: tuple[str, str, tuple[float, float]],
    ) -> None:
        """A town's elementary and high school districts: see :data:`SYSTEM_KINDS`."""
        rng = self.system_rng
        county, root, home = where
        office = self._near(home, 0.15)
        apart = (office[0] + 0.04, office[1] - 0.05)
        city = f"{town} City" if kind == "mt_office_city" else town
        tag = f"{SYSTEM_FORM}:{kind}:{city}"
        elementary = Identity("district", (town,), level="elementary", form=tag)
        high = Identity("district", (town,), level="high", form=tag)
        middle = (f"{city} Middle School", Identity("school", (city,), level="middle"))
        high_school = (f"{town} High School", Identity("school", (town,), level="high"))
        if kind == "mt_levels":
            names = (f"{town} Elem", f"{town} H S")
        elif kind == "mt_office":
            names = (f"{town} Elem", f"{other} H S")
            high = replace(high, base=(other,))
            high_school = (f"{other} High School", Identity("school", (other,), level="high"))
        elif kind == "mt_office_city":
            names = (f"{town} City Elem", f"{root} County H S")
            high = replace(high, base=(root,), qualifier="County")
            high_school = (f"{root} County High School", Identity("school", (root,), level="high"))
        elif kind == "mt_apart":
            names = (f"{town} Elem", f"{other} H S")
            high = replace(high, base=(other,))
            high_school = (f"{other} High School", Identity("school", (other,), level="high"))
        elif kind == "ca_union":
            names = (f"{town} Union Elementary", f"{town} Union High")
        elif kind == "ca_office_city":
            names = (f"{town} City Elementary", f"{town} Joint Union High")
        elif kind == "az_levels":
            first, second = rng.sample(range(4000, 9999), k=2)
            names = (
                f"{town} Elementary District ({first})",
                f"{town} Union High School District ({second})",
            )
        else:  # il_levels
            first, second = rng.sample(range(1, 399), k=2)
            names = (f"{town} ESD {first}", f"{town} Twp HSD {second}")
            elementary = replace(elementary, numbers=(str(first),))
            high = replace(high, numbers=(str(second),))
        separate = kind in {"mt_apart", "ca_union", "az_levels", "il_levels"}
        self._system_district(
            state,
            names[0],
            elementary,
            county,
            city,
            office,
            (middle, self._person_school("elementary")),
        )
        self._system_district(
            state, names[1], high, county, city, apart if separate else office, (high_school,)
        )

    def _city_system(
        self,
        state: str,
        town: str,
        first: tuple[str, tuple[float, float]],
        second: tuple[str, tuple[float, float]],
    ) -> None:
        """A city's geographic districts, district 75 and a charter: see :data:`SYSTEM_KINDS`."""
        rng = self.system_rng
        tag = f"{SYSTEM_FORM}:ny_city:{town} City"
        upper = town.upper()
        for number in range(1, 5):
            county, home = first if number <= 2 else second
            self._system_district(
                state,
                f"{upper} CITY GEOGRAPHIC DISTRICT #{number:2d}",
                Identity("district", (town,), qualifier="City", numbers=(str(number),), form=tag),
                county,
                town,
                self._near(home, 0.1),
                [self._person_school(rng.choice(("elementary", "middle"))) for _ in range(2)],
            )
        county, home = first
        self._system_district(
            state,
            f"{upper} CITY SPECIAL SCHOOLS - DISTRICT 75",
            Identity("district", (town, "Special"), qualifier="City", numbers=("75",), form=tag),
            county,
            town,
            self._near(home, 0.1),
            [self._person_school("elementary") for _ in range(3)],
        )
        name = f"{upper} CITY CHARTER SCHOOL OF THE ARTS"
        charter = Identity(
            "district",
            (town, "Arts"),
            qualifier="City",
            noun="Charter",
            form=f"{SYSTEM_FORM}:{CITY_CHARTER}:{town} City",
        )
        self._system_district(
            state,
            name,
            charter,
            county,
            town,
            self._near(home, 0.1),
            ((name, replace(charter, kind="school")),),
        )

    def _rename(self, position: int, name: str, identity: Identity | None = None) -> None:
        item = self.records[position]
        self.records[position] = replace(
            item,
            record=replace(item.record, name=name),
            identity=identity if identity is not None else item.identity,
        )

    def brackets(self, state: str) -> None:
        """End names with the brackets NCES ends some with, in the states that do.

        Every district of :data:`ENTITY_NUMBER_STATES` takes an entity number
        (``"Ashfield School District (4231)"``); two districts of one name in
        :data:`COUNTY_BRACKET_STATES` take their counties' names (``"Ashfield
        Public Schools (Abernathy)"``, the namesakes of :meth:`namesakes`); and
        some town districts of :data:`SECOND_NAME_STATES` a second name
        (``"ASHFIELD CENTRAL SCHOOL DISTRICT (LAKE VESPER)"``), with a high
        school named for it. None of it changes who a record is.
        """
        rng = self.bracket_rng
        positions = [
            i
            for i, item in enumerate(self.records)
            if item.record.state == state and item.record.kind == "district"
        ]
        if state in ENTITY_NUMBER_STATES:
            numbers = rng.sample(range(4000, 99999), k=len(positions))
            for position, number in zip(positions, numbers, strict=True):
                self._rename(position, f"{self.records[position].record.name} ({number})")
        if state in COUNTY_BRACKET_STATES:
            by_name: dict[str, list[int]] = defaultdict(list)
            for position in positions:
                by_name[self.records[position].record.name.casefold()].append(position)
            for group in by_name.values():
                for position in group if len(group) > 1 else ():
                    record = self.records[position].record
                    root = self.county_roots[record.county_fips or ""]
                    self._rename(position, f"{record.name} ({root})")
        if state in SECOND_NAME_STATES:
            eligible = [
                position
                for position in positions
                if self.records[position].style != NAMESAKE_STYLE
                and len(self.records[position].identity.base) == 1
            ]
            chosen = rng.sample(eligible, k=min(_SECOND_NAMES_PER_STATE, len(eligible)))
            aliases = rng.sample(SECOND_NAMES, k=len(chosen))
            for position, alias in zip(chosen, aliases, strict=True):
                self._second_name(position, alias)

    def _second_name(self, position: int, alias: str) -> None:
        item = self.records[position]
        record = item.record
        point = record.point
        assert record.county_fips is not None
        assert record.city is not None
        assert point is not None
        self._rename(
            position,
            f"{record.name} ({alias.upper()})",
            replace(item.identity, aliases=(alias,)),
        )
        self._add(
            kind="school",
            name=f"{alias.upper()} HIGH SCHOOL",
            identity=Identity("school", (alias,), level="high"),
            style=BRACKET_STYLE,
            state=record.state,
            county=record.county_fips,
            district_id=record.id,
            city=record.city,
            point=point,
        )


_ACROSS_WORDING: dict[str, tuple[str, str | None, str | None]] = {
    "VA": ("{} City Public Schools", "City", None),
    "KY": ("{} Independent", None, "Independent"),
    "OH": ("{} Exempted Village", "Village", "Exempted Village"),
    "IN": ("{} Community Schools", None, "Community"),
    # Kansas and Tennessee: the town alone.
    "KS": ("{}", None, None),
    "TN": ("{}", None, None),
}
"""How each of :data:`ACROSS_PAIRS`' states that does not number its districts
writes a town's district: the name, its municipal qualifier and its legal form."""


def _across_name(rng: random.Random, state: str, town: str) -> tuple[str, Identity]:
    """A town's district as ``state`` (one of :data:`ACROSS_PAIRS`') writes its NCES name."""
    if state == "MO":
        number = rng.randint(1, 12)
        return f"{town.upper()} R-{_ROMAN[number]}", Identity(
            "district", (town,), numbers=(str(number),)
        )
    if state == "IL":
        number = rng.randint(1, 399)
        return f"{town} CUSD {number}", Identity(
            "district", (town,), numbers=(str(number),), legal="CUSD"
        )
    wording, qualifier, legal = _ACROSS_WORDING[state]
    return wording.format(town), Identity("district", (town,), qualifier=qualifier, legal=legal)


def build_directory(
    *, districts_per_state: int, private_per_state: int, seed: int
) -> list[SyntheticRecord]:
    """Generate a synthetic directory: every state gets the same number of districts.

    The charter networks (:meth:`_Generator.networks`), the charter districts
    named as one academy (:meth:`_Generator.academies`), the districts named
    for a town elsewhere (:meth:`_Generator.namesakes`), the brackets names
    end with (:meth:`_Generator.brackets`) and the namesakes on either side
    of a market's counties (:meth:`_Generator.borders`) and the school systems
    NCES splits into districts (:meth:`_Generator.systems`) and the twin towns
    across a state line (:meth:`_Generator.across`) and the townships of one
    name in two counties (:meth:`_Generator.townships`) and the private schools
    whose names begin with or hold a place word (:meth:`_Generator.leading`) and
    the schools whose names leave out their level (:meth:`_Generator.levels`) and
    the schools named for a person (:meth:`_Generator.forenames`) or for a word with
    a plural's ``s`` or without it (:meth:`_Generator.plurals`) come last, so the
    rest of the directory is the same with them or without.
    """
    generator = _Generator(seed)
    for index, state in enumerate(STATES):
        generator.state(index, state, districts_per_state, private_per_state)
    for state in STATES:
        generator.networks(state)
    for state in STATES:
        generator.academies(state)
    for state in STATES:
        generator.namesakes(state)
    for state in STATES:
        generator.brackets(state)
    generator.borders()
    for state in STATES:
        generator.systems(state)
    generator.across()
    generator.townships()
    for state in STATES:
        generator.leading(state)
    for state in STATES:
        generator.levels(state)
    for state in STATES:
        generator.forenames(state)
    for state in STATES:
        generator.plurals(state)
    return generator.records


# -- the oracle -----------------------------------------------------------------

_TOWN_QUALIFIERS = frozenset({"City", "Town", "Village", "Borough", "Local", "Area", "Regional"})
MUNICIPAL_QUALIFIERS = frozenset({"City", "Town", "Village", "Borough", "Township"})
"""Qualifiers that say what kind of municipality a district's town is, which NCES and
the lists each say or leave out (``"Murfreesboro"`` and ``"Murfreesboro City
Schools"``, ``"Bensalem Township SD"`` and ``"Bensalem School District"``): see
:func:`needs_forgiving`."""


def _norm(words: Iterable[str]) -> str:
    """Compare base names as the matcher does: "Pine View" and "Pineview" are one name.

    Initials count for nothing ("Amelia R. Carrow" is "Amelia Carrow").
    """
    kept = [w for w in " ".join(words).replace(".", " ").split() if len(w) > 1]
    return "".join(kept).casefold()


def _noun(noun: str | None) -> str | None:
    """A school's noun as the matcher reads it: "Schools" is "School"."""
    return "School" if noun == "Schools" else noun


def _levels(record: Identity, *, maybe: bool) -> frozenset[str]:
    """The levels a listing names ``record`` by, when its name says none (:data:`TAUGHT`).

    ``maybe``: also those a listing may mean it by, though not surely.
    """
    if record.level is not None or record.grades is None:
        return frozenset()
    fits, may = TAUGHT[record.grades]
    return fits | may if maybe else fits


def compatible(  # noqa: PLR0911, PLR0912 - one rule each
    listing: Identity, record: Identity, *, maybe: bool = False
) -> bool:
    """Whether a listing that says ``listing`` could mean a record that is ``record``.

    A listing may leave out a level, a number or a town qualifier (``City``)
    and still mean the record; it may not leave out a county, and whatever it
    does say must agree, but for a level a school's name leaves out, which its
    grades say (:data:`TAUGHT`: ``"Dunbar Elementary"`` for the K-5 ``"Dunbar
    School"``, not the 6-8 one), and for a municipal word only one side says
    (:func:`needs_forgiving`), which fits when nothing else in scope bears the
    rest of the name. An affiliation the listing names must be
    the record's own: ``"Ashfield Catholic Schools"`` means no public district
    and no school that does not say Catholic, but for a saint's private school
    that names no faith, which is a Catholic parish's (``"St. Mary's Catholic
    School"`` for ``"St. Mary's School"``). It may leave out the affiliation of a
    saint's school only (``"St. Mary's School"`` for ``"St. Mary's Catholic
    School"``): ``"Lincoln Academy"`` is not ``"Lincoln Christian Academy"``. A
    direction is part of the base (``"East Ashfield"`` is not ``"Ashfield"``). A
    district may be named by a second name (:attr:`Identity.aliases`) as by its
    own. A listing for a college or a civic body (kinds ``"college"`` and ``"civic"``:
    ``"City of Ashfield"``, ``"Ashfield Senior Center"``) means no K-12 record
    at all; its kind never equals a record's; nor does a district's program
    (kind ``"program"``: ``"RSU 13 - Adult Education"``). A district named only
    by its codes (``"RSU 13"``) is meant by a listing that gives one of them,
    with its town or without; whether a code fits is :meth:`Oracle.codes_fit`'s
    to say. A listing that is only a town's name (kind ``"place"``) means the
    district named for the town (:func:`_names_the_town`), never a school. A
    private school named for its town (``"Village School of Ashfield"``) is
    meant by its name alone. ``maybe``: whether the listing may mean the record,
    though not surely: a K-12 ``"Dunbar School"`` for ``"Dunbar Elementary"``.
    """
    if listing.kind == "place":
        return _names_the_town(listing, record)
    if listing.kind != record.kind or listing.form != record.form:
        return False
    if record.coded:
        # Named only by its codes: a listing gives one, and may add the town.
        if not listing.codes or (listing.base and _norm(listing.base) != _norm(record.base)):
            return False
    elif (listing.surname is None or record.surname is None) and _norm(listing.base) in _bases(
        record
    ):
        # The same name, one side not telling its person's forenames from the surname.
        pass
    elif plural_twins(listing, record):
        # Another word, which a list may misspell: a school the listing may mean.
        if not maybe:
            return False
    elif listing.surname is not None or record.surname is not None:
        fit = person_fit(listing, record)
        if fit is None or (fit == MAYBE and not maybe):
            return False
    else:
        return False
    if listing.saint != record.saint or _noun(listing.noun) != _noun(record.noun):
        return False
    if (
        listing.level is not None
        and listing.level != record.level
        and listing.level not in _levels(record, maybe=maybe)
    ):
        return False
    if listing.numbers != record.numbers and listing.numbers:
        return False
    if listing.affiliation != record.affiliation and not (
        record.saint
        and (listing.affiliation is None or (listing.affiliation, record.affiliation) == _PARISH)
    ):
        return False
    if listing.qualifier != record.qualifier:
        return (
            listing.qualifier is None and record.qualifier in _TOWN_QUALIFIERS
        ) or needs_forgiving(listing, record)
    return True


SURE, LEFT, MAYBE = "sure", "left", "maybe"


def _twin_key(base: tuple[str, ...]) -> str:
    """A base's words as :func:`_stems` reads them, in order: ``"parksheights"`` for both
    ``"Parks Heights"`` and ``"Park Heights"``."""
    words = " ".join(base).replace(".", " ").replace("-", " ").split()
    return "".join(
        word[:-1]
        if len(word) >= _STEM_LENGTH and word.endswith("s") and not word.endswith("ss")
        else word
        for word in (word.casefold() for word in words)
    )


def plural_twins(listing: Identity, record: Identity) -> bool:
    """Whether two schools' bases differ only by a word's plural ``s`` (``"Parks"``, ``"Park"``).

    Two names, but a list may misspell either, so a listing of one may mean the
    other school, though not surely: :func:`compatible` with ``maybe``. Not a saint's
    name, and not districts, which the matcher tells apart by spelling.
    """
    return (
        listing.kind == "school"
        and record.kind == "school"
        and not listing.saint
        and not record.saint
        and _norm(listing.base) != _norm(record.base)
        and _stems(listing.base) == _stems(record.base)
        and len(listing.base[0].split()) == len(record.base[0].split())
    )


def _person_of(identity: Identity) -> tuple[tuple[str, ...], str]:
    """``identity``'s forenames and surname, as folded words: a name of no person's is all
    surname (``((), "keller")`` for ``"Keller Elementary"``)."""
    if identity.surname is None:
        return (), _norm(identity.base)
    return tuple(part.rstrip(".").casefold() for part in identity.given), _norm((identity.surname,))


def person_fit(  # noqa: PLR0911 - one return per way of naming
    listing: Identity, record: Identity
) -> str | None:
    """Whether a listing names the person a school is named for, and how.

    The surnames agree, and the forenames agree slot by slot: each the same, or
    one the other's initial; the listing may leave out the later ones, or all of
    them, and add initials of its own; a middle initial after a forename both
    spell alike is no matter (``"Amelia T. Carrow"`` for ``"Amelia R. Carrow"``).
    A school whose name gives no forenames is named by a listing that gives only
    initials too (``"W.W. Walker"`` for ``"Walker School"``). Returns :data:`SURE`
    when the listing names the person as the record does, or another way;
    :data:`LEFT` when it leaves the forenames out (or the record leaves out its
    initials), which a school whose name is the listing's word for word comes
    before; :data:`MAYBE` for a record whose forenames are only given names
    (``"Clara Whitcombe"``) that the listing leaves out or gives as initials: a
    given name alone may be a place's word, so such a school may be meant, though
    not surely, and not before a school whose name is the listing's word for word
    (:meth:`Oracle.expected`). Forenames that end with an initial or that NCES
    bracketed are surely a person's.
    """
    mine, surname = _person_of(listing)
    theirs, their_surname = _person_of(record)
    if surname != their_surname:
        return None
    if not theirs:
        if not mine:
            return SURE
        if not all(len(part) == 1 for part in mine):
            return None
        return LEFT if listing.level is not None else MAYBE
    sure = record.bracketed or len(theirs[-1]) == 1
    if not mine:
        # Left out: surely the person's school only where the listing says its level.
        return LEFT if sure and listing.level is not None else MAYBE
    spelled = len(mine[0]) > 1 and mine[0] == theirs[0]
    paired = False
    for i in range(max(len(mine), len(theirs))):
        said = mine[i] if i < len(mine) else None
        own = theirs[i] if i < len(theirs) else None
        if own is None:
            if said is not None and len(said) > 1:
                return None
        elif said is None or said == own:
            continue
        elif said[0] == own[0] and (len(said) == 1 or len(own) == 1):
            paired = True
        elif not (spelled and len(said) == 1 and len(own) == 1):
            return None
    return SURE if sure or not paired else MAYBE


def needs_forgiving(listing: Identity, record: Identity) -> bool:
    """Whether a district listing fits a district only with a municipal word set aside.

    One of them says a municipal qualifier (:data:`MUNICIPAL_QUALIFIERS`) and the
    other none: ``"Ashfield City Schools"`` for ``"Ashfield School District"``
    or ``"Ashfield Local"``, ``"Ashfield School District"`` for ``"Ashfield
    Township School District"``. That fits only when no other district in scope
    bears the rest of the record's name (:meth:`Oracle.shared`), as ``"East
    Ashfield SD"`` or ``"Ashfield Valley SD"`` do. A ``City`` the listing leaves
    out fits anyway (a town qualifier), and a ``County`` never.
    """
    if listing.kind != "district" or record.kind != "district":
        return False
    said, theirs = listing.qualifier, record.qualifier
    if said is None:
        return theirs == "Township"
    return said in MUNICIPAL_QUALIFIERS and (
        theirs is None or theirs in _TOWN_QUALIFIERS - MUNICIPAL_QUALIFIERS
    )


_DIRECTION_STEMS = frozenset(direction.casefold() for direction in DIRECTIONS)


def _bears(other: Identity, words: frozenset[str], name: str) -> bool:
    """Whether ``other``'s base holds ``words`` (or is ``name`` run together), no new direction."""
    theirs = _stems(other.base)
    return (words <= theirs or _norm(other.base) == name) and (
        theirs & _DIRECTION_STEMS == words & _DIRECTION_STEMS
    )


_STEM_LENGTH = 4
"""The shortest word whose trailing ``s`` the matcher drops."""


def _stems(words: Iterable[str]) -> frozenset[str]:
    """A base's words as the matcher compares them: case folded, a plural's ``s`` dropped."""
    stems = set()
    for word in " ".join(words).replace(".", " ").replace("-", " ").split():
        folded = word.casefold()
        if len(folded) >= 4 and folded.endswith("s") and not folded.endswith("ss"):
            folded = folded[:-1]
        stems.add(folded)
    return frozenset(stems)


_PARISH = ("Catholic", None)
"""A listing that says Catholic, and a saint's school whose name says no faith: a
parish's school, which the generator makes private."""


def _bases(record: Identity) -> set[str]:
    """The bases a listing may give for ``record``: its own, and its second names'."""
    return {_norm(record.base), *(_norm((alias,)) for alias in record.aliases)}


def _names_the_town(listing: Identity, record: Identity) -> bool:
    """Whether a town's name alone (``"Ashfield"``) means ``record``.

    Only a district named for the town does, whatever level or number its name
    adds (``"Ashfield Elementary"``, ``"ASHFIELD R-IV"``) and whatever town
    qualifier (``"Ashfield City"``, ``"Ashfield Area SD"``); not one named for
    more (``"Ashfield Valley Unified"``), for its county or township, or by its
    codes alone (``"RSU 13"``).
    """
    return (
        record.kind == "district"
        and not record.coded
        and _norm(listing.base) == _norm(record.base)
        and record.affiliation is None
        and (record.qualifier is None or record.qualifier in _TOWN_QUALIFIERS)
    )


_SERIES = {"RSU": "rsu", "MSAD": "sad", "SAD": "sad", "AOS": "aos", "USD": "usd"}


def code_keys(codes: Iterable[str]) -> set[str]:
    """Codes as series and number, with ``MSAD`` and ``SAD`` one series: ``{"sad 17"}``."""
    keys = set()
    for code in codes:
        series, number = code.split()
        keys.add(f"{_SERIES[series]} {int(number)}")
    return keys


class Oracle:
    """Answers which record a listing should match, from identities alone."""

    def __init__(self, records: Sequence[SyntheticRecord]) -> None:
        self.records = records
        self.by_base: dict[str, list[SyntheticRecord]] = defaultdict(list)
        self.district_counties: dict[str, set[str]] = defaultdict(set)
        self.districts: dict[str, SyntheticRecord] = {}
        self.coded: list[SyntheticRecord] = []
        self.named_series: dict[str, set[str]] = defaultdict(set)
        self.by_id = {item.record.id: item for item in records}
        self.grid = CountyGrid([item.record for item in records])
        self.district_words: dict[str, list[SyntheticRecord]] = defaultdict(list)
        self.by_surname: dict[str, list[SyntheticRecord]] = defaultdict(list)
        self.by_twin: dict[str, list[SyntheticRecord]] = defaultdict(list)
        for item in records:
            for base in _bases(item.identity):
                self.by_base[base].append(item)
            if item.record.kind == "school":
                self.by_twin[_twin_key(item.identity.base)].append(item)
            if item.identity.surname is not None:
                self.by_surname[_norm((item.identity.surname,))].append(item)
            if item.record.kind == "district" and not item.identity.coded:
                for word in _stems(item.identity.base):
                    self.district_words[word].append(item)
            record = item.record
            owner = record.id if record.kind == "district" else record.district_id
            if owner is not None and record.county_fips is not None:
                self.district_counties[owner].add(record.county_fips)
            if record.kind == "district":
                self.districts[record.id] = item
                if item.identity.coded:
                    self.coded.append(item)
                if item.identity.codes and not item.identity.hidden:
                    series = {key.split()[0] for key in code_keys(item.identity.codes)}
                    self.named_series[record.state] |= series

    def shared(
        self, item: SyntheticRecord, states: Sequence[str], counties: Sequence[str] | None
    ) -> bool:
        """Whether another district in scope bears the rest of ``item``'s name.

        Its base holds all of ``item``'s base words (``"East Ashfield"``,
        ``"Ashfield Valley"``, the plural ``"Ashfields"`` for ``"Ashfield"``), or
        is the same name run together: then a municipal word said on one side
        only is what tells them apart (:func:`needs_forgiving`). Not one named
        for a direction the record's name does not say: a listing for
        ``"Ashfield"`` rules out ``"East Ashfield"``. Only a district of
        ``item``'s own state: across a state line such a word is how each state
        writes its names, and tells nothing apart (:meth:`namesakes_across`).
        """
        words = _stems(item.identity.base)
        return any(
            other is not item
            and other.record.state == item.record.state
            and self.in_scope(other.record, states, counties)
            and _bears(other.identity, words, _norm(item.identity.base))
            for other in self.district_words.get(min(words), ())
        )

    def codes_fit(self, listing: Identity, item: SyntheticRecord) -> bool:
        """Whether the codes a listing gives fit a record: its own or its district's.

        A district whose name shows its codes must have one of the listing's; one
        whose name does not (Kansas's) cannot be checked. A record whose district
        shows no code fits unless the state names districts by codes of the
        listing's series: then it is in none of them (``"RSU 13 Lincoln
        School"`` for a town district's school). A series no district's name
        shows (``"AOS 98"``) cannot be checked.
        """
        if not listing.codes:
            return True
        record = item.record
        owner = item if record.kind == "district" else self.districts.get(record.district_id or "")
        wanted = code_keys(listing.codes)
        if owner is not None and owner.identity.codes and not owner.identity.hidden:
            return bool(wanted & code_keys(owner.identity.codes))
        series = {key.split()[0] for key in wanted}
        return not series & self.named_series[record.state]

    def in_scope(
        self, record: DirectoryRecord, states: Sequence[str], counties: Sequence[str] | None
    ) -> bool:
        if record.state not in states:
            return False
        if counties is None:
            return True
        if record.kind == "district":
            return bool(self.district_counties[record.id] & set(counties))
        return record.county_fips in counties

    def reach(self, states: Sequence[str], counties: Sequence[str] | None) -> list[str] | None:
        """``counties`` and the counties of ``states`` just past them; ``None`` for whole states."""
        if counties is None:
            return None
        return [*counties, *sorted(self.grid.around(counties, states))]

    def expected(
        self, listing: Identity, states: Sequence[str], counties: Sequence[str] | None
    ) -> str | None:
        """The id of the only in-scope record ``listing`` is compatible with, else ``None``.

        A town's name alone (kind ``"place"``) that no district is named for
        means the district of a public school in the town named for it, when
        that district's name begins with the town's (``"Ashfield"`` for
        ``"Ashfield Valley Unified"``, whose ``"Ashfield High"`` is there, or for
        ``"Ashfield Township School District"``, whose ``"Ashfield Elementary"``
        is).

        With counties given, the records of the counties just past them count
        too (:meth:`reach`): a list strays there, so a record there that the
        listing fits leaves it no answer, and is never the answer itself. So
        does a school the listing may mean, though not surely (``maybe``, see
        :func:`compatible`). A school whose name is the listing's comes before
        one whose person's forenames the listing leaves out, and before one of a
        given name it may mean (:meth:`tier`): ``"Whitcombe Elementary"`` names
        ``"Whitcombe Elementary"`` beside ``"R. D. Whitcombe Elementary"``, and the
        latter only where it is the one school of the surname.
        """
        reach = self.reach(states, counties)
        found = self._compatible(listing, states, reach)
        if listing.kind == "place" and not found:
            found = self._town_school_districts(listing, states, reach)
        maybes = self._compatible(listing, states, reach, maybe=True) - found
        exact = {record_id for record_id in found if self.tier(listing, record_id) != LEFT}
        if exact:
            # A school whose name is the listing's comes before one whose person's
            # forenames the listing leaves out, and before a school of a given name
            # the listing may mean.
            found = exact
            maybes = {record_id for record_id in maybes if self.tier(listing, record_id) != MAYBE}
        if len(found) != 1 or maybes:
            return None
        only = found.pop()
        if counties is not None and not self.in_scope(self.by_id[only].record, states, counties):
            return None
        if self.namesakes_across(self.by_id[only], listing, states, reach):
            return None
        return only

    def tier(self, listing: Identity, record_id: str) -> str:
        """How ``listing`` names the person record ``record_id`` is named for (:func:`person_fit`).

        :data:`SURE` for a record of no person, or of the listing's name.
        """
        record = self.by_id[record_id].identity
        if listing.surname is None and record.surname is None:
            return SURE
        return person_fit(listing, record) or SURE

    def namesakes_across(
        self,
        item: SyntheticRecord,
        listing: Identity,
        states: Sequence[str],
        counties: Sequence[str] | None,
    ) -> list[SyntheticRecord]:
        """The districts in another state in scope that bear district ``item``'s name.

        The same base (or second name), level, and a county's district or
        neither; a number the listing gives, both carry. However else their
        states write them (a legal form, a municipal word, a number the listing
        leaves out: Missouri's ``"ASHFIELD R-III"`` and Kansas's ``"Ashfield"``),
        the listing names neither: which state it means is no matter of wording.
        Only a point much nearer one of them tells (:meth:`nearest`).
        """
        identity = item.identity
        if item.record.kind != "district" or identity.coded or identity.form is not None:
            return []
        county = identity.qualifier == "County"
        wanted = set(listing.numbers)
        found: list[SyntheticRecord] = []
        for base in _bases(identity):
            for other in self.by_base.get(base, ()):
                theirs = other.identity
                if (
                    other.record.kind == "district"
                    and other.record.state != item.record.state
                    and other not in found
                    and self.in_scope(other.record, states, counties)
                    and not theirs.coded
                    and theirs.form is None
                    and theirs.affiliation is None
                    and theirs.level == identity.level
                    and (theirs.qualifier == "County") == county
                    and wanted <= set(theirs.numbers)
                    and wanted <= set(identity.numbers)
                ):
                    found.append(other)
        return found

    def nearest(
        self, listing: Identity, states: Sequence[str], near: tuple[float, float]
    ) -> str | None:
        """The record a listing names across ``states`` whole, read from the point ``near``.

        The records it fits or may mean, and the namesakes across a state line
        of those it fits (:meth:`namesakes_across`), tie; the one much nearer ``near`` than the
        rest wins (:data:`NEAR_RATIO`, :data:`NEAR_SLACK_KM`, :data:`NEAR_MAX_KM`),
        when the listing fits it and every other lies beyond the market's reach of
        the point (:data:`NEAR_REACH_KM`). Otherwise none.
        """
        found = self._compatible(listing, states, None)
        tied = {
            record_id: self.by_id[record_id]
            for record_id in self._compatible(listing, states, None, maybe=True) | found
        }
        for record_id in found:
            for other in self.namesakes_across(self.by_id[record_id], listing, states, None):
                tied.setdefault(other.record.id, other)
        if len(tied) == 1:
            return next(iter(found), None)
        distances = sorted(
            (haversine_km(near, item.record.point), record_id)
            for record_id, item in tied.items()
            if item.record.point is not None
        )
        if len(distances) != len(tied) or not distances:
            return None
        (first, winner), (second, _) = distances[0], distances[1]
        if (
            first > NEAR_MAX_KM
            or second < NEAR_RATIO * first + NEAR_SLACK_KM
            or second <= NEAR_REACH_KM
        ):
            return None
        return winner if winner in found else None

    def _town_school_districts(
        self, listing: Identity, states: Sequence[str], counties: Sequence[str] | None
    ) -> set[str]:
        town = _norm(listing.base)
        found: set[str] = set()
        for item in self.by_base.get(town, ()):
            record = item.record
            owner = self.districts.get(record.district_id or "")
            if (
                record.kind == "school"
                and owner is not None
                and record.city is not None
                and _norm((record.city,)) == town
                and not owner.identity.coded
                and _norm(owner.identity.base).startswith(town)
                and self.in_scope(record, states, counties)
                and self.in_scope(owner.record, states, counties)
            ):
                found.add(owner.record.id)
        return found

    @staticmethod
    def _namesake_elsewhere(
        listing: Identity, item: SyntheticRecord, found: Sequence[SyntheticRecord]
    ) -> bool:
        """Whether a listing that leaves out ``item``'s ``Township`` names a namesake elsewhere.

        ``"Ashfield Schools"`` fits ``"Ashfield Township School District"`` only
        with its ``Township`` set aside, which another district bearing the name
        forbids (:meth:`shared`): ``"Ashfield School District"`` beside it is the
        listing's name as it is. But when a district the listing fits lies in
        another county, the two are two places of one name, and a list writes
        each for its own market without the word that sets it apart from the
        other (NCES writes New Jersey's townships with ``Township`` or without,
        and the lists too): the listing names both, and so neither, unless a
        point much nearer one of them tells (:meth:`nearest`). So do two
        ``"Ashfield Township"`` districts of two counties for ``"Ashfield
        Schools"``. A listing that says the word (``"Ashfield Township
        Schools"``) still names only the districts whose names say it.
        """
        if listing.qualifier is not None or item.identity.qualifier != "Township":
            return False
        county = item.record.county_fips
        return any(
            other is not item
            and other.record.kind == "district"
            and other.record.county_fips != county
            for other in found
        )

    def _compatible(
        self,
        listing: Identity,
        states: Sequence[str],
        counties: Sequence[str] | None,
        *,
        maybe: bool = False,
    ) -> set[str]:
        pool: list[SyntheticRecord] = list(self.by_base.get(_norm(listing.base), ()))
        if listing.kind == "school":
            # A school of the other word's plural (plural_twins).
            pool.extend(
                item for item in self.by_twin.get(_twin_key(listing.base), ()) if item not in pool
            )
            # A school named for a person, by its surname or its person's name.
            _given, surname = _person_of(listing)
            pool.extend(item for item in self.by_surname.get(surname, ()) if item not in pool)
            if listing.surname is not None:
                pool.extend(item for item in self.by_base.get(surname, ()) if item not in pool)
        if listing.codes and listing.kind == "district":
            pool.extend(self.coded)
        found = [
            item
            for item in pool
            if self.in_scope(item.record, states, counties)
            and compatible(listing, item.identity, maybe=maybe)
            and self.codes_fit(listing, item)
        ]
        found = [
            item
            for item in found
            if not (needs_forgiving(listing, item.identity) and self.shared(item, states, counties))
            or self._namesake_elsewhere(listing, item, found)
        ]
        if listing.affiliation is not None and any(
            item.identity.affiliation == listing.affiliation for item in found
        ):
            # A school that says the listing's faith is its reading, over one
            # whose saint's name only implies it.
            found = [item for item in found if item.identity.affiliation == listing.affiliation]
        return {item.record.id for item in found}


# -- listings -------------------------------------------------------------------

_DISTRICT_DESIGNATORS = (
    "Schools",
    "School District",
    "Public Schools",
    "SD",
    "School System",
    "Sch. Dist.",
)
_NOISE = (
    "",
    "",
    "",
    " (Closed)",
    " - 2 Hour Delay",
    ": Closed",
    " (E-Learning Day)",
    " - Early Dismissal at 1 PM",
)
_DISTRICT_NOISE = (*_NOISE, " - All Schools", " (All Schools)", ", all locations")


def _spell_base(
    rng: random.Random, words: tuple[str, ...], identity: Identity, *, shorten: float = 0.5
) -> str:
    """Spell a base the way listings do; ``shorten`` is the chance a direction is abbreviated."""
    text = " ".join(words)
    direction = text.split(" ", 1)[0]
    if direction in DIRECTION_FORMS and rng.random() < shorten:
        text = rng.choice(DIRECTION_FORMS[direction]) + text[len(direction) :]
    if identity.initial and rng.random() < 0.5:
        given, surname = text.split(" ")
        text = f"{given} {identity.initial}. {surname}"
    if identity.street and rng.random() < 0.5:
        long_form, short_form = identity.street
        text = text.removesuffix(long_form) + short_form
    if text.startswith("Mount ") and rng.random() < 0.5:
        text = "Mt. " + text[6:]
    if text.startswith("Fort ") and rng.random() < 0.5:
        text = "Ft. " + text[5:]
    if text.endswith(" Jr") and rng.random() < 0.5:
        text = text[:-3] + " Jr."
    return text


def _exempted_village_text(rng: random.Random, base: str, identity: Identity) -> str:
    """An Ohio exempted village district as a listing names it, or without its "Village"."""
    if identity.qualifier == "Village":
        forms = (
            "Exempted Village Schools",
            "Exempted Village School District",
            "EVSD",
            "Exempted Village SD",
        )
        return f"{base} {rng.choice(forms)}"
    return f"{base} {rng.choice(_DISTRICT_DESIGNATORS)}"


def _district_text(rng: random.Random, base: str, identity: Identity) -> str:
    if identity.legal == "Exempted Village":
        return _exempted_village_text(rng, base, identity)
    parts = [base]
    if identity.qualifier:
        qualifier = identity.qualifier
        if qualifier == "County" and rng.random() < 0.3:
            qualifier = "Co."
        if qualifier == "Township" and rng.random() < 0.4:
            qualifier = "Twp."
        parts.append(qualifier)
    legal = identity.legal
    if legal in {"ISD", "CISD"}:
        parts.append(rng.choice((legal, "Independent School District", "I.S.D.", "Schools")))
    elif legal in {"CUSD", "CCSD"} and rng.random() < 0.6:
        parts.append(legal)
    elif legal and rng.random() < 0.5:
        parts.append(legal.title())
        parts.append(rng.choice(_DISTRICT_DESIGNATORS))
    elif identity.level:
        parts.append("Elementary School District")
    else:
        parts.append(rng.choice(_DISTRICT_DESIGNATORS))
    if identity.numbers:
        number = identity.numbers[0]
        if legal in {"CUSD", "CCSD", "SD"}:
            parts.append(rng.choice((number, f"#{number}", f"No. {number}")))
        else:
            roman = _ROMAN[int(number)]
            parts.append(rng.choice((f"R-{number}", f"R-{roman}", f"R{number}")))
    return " ".join(parts)


def _school_text(rng: random.Random, base: str, identity: Identity) -> str:
    if identity.form is not None:
        return identity.form.format(town=base)
    affiliation = f" {identity.affiliation}" if identity.affiliation else ""
    if identity.saint:
        saint = identity.base[0]
        plain = saint if saint.endswith("s") else f"{saint}s"
        spelled = rng.choice((f"St. {saint}'s", f"Saint {saint}", f"St {plain}", f"St. {saint}"))
        rest = "".join(f" {word}" for word in identity.base[1:])
        return f"{spelled}{rest}{affiliation} {rng.choice(('School', 'School', 'Sch.'))}"
    if identity.noun == "Academy":
        return f"{base}{affiliation} {rng.choice(('Academy', 'Acad.'))}"
    if identity.noun == "Schools":
        return f"{base}{affiliation} {rng.choice(('Schools', 'Schools', 'School System'))}"
    if identity.noun == "School" or identity.level is None:
        return f"{base} School"
    return f"{base} {rng.choice(LEVEL_LISTING[identity.level])}"


_CODE_FORMS: dict[str, tuple[str, ...]] = {
    "RSU": (
        "RSU {n}", "RSU #{n}", "R.S.U. {n}", "Regional School Unit {n}", "RSU {n:02d}", "RSU{n}",
    ),
    "MSAD": (
        "MSAD {n}", "M.S.A.D. #{n}", "SAD {n}", "MSAD #{n}",
        "Maine School Administrative District {n}",
    ),
    "USD": ("USD {n}", "USD #{n}", "U.S.D. {n}", "USD No. {n}"),
    "AOS": ("AOS {n}", "AOS #{n}"),
}  # fmt: skip
# A district's programs, which closings lists name after its code.
PROGRAMS: tuple[str, ...] = (
    "Adult Education", "Adult Ed.", "Adult & Community Education", "Food Services",
    "Transportation",
)  # fmt: skip


def _code_text(rng: random.Random, code: str) -> str:
    series, number = code.split()
    return rng.choice(_CODE_FORMS[series]).format(n=int(number))


def _coded_listing(rng: random.Random, identity: Identity) -> str:
    """A listing that begins with a district code: ``"RSU 13 - Ashfield"``, ``"USD 320 ..."``."""
    codes = " / ".join(_code_text(rng, code) for code in identity.codes)
    if identity.kind == "district" and not identity.base:
        return codes + rng.choice(_DISTRICT_NOISE)
    base = _spell_base(rng, identity.base, identity)
    if identity.kind == "program":
        rest = rng.choice(PROGRAMS)
    elif identity.kind == "district":
        kansas = identity.codes[0].startswith("USD")
        rest = base + rng.choice(("", " Schools", " Public Schools" if kansas else " Area"))
        if kansas and rng.random() < 0.25:
            return f"{rest} {codes}"
    else:
        rest = _school_text(rng, base, identity)
    return f"{codes}{rng.choice((' ', ' - ', ': '))}{rest}"


def render_listing(rng: random.Random, identity: Identity, *, shorten: float = 0.5) -> str:
    """Spell a listing for ``identity`` the way a closings list might.

    ``shorten`` is the chance a direction in the base is abbreviated (``"E."``).
    """
    if identity.codes:
        return _coded_listing(rng, identity)
    base = _spell_base(rng, identity.base, identity, shorten=shorten)
    if identity.kind == "college":
        return rng.choice(COLLEGE_FORMS).format(town=base) + rng.choice(_NOISE)
    if identity.kind == "civic":
        assert identity.form is not None
        text = identity.form.format(town=base)
        return _upper_if(text, rng.random() < 0.15) + rng.choice(_NOISE)
    if identity.kind == "place":
        return _upper_if(base, rng.random() < 0.2) + rng.choice(_DISTRICT_NOISE)
    if identity.kind == "district":
        text = _district_text(rng, base, identity)
    else:
        text = _school_text(rng, base, identity)
    pick = rng.random()
    if pick < 0.15:
        text = text.upper()
    elif pick < 0.2:
        text = text.lower()
    group = identity.kind == "district" or identity.noun == "Schools"
    return text + rng.choice(_DISTRICT_NOISE if group else _NOISE)


def _mutations(rng: random.Random, identity: Identity) -> Identity:
    """A listing that says something the record does not (a level, a number)."""
    if identity.kind == "school" and identity.level is not None:
        others = [lv for lv in LEVEL_LISTING if lv != identity.level]
        return replace(identity, level=rng.choice(others))
    if identity.numbers:
        return replace(identity, numbers=(str(int(identity.numbers[0]) % 12 + 1),))
    if identity.qualifier == "County":
        return replace(identity, qualifier=None)
    return replace(identity, base=(*identity.base, "Heights"))


def _omissions(rng: random.Random, identity: Identity) -> Identity:
    """A listing that leaves out what a closings list often drops."""
    if identity.qualifier in _TOWN_QUALIFIERS or identity.qualifier == "Township":
        return replace(identity, qualifier=None)
    if identity.numbers:
        return replace(identity, numbers=())
    if identity.kind == "school" and identity.level is not None and identity.noun is None:
        return replace(identity, level=None)
    if identity.affiliation is not None and identity.noun != "Schools" and rng.random() < 0.5:
        # A group of schools without its faith ("Ashfield Schools") names the district.
        return replace(identity, affiliation=None)
    return identity


@dataclass(frozen=True, slots=True)
class _Towns:
    """Towns that hard negatives are written for, per state."""

    system: dict[str, list[str]]
    """Towns a private school system is named for ("Ashfield Christian Schools")."""
    college: dict[str, list[str]]
    """Towns a "College High School" or "University Academy" is named for."""
    municipal: list[tuple[str, str, str]]
    """``(state, town, qualifier)`` of every district named "<town> City",
    "<town> Exempted Village" or "<town> Town"."""
    neighbours: list[tuple[SyntheticRecord, SyntheticRecord]]
    """``(district, neighbour)``: a town's district and the district of the town
    named for its direction from it ("Ashfield", "East Ashfield")."""
    lone: list[SyntheticRecord]
    """Districts named for a town that has no such neighbour."""
    places: list[tuple[str, str, str]]
    """``(state, town, county)`` of every district's town."""
    named: list[tuple[str, str, str]]
    """``(state, town, county)`` of the towns a school is named for (``"Ashfield
    Elementary"``, ``"Ashfield High"`` of ``"Ashfield Valley Unified"``, ``"Village
    School of Ashfield"``)."""


def _named_for_towns(records: Sequence[SyntheticRecord]) -> _Towns:
    """The towns private schools are named for, and the towns districts are named for."""
    towns = _Towns(defaultdict(list), defaultdict(list), [], [], [], [], [])
    districts: dict[tuple[str, str], SyntheticRecord] = {}
    for item in records:
        if item.record.kind == "district" and len(item.identity.base) == 1:
            districts[item.record.state, item.identity.base[0]] = item
    for (state, base), item in districts.items():
        direction, _, rest = base.partition(" ")
        parent = districts.get((state, rest)) if direction in DIRECTION_FORMS else None
        if parent is not None:
            towns.neighbours.append((parent, item))
    has_neighbour = {parent.record.id for parent, _ in towns.neighbours}
    towns.lone.extend(
        item
        for item in districts.values()
        if item.record.id not in has_neighbour
        and item.identity.base[0].split(" ", 1)[0] not in DIRECTION_FORMS
        and item.style != "me"
    )
    named: set[tuple[str, str, str]] = set()
    for item in records:
        identity = item.identity
        record = item.record
        if record.city is None:
            continue
        place = (record.state, record.city, record.county_fips or "")
        if record.kind == "district":
            towns.places.append(place)
        elif identity.base == (record.city,) and identity.affiliation is None:
            named.add(place)
        if record.kind == "district" and identity.qualifier in GOVERNMENT_OF:
            towns.municipal.append((record.state, identity.base[0], identity.qualifier))
        if item.style != "private":
            continue
        if identity.noun == "Schools":
            towns.system[record.state].append(record.city)
        elif identity.base[1:] in {("College",), ("University",)}:
            towns.college[record.state].append(record.city)
    towns.named.extend(sorted(named))
    return towns


def _civic_negative(rng: random.Random, towns: _Towns) -> tuple[Identity, str]:
    """A town's government, community place or church, beside its district.

    The town is one a district is named for as a city, a village or a town
    ("Ashfield City"), so the listing shares the district's words: half of them
    name the government the way the district names the town (``"City of
    Ashfield"``), the rest a hall, a senior center, a library, a church ...
    The kind of district is picked first, so the few exempted villages and town
    districts get as many listings as the many city districts.
    """
    kinds = sorted({qualifier for _state, _town, qualifier in towns.municipal})
    kind = rng.choice(kinds)
    state, town, qualifier = rng.choice([m for m in towns.municipal if m[2] == kind])
    form = GOVERNMENT_OF[qualifier] if rng.random() < 0.5 else rng.choice(CIVIC_FORMS)
    return Identity("civic", (town,), form=form), state


def _hard_negative(
    rng: random.Random, record: DirectoryRecord, towns: _Towns
) -> tuple[Identity, str, str]:
    """A listing for a town that no public record answers to; also its note and state.

    A church or faith beside the town's name (``"Ashfield Catholic Schools"``),
    which a private school of that faith and town alone may answer; a college or
    university named for the town (``"Ashfield College"``), which nothing in a
    K-12 directory answers, most of them for a town with a "College High School";
    or a town's government, community place or church (:func:`_civic_negative`),
    which no school answers either.
    """
    assert record.city is not None
    roll = rng.random()
    if roll < 0.35:
        nearby = towns.system.get(record.state)
        town = rng.choice(nearby) if nearby and rng.random() < 0.5 else record.city
        faith = rng.choice(FAITHS)
        identity = Identity("school", (town,), noun="Schools", affiliation=faith)
        return identity, "faith and town", record.state
    if roll < 0.7 or not towns.municipal:
        nearby = towns.college.get(record.state)
        town = rng.choice(nearby) if nearby and rng.random() < 0.75 else record.city
        return Identity("college", (town,)), "college or university", record.state
    identity, state = _civic_negative(rng, towns)
    return identity, "civic body", state


DIRECTION_NOTE = "direction"
_DIRECTION_SHARE = 0.05


def _direction_case(
    rng: random.Random, towns: _Towns, schools: dict[str, list[SyntheticRecord]], oracle: Oracle
) -> Case:
    """A listing that says a direction, mostly abbreviated: ``"E. Ashfield Schools"``.

    For a town with a neighbour named for its direction: the neighbour's
    district or one of its schools, the town's own district, or a direction
    neither has (``"W. Ashfield Schools"`` beside ``"Ashfield"`` and ``"East
    Ashfield"``). For a town with none: a direction before its name, which
    names nothing (``"S. Ashfield Public Schools"``). Half of them name the
    county, which both towns share.
    """
    roll = rng.random()
    if roll < 0.6 and towns.neighbours:
        parent, neighbour = rng.choice(towns.neighbours)
        pick = rng.random()
        if pick < 0.4:
            item = neighbour
        elif pick < 0.55:
            item = parent
        elif pick < 0.8 or not schools.get(neighbour.record.id):
            taken = neighbour.identity.base[0].split(" ", 1)[0]
            other = rng.choice([d for d in DIRECTIONS if d != taken])
            item = replace(
                parent,
                identity=replace(parent.identity, base=(f"{other} {parent.identity.base[0]}",)),
            )
        else:
            item = rng.choice(schools[neighbour.record.id])
    else:
        lone = rng.choice(towns.lone)
        direction = rng.choice(DIRECTIONS)
        item = replace(
            lone, identity=replace(lone.identity, base=(f"{direction} {lone.identity.base[0]}",))
        )
    record = item.record
    states = (record.state,)
    counties = (record.county_fips,) if record.county_fips and rng.random() < 0.5 else None
    identity = item.identity
    listing = render_listing(rng, identity, shorten=0.85)
    return Case(
        listing, states, oracle.expected(identity, states, counties), counties, note=DIRECTION_NOTE
    )


PLACE_NOTE = "place"
_PLACE_SHARE = 0.06
_NAMED_TOWN_SHARE = 0.6


def _place_case(rng: random.Random, towns: _Towns, oracle: Oracle) -> Case:
    """A listing that is only a town's name: ``"Ashfield"``, ``"ASHFIELD - Closed"``.

    Most are towns a school is named for (``"Ashfield Elementary"``, the
    ``"Ashfield High"`` of ``"Ashfield Valley Unified"``, ``"Village School of
    Ashfield"``), which the listing never means; the rest any district's town.
    Half name the town's county.
    """
    named = towns.named and rng.random() < _NAMED_TOWN_SHARE
    state, town, county = rng.choice(towns.named if named else towns.places)
    identity = Identity("place", (town,))
    states = (state,)
    counties = (county,) if county and rng.random() < 0.5 else None
    listing = render_listing(rng, identity)
    return Case(
        listing, states, oracle.expected(identity, states, counties), counties, note=PLACE_NOTE
    )


CODE_NOTE = "district code"
_CODE_SHARE = 0.05


def _other_code(rng: random.Random, code: str) -> str:
    """The same series with another number."""
    series, number = code.split()
    return f"{series} {int(number) + rng.randint(1, 4)}"


def _district_code_case(
    rng: random.Random, item: SyntheticRecord, oracle: Oracle
) -> tuple[Identity, tuple[str, ...] | None]:
    """A listing that gives a district code for ``item``, or a wrong one; also its counties.

    A district by its code alone or with its town (``"RSU 13"``, ``"RSU 13 -
    Ashfield"``, ``"USD 320 Ashfield"``), a school after its district's code
    (``"RSU 13 Lincoln Elementary"``), and the hard negatives: another number,
    the other series (``"MSAD 13"`` for ``"RSU 13"``), a program (``"RSU 13 -
    Adult Education"``), another district's town, a school after another
    district's code, and a town district's school after a unit's code. A
    school of a town district after an ``AOS`` code no district's name gives
    is that school.
    """
    if item.record.kind == "district":
        return _code_for_district(rng, item, oracle), None
    return _code_for_school(rng, item, oracle)


def _code_for_district(rng: random.Random, item: SyntheticRecord, oracle: Oracle) -> Identity:
    record, identity = item.record, item.identity
    roll = rng.random()
    codes = identity.codes
    chosen = codes if identity.coded and rng.random() < 0.3 else (rng.choice(codes),)
    base = () if identity.coded and rng.random() < 0.5 else identity.base
    if roll < 0.45:
        return replace(identity, codes=chosen, base=base, coded=False, hidden=False)
    if roll < 0.6:
        return replace(identity, codes=(_other_code(rng, chosen[0]),), base=base)
    if roll < 0.7 and chosen[0].startswith(("RSU", "MSAD")):
        series, number = chosen[0].split()
        other = "MSAD" if series == "RSU" else "RSU"
        return replace(identity, codes=(f"{other} {number}",), base=base)
    if roll < 0.85:
        return Identity("program", (), codes=chosen)
    towns = [
        d.identity.base
        for d in oracle.districts.values()
        if d.record.state == record.state
        and d.identity.base != identity.base
        and d.style not in _CHARTER_STYLES
    ]
    return replace(identity, codes=chosen, base=rng.choice(towns))


def _code_for_school(
    rng: random.Random, item: SyntheticRecord, oracle: Oracle
) -> tuple[Identity, tuple[str, ...] | None]:
    record, identity = item.record, item.identity
    roll = rng.random()
    counties = (record.county_fips,) if record.county_fips and rng.random() < 0.5 else None
    owner = oracle.districts[record.district_id or ""]
    own = owner.identity.codes
    if own and roll < 0.6:
        codes = (rng.choice(own),)
    elif own:
        others = [
            code
            for d in oracle.districts.values()
            if d.record.state == record.state and d is not owner
            for code in d.identity.codes
        ]
        codes = (rng.choice(others),)
    elif roll < 0.5:
        codes = (f"AOS {rng.randint(90, 99)}",)
    else:
        codes = (f"RSU {rng.randint(1, 60)}",)
    return replace(identity, codes=codes), counties


def _code_case(rng: random.Random, coded: Sequence[SyntheticRecord], oracle: Oracle) -> Case:
    """A labelled listing that begins (or, in Kansas, may end) with a district code."""
    chosen = rng.choice(coded)
    identity, counties = _district_code_case(rng, chosen, oracle)
    states = (chosen.record.state,)
    listing = render_listing(rng, identity)
    return Case(
        listing, states, oracle.expected(identity, states, counties), counties, note=CODE_NOTE
    )


NETWORK_NOTE = "network"
STRADDLE_NOTE = "straddles the market"
_NETWORK_SHARE = 0.04
_STRADDLE_SHARE = 0.15
_NETWORK_LISTINGS: dict[str, tuple[str, ...]] = {
    "high": ("{b} High School", "{b} High Schools", "{B} HIGH SCHOOL", "{b} HS"),
    "academy": ("{b} Academy", "{B} ACADEMY", "{b} Academy Schools"),
    "system": ("{b} Public Schools", "{b} Schools", "{B} PUBLIC SCHOOLS"),
}
_CAMPUS_LISTINGS: dict[str, tuple[str, ...]] = {
    "high": ("{b} High School {t}", "{b} High School - {t}", "{B} H.S. - {T}"),
    "academy": ("{b} Academy - {t}", "{b} Academy {t}", "{B} ACADEMY - {T}"),
    "system": ("{b} {t} {n}",),
}
_OTHER_KIND: dict[str, tuple[str, ...]] = {
    "high": ("{b} Middle School", "{b} Elementary"),
    "academy": ("{b} Elementary School", "{b} Middle School"),
    "system": ("{b} Academy",),
}


@dataclass(frozen=True, slots=True)
class _Network:
    """A charter network of the directory: its district and its campuses."""

    district: SyntheticRecord
    campuses: tuple[SyntheticRecord, ...]

    @property
    def brand(self) -> str:
        return self.district.identity.base[0]

    @property
    def kind(self) -> str:
        identity = self.district.identity
        if identity.level == "high":
            return "high"
        return "academy" if identity.noun == "Academy" else "system"

    @property
    def counties(self) -> list[str]:
        return sorted({item.record.county_fips or "" for item in self.campuses})

    def within(self, counties: Iterable[str]) -> list[SyntheticRecord]:
        """Its campuses in ``counties``."""
        market = set(counties)
        return [item for item in self.campuses if item.record.county_fips in market]


def _networks(records: Sequence[SyntheticRecord]) -> list[_Network]:
    campuses: dict[str, list[SyntheticRecord]] = defaultdict(list)
    districts: list[SyntheticRecord] = []
    for item in records:
        if item.style != NETWORK_STYLE:
            continue
        if item.record.kind == "district":
            districts.append(item)
        else:
            campuses[item.record.district_id or ""].append(item)
    return [_Network(item, tuple(campuses[item.record.id])) for item in districts]


def _spell(form: str, brand: str, town: str = "", noun: str = "") -> str:
    return form.format(b=brand, B=brand.upper(), t=town, T=town.upper(), n=noun)


def _network_case(rng: random.Random, scene: "_Scene") -> Case:
    """A listing for a charter network or one of its campuses, from one market.

    The network's name from a market that holds one of its campuses names that
    campus; from one that holds two, or from two markets, it names none it can
    tell apart. A campus's name with its town names the campus; the network's
    name with another kind of school (``"Solvane Middle School"`` for a network
    of high schools, ``"Corvane Academy"`` where its campus is a college
    preparatory school) names nothing. Some listings instead name an ordinary
    district from a market that holds only one of its schools, just across a
    county line: that is the district, whole.
    """
    if scene.straddling and rng.random() < _STRADDLE_SHARE:
        item, county = rng.choice(scene.straddling)
        states = (item.record.state,)
        expected = scene.oracle.expected(item.identity, states, (county,))
        listing = render_listing(rng, item.identity)
        return Case(listing, states, expected, (county,), note=STRADDLE_NOTE)
    network = rng.choice(scene.networks)
    brand, kind = network.brand, network.kind
    states = (network.district.record.state,)
    county = rng.choice(network.counties)
    roll = rng.random()
    if roll < 0.6:
        market: tuple[str, ...] = (county,)
        if rng.random() < 0.3:
            market = (county, rng.choice([c for c in scene.counties[states[0]] if c != county]))
        listing = _spell(rng.choice(_NETWORK_LISTINGS[kind]), brand) + rng.choice(_NOISE)
        here = network.within(market)
        expected = here[0].record.id if len(here) == 1 else None
        return Case(listing, states, expected, market, note=NETWORK_NOTE)
    if roll < 0.85:
        campus = rng.choice(network.campuses)
        town = campus.identity.base[1]
        noun = campus.identity.noun or ""
        listing = _spell(rng.choice(_CAMPUS_LISTINGS[kind]), brand, town, noun)
        where = (campus.record.county_fips or "",)
        return Case(listing, states, campus.record.id, where, note=NETWORK_NOTE)
    forms = _OTHER_KIND[kind]
    if kind == "system":
        # Its academy's name where its one campus is a college preparatory school.
        prep = [
            c
            for c in network.counties
            if [i.identity.noun for i in network.within((c,))] == ["College Preparatory"]
        ]
        county, forms = (rng.choice(prep), forms) if prep else (county, _OTHER_KIND["academy"])
    listing = _spell(rng.choice(forms), brand) + rng.choice(_NOISE)
    return Case(listing, states, None, (county,), note=NETWORK_NOTE)


ACADEMY_NOTE = "a district's own name"
_ACADEMY_SHARE = 0.04
_ACADEMY_LISTINGS: tuple[str, ...] = ("{b} Academy", "{B} ACADEMY", "{b} Academy", "{b} Acad.")


@dataclass(frozen=True, slots=True)
class _Academy:
    """A charter district named as one academy, and its schools."""

    district: SyntheticRecord
    schools: tuple[SyntheticRecord, ...]


def _academies(records: Sequence[SyntheticRecord]) -> list[_Academy]:
    schools: dict[str, list[SyntheticRecord]] = defaultdict(list)
    districts: list[SyntheticRecord] = []
    for item in records:
        if item.style != ACADEMY_STYLE:
            continue
        if item.record.kind == "district":
            districts.append(item)
        else:
            schools[item.record.district_id or ""].append(item)
    return [_Academy(item, tuple(schools[item.record.id])) for item in districts]


def _academy_school_text(rng: random.Random, identity: Identity) -> str:
    """One of an academy district's schools as a listing names it: ``"Arvenne Academy Middle"``."""
    head = " ".join((f"{identity.base[0]} Academy", *identity.base[1:]))
    if identity.level is None:
        return rng.choice(
            (head, f"{head} School", f"{identity.base[0]} Academy - {identity.base[1]}")
        )
    return f"{head} {rng.choice(LEVEL_LISTING[identity.level])}"


def _academy_case(rng: random.Random, scene: "_Scene") -> Case:
    """A listing for a charter district named as one academy, or one of its schools.

    The district's name alone, word for word (``"Arvenne Academy"``, ``"BELVORA
    ACADEMY - All Schools"``), names the district, never the one of its schools
    whose name adds only a level to it (``"Belvora Academy Middle"``); a school's
    own name names that school. Some are aimed at another state, which may have
    an academy of that name of its own, and some at a level none of its schools
    has (``"Arvenne Academy High School"``), which names nothing. Half name the
    district's county.
    """
    academy = rng.choice(scene.academies)
    district = academy.district
    brand = district.identity.base[0]
    states: tuple[str, ...] = (district.record.state,)
    counties = (district.record.county_fips or "",) if rng.random() < 0.5 else None
    identity = district.identity
    roll = rng.random()
    if roll < 0.55:
        listing = _spell(rng.choice(_ACADEMY_LISTINGS), brand) + rng.choice(_DISTRICT_NOISE)
    elif roll < 0.85:
        identity = rng.choice(academy.schools).identity
        listing = _academy_school_text(rng, identity) + rng.choice(_NOISE)
    elif roll < 0.93:
        states = (rng.choice([s for s in scene.states if s != states[0]]),)
        counties = None
        listing = _spell(rng.choice(_ACADEMY_LISTINGS), brand) + rng.choice(_DISTRICT_NOISE)
    else:
        identity = Identity("school", (brand,), level="high", noun="Academy", form=ACADEMY_FORM)
        listing = _academy_school_text(rng, identity) + rng.choice(_NOISE)
    expected = scene.oracle.expected(identity, states, counties)
    return Case(listing, states, expected, counties, note=ACADEMY_NOTE)


@dataclass(frozen=True, slots=True)
class _Scene:
    """What the case writer knows about a directory."""

    oracle: Oracle
    towns: _Towns
    coded: list[SyntheticRecord]
    """Maine's and Kansas's districts with codes, and every school of theirs."""
    states: list[str]
    counties: dict[str, list[str]]
    """Each state's counties."""
    schools: dict[str, list[SyntheticRecord]]
    """Each district's schools, by district id."""
    plain: list[SyntheticRecord]
    """Every record but the charter networks' and the academy districts'."""
    networks: list["_Network"]
    straddling: list[tuple[SyntheticRecord, str]]
    """Districts with a school in a county beside their own, and that county."""
    academies: list[_Academy]
    namesakes: list[tuple[SyntheticRecord, SyntheticRecord]]
    """``(namesake, district)``: a district named for a town elsewhere, and that
    town's own district."""
    bracketed: list[SyntheticRecord]
    """Districts whose names end with their county or a second name."""
    county_roots: dict[str, str]
    """Each county's name without ``County``, by FIPS code."""
    stated: list[SyntheticRecord]
    """Districts and schools whose base a record of another state bears too."""
    base_states: dict[str, set[str]]
    """The states whose records bear each base, by :func:`_norm`."""
    saints: list[SyntheticRecord]
    """Private schools named for a saint, whose parish's church bears the name too."""
    borders: list["_Border"]
    """Towns whose namesakes lie on either side of a two-state market's counties."""
    municipal: list[SyntheticRecord]
    """Districts named for a town, with no county qualifier: see :func:`_municipal_case`."""
    systems: list["_System"]
    """School systems NCES splits into districts: see :func:`_system_case`."""
    twins: list["_Twin"]
    """Twin towns across a state line: see :func:`_across_case`."""
    townships: list["_Twin"]
    """Townships of one name in two counties of one state: see :func:`_township_case`."""
    leading: list[SyntheticRecord]
    """Private schools whose names begin with or hold a place word: see :func:`_leading_case`."""
    levels: list[tuple[SyntheticRecord, ...]]
    """Schools of one name in one county, some whose names leave out their level: see
    :func:`_level_case`."""
    forenames: list[tuple[SyntheticRecord, ...]]
    """Schools named for a person, of one surname in one county: see :func:`_forename_case`."""
    plurals: list[tuple[SyntheticRecord, ...]]
    """Schools named for a word with a plural's ``s`` or without it, in one county: see
    :func:`_plural_case`."""


BRACKET_NOTE = "a bracket NCES ends a name with"
_BRACKET_SHARE = 0.03


def _bracket_case(rng: random.Random, scene: "_Scene") -> Case:
    """A listing for a district whose name ends with its county or a second name.

    A second name alone (``"Lake Vesper"``), with the district's designators
    (``"Lake Vesper CSD"``) or as its high school's (``"Lake Vesper High
    School"``); or the district's own name with its county (``"Ashfield Public
    Schools - Abernathy County"``, ``"Ashfield School District (Abernathy)"``),
    which a listing of that name statewide needs, since another county's
    district bears it too. Some are searched in another state.
    """
    item = rng.choice(scene.bracketed)
    record, identity = item.record, item.identity
    states: tuple[str, ...] = (record.state,)
    named: str | None = None
    if identity.aliases:
        alias = rng.choice(identity.aliases)
        roll = rng.random()
        if roll < 0.3:
            said = replace(identity, base=(alias,))
            listing = _upper_if(alias, rng.random() < 0.3) + rng.choice(_DISTRICT_NOISE)
        elif roll < 0.5:
            said = Identity("school", (alias,), level="high")
            listing = render_listing(rng, said)
        else:
            said = replace(identity, base=(alias,))
            listing = render_listing(rng, said)
    else:
        said = identity
        root = scene.county_roots[record.county_fips or ""]
        text = _district_text(rng, _spell_base(rng, identity.base, identity), identity)
        county = rng.choice((f" ({root})", f" - {root} County", f", {root} Co."))
        listing = text + county + rng.choice(_DISTRICT_NOISE)
        named = root
    if rng.random() < 0.15:
        states = (rng.choice([s for s in scene.states if s != record.state]),)
    if named is None:
        expected = scene.oracle.expected(said, states, None)
    else:
        # The county the listing names is the one a district's name brackets:
        # its office's, any county of that name in the state searched.
        found = {
            item.record.id
            for item in scene.oracle.by_base.get(_norm(said.base), ())
            if item.record.state in states
            and scene.county_roots.get(item.record.county_fips or "") == named
            and compatible(said, item.identity)
        }
        expected = found.pop() if len(found) == 1 else None
    return Case(listing, states, expected, note=BRACKET_NOTE)


STATE_NOTE = "a state beside the name"
_STATE_SHARE = 0.05
_FIRM_ABBREVIATIONS = {
    state: short
    for short, state in lexicon.STATE_ABBREVIATIONS.items()
    if short not in lexicon.LOOSE_STATE_ABBREVIATIONS
}


_SYSTEM_WORDS = frozenset({"Schools", "School", "Public", "SD", "School District", "District"})
"""Words a district's text may go on with after its county."""


def _spell_state(rng: random.Random, state: str, *, alone: bool) -> str | None:
    """How a list writes ``state``: its code, a newspaper abbreviation or its name.

    ``alone``: the state stands alone (in brackets, after a comma or a hyphen), where
    any spelling reads as a state; after a word only a code that is no word itself
    (not ``MS``, ``SD``, ``IN``) or a newspaper abbreviation does, or ``None``.
    """
    if alone:
        spellings = [state, state, lexicon.STATE_NAMES[state]]
        if state in _FIRM_ABBREVIATIONS:
            spellings.append(_FIRM_ABBREVIATIONS[state])
        return rng.choice(spellings)
    if state not in lexicon.LOOSE_STATE_CODES:
        return state
    return _FIRM_ABBREVIATIONS.get(state)


def _state_listing(  # noqa: PLR0911 - one return per way a list writes it
    rng: random.Random, item: SyntheticRecord, state: str, town: str | None
) -> tuple[str, bool]:
    """A listing for ``item`` that writes ``state`` beside its name, in one of a list's ways.

    Before the designators (``"Ashfield MA Public Schools"``, ``"Ashfield County, TN
    Schools"``, ``"Ashfield (TX) ISD"``, ``"Ashfield Co. AL Schools"``), before a
    qualifier (``"Ashfield, VA City Schools"``), after the name (``"Ashfield Public
    Schools, KY"``, ``"ASHFIELD SCHOOLS-IN"``, ``"Ashfield High School (N.C.)"``),
    or, given the ``town`` the record lies in, after the name and its town
    (``"Ashfield R-IV Schools Ashfield MO"``, ``"Lincoln Elementary, Ashfield
    NH"``) or between them (``"Ashfield R-IV MO Ashfield"``). Also says whether it
    wrote the town.
    """
    identity = item.identity
    base = _spell_base(rng, identity.base, identity)
    if identity.kind == "district":
        text = _district_text(rng, base, identity)
    else:
        text = _school_text(rng, base, identity)
    firm = _spell_state(rng, state, alone=False)
    alone = _spell_state(rng, state, alone=True)
    roll = rng.random()
    if identity.kind == "district" and text.startswith(base) and roll < 0.45:
        words = text[len(base) :].split()
        spelled_qualifier = {identity.qualifier, "Co.", "Twp."} if identity.qualifier else set()
        k = 1 if words and words[0] in spelled_qualifier else 0
        head, tail = " ".join([base, *words[:k]]), " ".join(words[k:])
        if k and identity.qualifier in _TOWN_QUALIFIERS and tail and rng.random() < 0.3:
            # "Ashfield, VA City Schools": the qualifier after the state.
            return f"{base}, {state} {' '.join(words)}", False
        if tail and roll < 0.25:
            if firm is not None:
                return f"{head} {firm} {tail}", False
            if k and identity.qualifier == "County" and tail.split()[0] in _SYSTEM_WORDS:
                # "Ashfield Co. AL Schools": a code that is also a word, after the county.
                return f"{head} {state} {tail}", False
        return f"{head}{rng.choice((f' ({alone})', f', {alone}'))} {tail}".rstrip(), False
    written = town is not None and (roll >= 0.6 or rng.random() < 0.5)
    if firm is not None and roll < 0.6 and identity.form is None:
        if written and len(firm) == 2 and rng.random() < 0.3:
            # "Ashfield R-4 MO Ashfield": the state between the name and its town.
            return f"{text} {firm} {town}", True
        return (f"{text} {town} {firm}" if written else f"{text} {firm}"), written
    if roll < 0.75 and written:
        return (f"{text}, {town} {firm}" if firm is not None else f"{text}, {town}, {alone}"), True
    endings = (f"{text} ({alone})", f"{text}, {alone}", f"{text.upper()}-{state}")
    return rng.choice(endings), False


def _state_case(rng: random.Random, scene: "_Scene") -> Case:
    """A listing that writes its state beside its name, in a market of two or three states.

    The market holds states whose records bear the listing's name too, so the
    name alone cannot tell them apart; the listing's state can. It names the
    record's own state, and sometimes the town the record lies in; or another
    of the market's states (whose namesake, if any, it then names); or a state
    outside the market, the record's own among them, when it names nothing
    there. A listing never writes one state's town beside another state.
    """
    item = rng.choice(scene.stated)
    record = item.record
    others = sorted(scene.base_states[_norm(item.identity.base)] - {record.state})
    namesakes = rng.sample(others, min(len(others), rng.choice((1, 2))))
    market = {record.state, *namesakes}
    roll = rng.random()
    if roll < 0.7:
        named = record.state
    elif roll < 0.85:
        named = rng.choice(namesakes)
    elif roll < 0.95:
        # The record's own state, which this market (its namesakes') does not
        # cover: the listing names no record of the market.
        market = set(namesakes)
        named = record.state
    else:
        named = rng.choice([s for s in scene.states if s not in market])
    town = record.city if named == record.state else None
    listing, with_town = _state_listing(rng, item, named, town)
    states = tuple(sorted(market))
    if named not in market:
        expected = None
    elif with_town:
        # The town tells apart the state's namesakes: the one that lies there.
        found = {
            candidate.record.id
            for candidate in scene.oracle.by_base.get(_norm(item.identity.base), ())
            if candidate.record.state == named
            and candidate.record.city == town
            and compatible(item.identity, candidate.identity)
        }
        expected = found.pop() if len(found) == 1 else None
    else:
        expected = scene.oracle.expected(item.identity, (named,), None)
    return Case(listing, states, expected, note=STATE_NOTE)


NAMESAKE_NOTE = "a district named for a town elsewhere"
_NAMESAKE_SHARE = 0.03


def _namesakes(records: Sequence[SyntheticRecord]) -> list[tuple[SyntheticRecord, SyntheticRecord]]:
    """Each namesake district with the district of the town it is named for."""
    towns = {
        (item.record.state, item.identity.base[0]): item
        for item in records
        if item.record.kind == "district"
        and item.style != NAMESAKE_STYLE
        and len(item.identity.base) == 1
    }
    pairs: list[tuple[SyntheticRecord, SyntheticRecord]] = []
    for item in records:
        if item.style != NAMESAKE_STYLE or item.record.kind != "district":
            continue
        base = item.identity.base[0]
        home = towns.get((item.record.state, base)) or towns[item.record.state, base[:-1]]
        pairs.append((item, home))
    return pairs


def _namesake_case(rng: random.Random, scene: "_Scene") -> Case:
    """A town's name, or a district's, where a district of that name lies far from the town.

    ``"Ashfield"`` from the namesake's own county is the namesake, whatever the
    town of Ashfield's district, and from the town's county it is the town's;
    statewide it is either, so nothing, unless the namesake spells the town's
    name another way (``"Ashfields Local"``), which only a listing that spells
    it so names. Some listings give the district's own name (``"ASHFIELD
    ISD"``, ``"Ashfields Local Schools"``).
    """
    namesake, home = rng.choice(scene.namesakes)
    state = namesake.record.state
    plural = namesake.identity.base != home.identity.base
    identity = (
        Identity("place", namesake.identity.base) if rng.random() < 0.7 else namesake.identity
    )
    roll = rng.random()
    counties: tuple[str, ...] | None = None
    if roll < 0.45:
        counties = (namesake.record.county_fips or "",)
    elif roll < 0.7 and not plural:
        counties = (home.record.county_fips or "",)
    listing = render_listing(rng, identity)
    expected = scene.oracle.expected(identity, (state,), counties)
    return Case(listing, (state,), expected, counties, note=NAMESAKE_NOTE)


PARISH_NOTE = "a parish's name"
_PARISH_SHARE = 0.03
_CHURCHES = (
    "{saint} Parish",
    "{saint} Catholic Church",
    "{saint} Church - Services Canceled",
    "{saint} Parish: No Mass",
    "Church of {saint}",
    "{saint} Religious Education",
)
_UNKNOWN_SECTIONS = (None, "Closings", "Other")
"""Sections that say nothing of what a listing is, or no section."""
_NO_SCHOOL_SECTIONS = (*_UNKNOWN_SECTIONS, "Churches", "Religious", "Pre-Schools/Daycare")
_SCHOOL_SECTIONS = ("Schools", "Private Schools", "Parochial School", "SCHOOLS")


def _parish_case(rng: random.Random, scene: _Scene) -> Case:
    """A listing for a saint's school, or for its parish's church, in the school's county.

    The church's (``"St. Anne's Parish"``, ``"St. Anne Catholic Church"``,
    ``"St. Anne's Parish: No Mass"``) names no school. The saint's name alone
    (``"St. Anne's"``) is the church's as much as the school's, unless the list
    files it among schools, when it names the saint's school the oracle finds
    in the county, if only one. With a school's word (``"St. Anne's School"``,
    ``"St. Anne Catholic School"``) it names the school whatever the section.
    """
    item = rng.choice(scene.saints)
    record = item.record
    saint = item.identity.base[0]
    states = (record.state,)
    counties = (record.county_fips,) if record.county_fips is not None else None
    spelled = rng.choice(
        (f"St. {saint}'s", f"St. {saint}", f"Saint {saint}", f"ST. {saint.upper()}")
    )
    roll = rng.random()
    if roll < 0.35:
        listing = rng.choice(_CHURCHES).format(saint=spelled)
        return Case(listing, states, None, counties, note=f"{PARISH_NOTE}: its church")
    school = Identity("school", (saint,), noun="School", saint=True)
    if roll < 0.6:
        category = rng.choice(_NO_SCHOOL_SECTIONS)
        note = f"{PARISH_NOTE}: its church or its school"
        return Case(spelled, states, None, counties, note=note, category=category)
    if roll < 0.8:
        expected = scene.oracle.expected(school, states, counties)
        category = rng.choice(_SCHOOL_SECTIONS)
        note = f"{PARISH_NOTE}: filed among schools"
        return Case(spelled, states, expected, counties, note=note, category=category)
    if rng.random() < 0.5:
        school = replace(school, affiliation="Catholic")
        listing = f"{spelled} Catholic School"
    else:
        listing = f"{spelled} School"
    category = rng.choice((*_UNKNOWN_SECTIONS, *_SCHOOL_SECTIONS))
    expected = scene.oracle.expected(school, states, counties)
    note = f"{PARISH_NOTE}: a school's word"
    return Case(listing, states, expected, counties, note=note, category=category)


BORDER_NOTE = "a namesake just past the counties"
_BORDER_SHARE = 0.04


@dataclass(frozen=True, slots=True)
class _Border:
    """A town's namesakes in the two states of a market: see :meth:`_Generator.borders`."""

    town: str
    person: str
    """Whose name a school of each bears."""
    states: tuple[str, str]
    """The market's state, and its second state."""
    counties: tuple[str, str]
    """The market's county, and the second state's county of the namesake."""


def _borders(records: Sequence[SyntheticRecord]) -> list[_Border]:
    """The towns :meth:`_Generator.borders` made namesakes of, in the order it made them."""
    districts = [
        item for item in records if item.style == BORDER_STYLE and item.record.kind == "district"
    ]
    elementary = {
        item.record.district_id: item.identity.base[0]
        for item in records
        if item.style == BORDER_STYLE and item.identity.level == "elementary"
    }
    return [
        _Border(
            town=first.identity.base[0],
            person=elementary[first.record.id],
            states=(first.record.state, second.record.state),
            counties=(first.record.county_fips or "", second.record.county_fips or ""),
        )
        for first, second in zip(districts[0::2], districts[1::2], strict=True)
    ]


def _border_case(rng: random.Random, scene: _Scene) -> Case:
    """A listing for a town's district or school whose namesake lies across the market's line.

    Mostly from the market's county, in both its states: when the namesake's
    county lies just past it, the listing fits both and names neither
    (``"Ashfield School District"`` is the namesake's name word for word, the
    market's ``"Ashfield"`` shorter); when far, the market's. Some from the
    market's state alone, whose namesake is none of the listing's; some from
    the namesake's county; some from both states whole.
    """
    border = rng.choice(scene.borders)
    first, second = border.states
    market, other = border.counties
    pick = rng.random()
    if pick < 0.4:
        identity = Identity("district", (border.town,))
    elif pick < 0.7:
        identity = Identity("school", (border.town,), level="high")
    else:
        identity = Identity("school", (border.person,), level="elementary")
    roll = rng.random()
    states: tuple[str, ...] = (first, second)
    counties: tuple[str, ...] | None = (market,)
    if roll < 0.15:
        states = (first,)
    elif roll < 0.3:
        counties = (other,)
    elif roll < 0.4:
        counties = None
    listing = render_listing(rng, identity)
    expected = scene.oracle.expected(identity, states, counties)
    return Case(listing, states, expected, counties, note=BORDER_NOTE)


MUNICIPAL_NOTE = "a municipal word one side says"
_MUNICIPAL_SHARE = 0.05
_CIVIC_TOWN_FORMS: tuple[str, ...] = (
    "{town}, City of",
    "{town}, Town of",
    "{town}, Township of",
    "{town} Borough",
    "{town} Township",
    "{town} Twp.",
)
"""A town's government as a list writes it without a school's word: a municipality,
never the district named for the town otherwise."""


def _municipal_case(rng: random.Random, scene: _Scene) -> Case:
    """A district's listing that says a municipal word its NCES name does not, or the other way.

    NCES and the lists each say or leave out what kind of municipality a
    district's town is: ``"Ashfield City Schools"`` or ``"Ashfield Township
    School District"`` for ``"Ashfield School District"`` or ``"Ashfield
    Local"``, ``"Ashfield Schools"`` for ``"Ashfield Township School District"``.
    That names the district unless another in scope bears the rest of its name
    (``"East Ashfield SD"``), which the oracle knows (:func:`needs_forgiving`).
    Some listings name the town's government in words no school says (``"City of
    Ashfield"`` or ``"Ashfield, City of"`` beside ``"Ashfield City"``, ``"Ashfield,
    Town of"`` or ``"Ashfield Borough"`` beside ``"Ashfield School District"``):
    never a school. Half are read in the district's county, half statewide.
    """
    item = rng.choice(scene.municipal)
    record = item.record
    identity = item.identity
    town = identity.base[0]
    counties = (record.county_fips,) if record.county_fips and rng.random() < 0.5 else None
    states = (record.state,)
    if rng.random() < 0.25:
        government = GOVERNMENT_OF.get(identity.qualifier or "")
        if government is not None:
            # "City of Ashfield" or "Ashfield, City of" beside "Ashfield City".
            form = rng.choice((government, f"{{town}}, {identity.qualifier} of"))
        elif identity.qualifier in MUNICIPAL_QUALIFIERS:
            form = rng.choice(_CIVIC_TOWN_FORMS[:3])
        else:
            form = rng.choice(_CIVIC_TOWN_FORMS)
        listing = form.format(town=_spell_base(rng, identity.base, identity))
        civic = Identity("civic", (town,), form=form)
        expected = scene.oracle.expected(civic, states, counties)
        return Case(listing, states, expected, counties=counties, note=MUNICIPAL_NOTE)
    if identity.qualifier in MUNICIPAL_QUALIFIERS:
        said = replace(identity, qualifier=None)
    else:
        said = replace(identity, qualifier=rng.choice(("City", "Township", "Borough", "Town")))
    listing = render_listing(rng, said)
    expected = scene.oracle.expected(said, states, counties)
    return Case(listing, states, expected, counties=counties, note=MUNICIPAL_NOTE)


ACROSS_NOTE = "a namesake across a state line"
_ACROSS_SHARE = 0.04


@dataclass(frozen=True, slots=True)
class _Twin:
    """A town's districts on either side of a state line: see :meth:`_Generator.across`."""

    town: str
    districts: tuple[SyntheticRecord, SyntheticRecord]
    """The first state's district, and the second's."""


def _twins(records: Sequence[SyntheticRecord]) -> list[_Twin]:
    """The twin towns :meth:`_Generator.across` made, in the order it made them."""
    districts = [
        item for item in records if item.style == ACROSS_STYLE and item.record.kind == "district"
    ]
    return [
        _Twin(first.identity.base[0], (first, second))
        for first, second in zip(districts[0::2], districts[1::2], strict=True)
    ]


def _across_case(rng: random.Random, scene: _Scene) -> Case:
    """A listing for a town whose twin across a state line bears its district's name.

    Each state writes the name its own way, so the listing names neither when
    it is read in both states (``"Ashfield Public Schools"`` for Missouri's
    ``"ASHFIELD R-III"`` and Kansas's ``"Ashfield"``, ``"Ashfield City Schools"``
    for Tennessee's ``"Ashfield"`` and Virginia's ``"Ashfield City Public
    Schools"``), unless it says what only one of them has (a number) or a
    point much nearer one of them tells (:meth:`Oracle.nearest`); read in one
    state, or with that state written beside the name (``"Ashfield KS
    Schools"``), it names that state's. Some name the town's high school, which
    each twin runs.
    """
    twin = rng.choice(scene.twins)
    town = twin.town
    item = rng.choice(twin.districts)
    pick = rng.random()
    identity: Identity
    if pick < 0.2:
        identity = Identity("place", (town,))
    elif pick < 0.5:
        identity = Identity("district", (town,))
    elif pick < 0.62:
        identity = Identity("district", (town,), qualifier="City")
    elif pick < 0.87:
        identity = item.identity
    else:
        identity = Identity("school", (town,), level="high")
    states = tuple(sorted({twin.districts[0].record.state, twin.districts[1].record.state}))
    roll = rng.random()
    if roll < 0.15:
        one = (item.record.state,)
        return Case(
            render_listing(rng, identity),
            one,
            scene.oracle.expected(identity, one, None),
            note=ACROSS_NOTE,
        )
    if roll < 0.3 and identity.kind == "district":
        listing, _written = _state_listing(rng, item, item.record.state, None)
        expected = scene.oracle.expected(item.identity, (item.record.state,), None)
        return Case(listing, states, expected, note=ACROSS_NOTE)
    listing = render_listing(rng, identity)
    if roll < 0.55:
        point = item.record.point
        assert point is not None
        near = (point[0] + rng.uniform(-0.01, 0.01), point[1] + rng.uniform(-0.01, 0.01))
        expected = scene.oracle.nearest(identity, states, near)
        return Case(listing, states, expected, near=near, note=ACROSS_NOTE)
    return Case(listing, states, scene.oracle.expected(identity, states, None), note=ACROSS_NOTE)


TOWNSHIP_NOTE = "two townships of one name in two counties"
_TOWNSHIP_SHARE = 0.05
_TOWNSHIP_LISTINGS: tuple[str, ...] = (
    "{town} Township Schools",
    "{town} Township Public Schools",
    "{town} Twp. School District",
    "{town} Twp Schools",
    "{upper} TOWNSHIP SCHOOLS",
    "Township of {town} Public Schools",
    "Township of {town} School District",
    "Township of {town} Schools",
    "{town} Township Schools - All Schools",
)
"""How a list names a township's district, ``Township`` said, in either word order."""
_TOWNSHIP_LEFT_OUT: tuple[str, ...] = (
    "{town} Schools",
    "{town} Public Schools",
    "{town} School District",
)
"""How a list names a township's district without ``Township``."""


def _townships(records: Sequence[SyntheticRecord]) -> list[_Twin]:
    """The townships :meth:`_Generator.townships` made, two by two, as it made them."""
    districts = [
        item for item in records if item.style == TOWNSHIP_STYLE and item.record.kind == "district"
    ]
    return [
        _Twin(first.identity.base[0], (first, second))
        for first, second in zip(districts[0::2], districts[1::2], strict=True)
    ]


def _township_case(rng: random.Random, scene: _Scene) -> Case:
    """A listing for a township whose namesake in another county of its state runs a district.

    Each NCES name is written its own way (``"Township of Ashfield School
    District"``, ``"Ashfield Township School District"``, ``"Ashfield Township
    Public School District"``, ``"Ashfield School District"``) and a list writes
    either in either word order, with ``Township`` or without: the listing names
    both, and so neither, unless it is read in one county (and the other lies
    beyond a list's reach of it) or a point much nearer one of them tells
    (:meth:`Oracle.nearest`). A listing that says ``Township`` names only the
    districts whose names say it; one that is only ``"Township of Ashfield"``
    names the township's government, no school.
    """
    twin = rng.choice(scene.townships)
    town = twin.town
    item = rng.choice(twin.districts)
    record = item.record
    states = (record.state,)
    pick = rng.random()
    identity: Identity
    if pick < 0.06:
        form = "Township of {town}"
        listing = form.format(town=town)
        identity = Identity("civic", (town,), form=form)
    elif pick < 0.7:
        listing = rng.choice(_TOWNSHIP_LISTINGS).format(town=town, upper=town.upper())
        identity = Identity("district", (town,), qualifier="Township")
    else:
        listing = rng.choice(_TOWNSHIP_LEFT_OUT).format(town=town)
        identity = Identity("district", (town,))
    roll = rng.random()
    if roll < 0.35:
        point = record.point
        assert point is not None
        near = (point[0] + rng.uniform(-0.01, 0.01), point[1] + rng.uniform(-0.01, 0.01))
        expected = scene.oracle.nearest(identity, states, near)
        return Case(listing, states, expected, near=near, note=TOWNSHIP_NOTE)
    counties: tuple[str, ...] | None = None
    if roll < 0.6:
        assert record.county_fips is not None
        counties = (record.county_fips,)
    elif roll < 0.7:
        counties = tuple(sorted(other.record.county_fips or "" for other in twin.districts))
    expected = scene.oracle.expected(identity, states, counties)
    return Case(listing, states, expected, counties=counties, note=TOWNSHIP_NOTE)


LEADING_NOTE = "a place word that begins or holds a school's name"
LEADING_NEGATIVE = "hard negative: a school's place word left out"
_LEADING_SHARE = 0.04
_LEADING_POSITIVE = 0.35


def _leading_spelling(rng: random.Random, name: str) -> str:
    """A school's own name as a list writes it: in its case or another, ``&`` or ``and``."""
    text = name.replace("&", "and") if "&" in name and rng.random() < 0.5 else name
    if text.endswith(("Academy", "ACADEMY")) and rng.random() < 0.3:
        text = text[: -len("Academy")] + "Acad."
    pick = rng.random()
    if pick < 0.25:
        text = text.title()
    elif pick < 0.4:
        text = text.upper()
    return text + rng.choice(_NOISE)


def _leading_form(item: SyntheticRecord) -> tuple[tuple[_LeftOut, ...], str]:
    """How a listing leaves out ``item``'s place word, and the made-up word its name uses."""
    name = item.record.name.casefold()
    for template, _base, _noun, _faith, left_out in LEADING_SCHOOLS:
        for word in LEADING_WORDS:
            if template.format(f=item.identity.affiliation, w=word).casefold() == name:
                return left_out, word
    raise AssertionError(item.record.name)


def _leading_case(rng: random.Random, scene: _Scene) -> Case:
    """A listing for a school whose name begins with or holds a place word, or without it.

    ``"Village Christian Academy"``, ``"Town and Country Day School"``, ``"Kid City
    Academy"`` name their schools; ``"Christian Academy"``, ``"Country Day School"``,
    ``"Kids Academy"`` and ``"Academy"`` leave out a word of the name (see
    :data:`LEADING_SCHOOLS`) and name none of them. Half are read in the school's
    county, half statewide.
    """
    item = rng.choice(scene.leading)
    record = item.record
    identity = item.identity
    states = (record.state,)
    counties = (record.county_fips,) if record.county_fips and rng.random() < 0.5 else None
    if rng.random() < _LEADING_POSITIVE:
        listing = _leading_spelling(rng, record.name)
        expected = scene.oracle.expected(identity, states, counties)
        return Case(listing, states, expected, counties=counties, note=LEADING_NOTE)
    left_out, word = _leading_form(item)
    text, base, noun = rng.choice(left_out)
    faith = identity.affiliation
    said = Identity(
        "school",
        tuple(part.format(w=word) for part in base),
        noun=noun,
        affiliation=faith if "{f}" in text.casefold() else None,
    )
    listing = text.format(f=faith, F=(faith or "").upper(), w=word, W=word.upper())
    listing += rng.choice(_NOISE)
    expected = scene.oracle.expected(said, states, counties)
    return Case(listing, states, expected, counties=counties, note=LEADING_NEGATIVE)


LEVEL_NOTE = "a level a school's name leaves out"
LEVEL_NEGATIVE = "hard negative: a level a namesake's name leaves out"
_LEVEL_SHARE = 0.05
_LEVEL_OTHERS: tuple[str, ...] = (
    "elementary", "middle", "high", "primary", "juniorhigh", "prekindergarten",
)  # fmt: skip
PREK_LISTING: tuple[str, ...] = ("Preschool", "Pre-K", "Preschool", "PreK")
"""How a list names a school's preschool (its ``prekindergarten`` level)."""


def _level_groups(records: Sequence[SyntheticRecord]) -> list[tuple[SyntheticRecord, ...]]:
    """The groups :meth:`_Generator.levels` made: its schools of one name in one county."""
    groups: dict[tuple[str, str | None, str], list[SyntheticRecord]] = defaultdict(list)
    for item in records:
        if item.style == LEVEL_STYLE:
            key = (item.record.state, item.record.county_fips, _norm(item.identity.base))
            groups[key].append(item)
    return [tuple(group) for group in groups.values()]


def _level_text(rng: random.Random, identity: Identity) -> str:
    """A listing for a school by its name and the level ``identity`` says, or ``School``."""
    base = identity.base[0]
    head = base
    if identity.saint:
        own = f"St. {base}'s" if not base.endswith("s") else f"St. {base}"
        head = rng.choice((f"St. {base}", f"St {base}", f"Saint {base}", own))
    if identity.affiliation is not None:
        head = f"{head} {identity.affiliation}"
    if identity.level is None:
        words: tuple[str, ...] = ("School",)
    elif identity.level == "prekindergarten":
        words = PREK_LISTING
    else:
        words = LEVEL_LISTING[identity.level]
    text = f"{head} {rng.choice(words)}"
    return (text.upper() if rng.random() < 0.2 else text) + rng.choice(_NOISE)


def _level_case(rng: random.Random, scene: _Scene) -> Case:
    """A listing for a school by a level its name, or its namesake's, leaves out.

    The groups of :meth:`_Generator.levels`: ``"Dunbar Elementary"`` names
    ``"Dunbar Elementary School"`` and the K-5 ``"Dunbar"`` beside it, and so
    neither; ``"St. Joseph Elementary"`` both PK-8 parish schools of the name;
    ``"St. John Lutheran Preschool"`` the PK-1 school, and the PK-8 one may be
    meant too. A school of other grades is none of the level (``"Dunbar
    Elementary"`` names the K-5 school beside a 6-8 ``"Dunbar School"``, and
    ``"Dunbar Middle School"`` the 6-8 one), and one alone of its name is the
    listing's by any level its grades are (``"Dunbar Elementary"``, ``"Dunbar
    Primary"`` for the lone K-5 ``"Dunbar"``). Mostly the level the group's first
    school says (or a preschool), else another its schools are; now and then
    another, or none. Read in the group's county, or statewide; the answer is the
    oracle's.
    """
    group = rng.choice(scene.levels)
    first = group[0]
    record = first.record
    said = sorted(
        {
            level
            for item in group
            for level in (
                {item.identity.level} if item.identity.level else _levels(item.identity, maybe=True)
            )
        }
    )
    key = first.identity.level or ("prekindergarten" if "prekindergarten" in said else said[0])
    roll = rng.random()
    level: str | None = None
    if roll < 0.6:
        level = key
    elif roll < 0.8:
        level = rng.choice(said)
    elif roll < 0.95:
        level = rng.choice(_LEVEL_OTHERS)
    identity = replace(first.identity, level=level, grades=None)
    states = (record.state,)
    counties = (record.county_fips,) if record.county_fips and rng.random() < 0.7 else None
    expected = scene.oracle.expected(identity, states, counties)
    note = LEVEL_NOTE if expected is not None else LEVEL_NEGATIVE
    return Case(_level_text(rng, identity), states, expected, counties=counties, note=note)


def _groups(records: Sequence[SyntheticRecord], style: str) -> list[tuple[SyntheticRecord, ...]]:
    """The groups of ``style`` a generator made, as its schools in one county.

    A forename group shares a surname (:meth:`_Generator.forenames`), a plural group a
    word written with a plural's ``s`` or without (:meth:`_Generator.plurals`).
    """
    found: dict[tuple[str, str | None, str], list[SyntheticRecord]] = defaultdict(list)
    for item in records:
        if item.style == style:
            key = item.identity.surname or _norm(item.identity.base).removesuffix("s")
            found[(item.record.state, item.record.county_fips, key)].append(item)
    return [tuple(group) for group in found.values()]


FORENAME_NOTE = "a person's forenames a listing leaves out"
FORENAME_NEGATIVE = "hard negative: a surname two schools' people share"
_FORENAME_SHARE = 0.04
_OTHER_GIVEN: tuple[str, ...] = ("Bernice", "Cornelia", "Dexter", "Evangeline")
"""Given names no generated school's person bears (all given names of the Census list)."""


def _forenames_text(rng: random.Random, parts: tuple[str, ...]) -> str:
    """Forenames as a list writes them: initials dotted or not, run together or not."""
    written = " ".join(parts)
    if all(len(part.rstrip(".")) == 1 for part in parts):
        return rng.choice((written, written.replace(" ", ""), written.replace(".", "")))
    return written if rng.random() < 0.6 else written.replace(".", "")


def _forename_case(rng: random.Random, scene: _Scene) -> Case:
    """A listing for a school named for a person, by its surname or its person's name.

    The groups of :meth:`_Generator.forenames`. Mostly the surname and level alone
    (``"Braxcombe Elementary"``), which names a school whose forenames are surely
    a person's (initials, or a forename and an initial: ``"R. D. Braxcombe"``,
    ``"Clara J. Braxcombe"``, or bracketed by NCES), one alone of its surname, and
    none where two share it, or where a school of the surname alone
    (``"Braxcombe Elementary"``) or one of a given name alone (``"Clara
    Braxcombe"``, which may be a place's word) is beside it. Else one school's
    person's name, as written or with initials for its forenames (``"C. J.
    Braxcombe"``, ``"Clara Braxcombe"``), or another person's (``"Dexter
    Braxcombe"``), or the surname at another level. Read in the group's county,
    or statewide; the answer is the oracle's.
    """
    group = rng.choice(scene.forenames)
    item = rng.choice(group)
    record = item.record
    identity = item.identity
    surname = identity.surname or identity.base[0]
    level = identity.level
    roll = rng.random()
    given: tuple[str, ...] = ()
    if roll < 0.5:
        pass
    elif roll < 0.75:
        given = identity.given
    elif roll < 0.85 and identity.given:
        given = tuple(f"{part.rstrip('.')[0]}." for part in identity.given)
    elif roll < 0.92:
        given = (rng.choice(_OTHER_GIVEN),)
    else:
        level = rng.choice([other for other in ("elementary", "middle", "high") if other != level])
    said = Identity(
        "school",
        (" ".join((*(part.rstrip(".") for part in given), surname)),),
        level=level,
        surname=surname,
        given=given,
    )
    head = f"{_forenames_text(rng, given)} {surname}" if given else surname
    assert level is not None
    text = f"{head} {rng.choice(LEVEL_LISTING[level])}"
    listing = (text.upper() if rng.random() < 0.2 else text) + rng.choice(_NOISE)
    states = (record.state,)
    counties = (record.county_fips,) if record.county_fips and rng.random() < 0.7 else None
    expected = scene.oracle.expected(said, states, counties)
    note = FORENAME_NOTE if expected is not None else FORENAME_NEGATIVE
    return Case(listing, states, expected, counties=counties, note=note)


PLURAL_NOTE = "a word with a plural's s or without"
PLURAL_NEGATIVE = "hard negative: a word written with a plural's s the other name lacks"
_PLURAL_SHARE = 0.02


def _plural_case(rng: random.Random, scene: _Scene) -> Case:
    """A listing for a school named for a word, with the name's plural ``s`` or the other way.

    The groups of :meth:`_Generator.plurals`: ``"Parks Elementary"`` names the
    school of that name, and ``"Park Elementary"`` none but one named so. Read in
    the group's county, or statewide.
    """
    group = rng.choice(scene.plurals)
    item = rng.choice(group)
    record = item.record
    word = item.identity.base[0]
    if rng.random() < 0.5:
        word = word.removesuffix("s") if word.endswith("s") else f"{word}s"
    said = replace(item.identity, base=(word,), grades=None)
    if said.level is not None:
        text = f"{word} {rng.choice(LEVEL_LISTING[said.level])}"
    else:
        text = f"{'The ' if rng.random() < 0.5 else ''}{word} School"
    listing = (text.upper() if rng.random() < 0.2 else text) + rng.choice(_NOISE)
    states = (record.state,)
    counties = (record.county_fips,) if record.county_fips and rng.random() < 0.7 else None
    expected = scene.oracle.expected(said, states, counties)
    note = PLURAL_NOTE if expected is not None else PLURAL_NEGATIVE
    return Case(listing, states, expected, counties=counties, note=note)


def _scene(records: Sequence[SyntheticRecord]) -> _Scene:
    counties: dict[str, list[str]] = defaultdict(list)
    schools: dict[str, list[SyntheticRecord]] = defaultdict(list)
    plain = [item for item in records if item.style not in _SPECIAL_STYLES]
    for item in records:
        record = item.record
        if record.county_fips is not None and record.county_fips not in counties[record.state]:
            counties[record.state].append(record.county_fips)
        if record.district_id is not None:
            schools[record.district_id].append(item)
    coded = [
        item
        for item in records
        if item.style in {"me", "ks"}
        and (item.identity.codes or item.record.district_id is not None)
    ]
    oracle = Oracle(records)
    straddling = sorted(
        {
            (oracle.districts[item.record.district_id], item.record.county_fips)
            for item in plain
            if item.record.district_id is not None
            and item.record.county_fips is not None
            and item.record.county_fips
            != oracle.districts[item.record.district_id].record.county_fips
        },
        key=lambda pair: (pair[0].record.id, pair[1]),
    )
    bracketed = [
        item
        for item in records
        if item.record.kind == "district"
        and item.record.name.endswith(")")
        and (item.identity.aliases or item.record.state in COUNTY_BRACKET_STATES)
    ]
    county_roots = {
        item.record.county_fips: (item.record.county or "").removesuffix(" County")
        for item in records
        if item.record.county_fips is not None
    }
    base_states: dict[str, set[str]] = defaultdict(set)
    for item in plain:
        base_states[_norm(item.identity.base)].add(item.record.state)
    stated = [
        item
        for item in plain
        if item.identity.kind in {"district", "school"}
        and not item.identity.codes
        and not item.identity.coded
        and len(base_states[_norm(item.identity.base)]) > 1
    ]
    return _Scene(
        oracle=oracle,
        towns=_named_for_towns(plain),
        coded=coded,
        states=sorted({item.record.state for item in records}),
        counties=counties,
        schools=schools,
        plain=plain,
        networks=_networks(records),
        straddling=straddling,
        academies=_academies(records),
        namesakes=_namesakes(records),
        bracketed=bracketed,
        county_roots=county_roots,
        stated=stated,
        base_states=base_states,
        saints=[item for item in plain if item.identity.saint],
        borders=_borders(records),
        municipal=[
            item
            for item in plain
            if item.record.kind == "district"
            and not item.identity.coded
            and not item.identity.codes
            and item.identity.qualifier != "County"
            and item.identity.affiliation is None
            and item.identity.level is None
        ],
        systems=_systems(records),
        twins=_twins(records),
        townships=_townships(records),
        leading=[item for item in records if item.style == LEADING_STYLE],
        levels=_level_groups(records),
        forenames=_groups(records, FORENAME_STYLE),
        plurals=_groups(records, PLURAL_STYLE),
    )


def _record_case(rng: random.Random, item: SyntheticRecord, scene: _Scene) -> Case:
    """A listing for ``item``, or aimed past it (another state or county, a change)."""
    record = item.record
    identity = item.identity
    roll = rng.random()
    scope_states: tuple[str, ...] = (record.state,)
    scope_counties: tuple[str, ...] | None = None
    note = "own state"
    if rng.random() < 0.1:
        identity, note, state = _hard_negative(rng, record, scene.towns)
        listing = render_listing(rng, identity)
        return Case(listing, (state,), scene.oracle.expected(identity, (state,), None), note=note)
    if record.kind == "school" and roll < 0.7:
        assert record.county_fips is not None
        scope_counties = (record.county_fips,)
        note = "own county"
    if roll > 0.9:
        scope_states = (rng.choice([s for s in scene.states if s != record.state]),)
        scope_counties = None
        note = "other state"
    elif roll > 0.85 and record.kind == "school":
        others = [c for c in scene.counties[record.state] if c != record.county_fips]
        scope_counties = (rng.choice(others),)
        note = "other county"
    elif roll > 0.8:
        identity = _mutations(rng, identity)
        note = "changed level or number"
    elif roll > 0.7:
        identity = _omissions(rng, identity)
        note = "left something out"
    listing = render_listing(rng, identity)
    expected = scene.oracle.expected(identity, scope_states, scope_counties)
    return Case(listing, scope_states, expected, counties=scope_counties, note=note)


SYSTEM_NOTE = "a school system NCES splits into districts"
SYSTEM_NEGATIVE = "hard negative: one district of a school system, or none"
_SYSTEM_SHARE = 0.05
_SYSTEM_NAMES: tuple[str, ...] = (
    "{n} Public Schools",
    "{n} Schools",
    "{n} School District",
    "{n} School System",
    "{n}",
    "{n} Public Schools - All Schools",
    "{n} Schools (Closed)",
    "{N} PUBLIC SCHOOLS",
    "{N}",
)
"""How a list names a town's or a city's school system (``{n}`` its name, ``{N}``
upper-cased)."""
_CITY_SYSTEM_NAMES: tuple[str, ...] = (
    *_SYSTEM_NAMES,
    "{n} Department of Education",
    "{n} Dept. of Ed.",
    "{n} DOE",
)


@dataclass(frozen=True, slots=True)
class _System:
    """A school system NCES splits into districts, as :meth:`_Generator.systems` made it.

    ``kind`` is a key of :data:`SYSTEM_KINDS`' values; ``name`` what the system
    is called (``"Ashfield"``, ``"Ashfield City"``); ``districts`` its districts
    in directory order (for ``mt_apart``, the two districts that are no
    system); ``schools`` their schools, by district id; ``charter`` a city's
    charter school's district, which is none of it.
    """

    kind: str
    name: str
    districts: tuple[SyntheticRecord, ...]
    schools: dict[str, tuple[SyntheticRecord, ...]]
    charter: SyntheticRecord | None


def _systems(records: Sequence[SyntheticRecord]) -> list[_System]:
    tagged: dict[tuple[str, str, str], list[SyntheticRecord]] = defaultdict(list)
    charters: dict[tuple[str, str], SyntheticRecord] = {}
    schools: dict[str, list[SyntheticRecord]] = defaultdict(list)
    for item in records:
        if item.style != SYSTEM_STYLE:
            continue
        record = item.record
        if record.kind == "school":
            schools[record.district_id or ""].append(item)
            continue
        form = item.identity.form or ""
        _prefix, kind, name = form.split(":", 2)
        if kind == CITY_CHARTER:
            charters[record.state, name] = item
        else:
            tagged[record.state, kind, name].append(item)
    return [
        _System(
            kind,
            name,
            tuple(districts),
            {
                d.record.id: tuple(schools[d.record.id])
                for d in (*districts, *filter(None, [charters.get((state, name))]))
            },
            charters.get((state, name)),
        )
        for (state, kind, name), districts in tagged.items()
    ]


@dataclass(frozen=True, slots=True)
class _SystemWriter:
    """Writes the listings of one :class:`_System`: see :func:`_system_case`."""

    rng: random.Random
    system: _System

    @property
    def name(self) -> str:
        return self.system.name

    @property
    def town(self) -> str:
        return self.system.name.removesuffix(" City")

    @property
    def state(self) -> tuple[str, ...]:
        return (self.system.districts[0].record.state,)

    def whole(self, forms: Sequence[str] = _SYSTEM_NAMES) -> Case:
        """The system's name: every one of its districts."""
        rng = self.rng
        listing = rng.choice(forms).format(n=self.name, N=self.name.upper())
        first, *rest = self.system.districts
        counties = (first.record.county_fips or "",) if rng.random() < 0.4 else None
        also = tuple(d.record.id for d in rest)
        return Case(listing, self.state, first.record.id, counties, note=SYSTEM_NOTE, also=also)

    def both(self, listing: str) -> Case:
        """A listing in words every district's name says: the system, drawn as :meth:`one` is."""
        first, *rest = self.system.districts
        counties = (first.record.county_fips or "",) if self.rng.random() < 0.4 else None
        also = tuple(d.record.id for d in rest)
        return Case(listing, self.state, first.record.id, counties, note=SYSTEM_NOTE, also=also)

    def one(self, listing: str, item: SyntheticRecord | None, note: str = SYSTEM_NEGATIVE) -> Case:
        """A listing that names ``item`` alone, or none (``None``)."""
        where = item if item is not None else self.system.districts[0]
        counties = (where.record.county_fips or "",) if self.rng.random() < 0.4 else None
        expected = item.record.id if item is not None else None
        return Case(listing, self.state, expected, counties, note=note)

    def school(self, district: SyntheticRecord, level: str) -> SyntheticRecord:
        """The school of ``level`` of ``district``."""
        schools = self.system.schools[district.record.id]
        return next(s for s in schools if s.identity.level == level)

    def city(self, roll: float) -> Case:
        """A listing for a city's geographic districts, one of them, its charter, or none."""
        rng, name, system = self.rng, self.name, self.system
        numbered = [d for d in system.districts if "Special" not in d.identity.base]
        special = next(d for d in system.districts if "Special" in d.identity.base)
        if roll < 0.55:
            return self.whole(_CITY_SYSTEM_NAMES)
        if roll < 0.75:
            member = rng.choice(numbered)
            form = rng.choice(
                ("{n} Geographic District {k}", "{n} District {k}", "{n} District #{k}")
            )
            return self.one(form.format(n=name, k=member.identity.numbers[0]), member)
        if roll < 0.85:
            form = rng.choice(("{n} District 75", "{n} Special Schools"))
            return self.one(form.format(n=name), special)
        if roll < 0.92 and system.charter is not None:
            # The charter school, its own district's one school, and none of the city's.
            charter = system.schools[system.charter.record.id][0]
            return self.one(f"{name} Charter School of the Arts", charter)
        form = rng.choice(("{t} Public Schools", "{n} Geographic District 9"))
        return self.one(form.format(t=self.town, n=name), None)

    def town_system(self, roll: float) -> Case:  # noqa: PLR0911 - one return per listing
        """A listing for a town's elementary and high school districts, one of them, or none."""
        rng, town, kind = self.rng, self.town, self.system.kind
        first, second = self.system.districts
        elementary, high = (
            (first, second) if first.identity.level == "elementary" else (second, first)
        )
        if kind == "mt_apart":
            if roll < 0.7:
                name = rng.choice(_SYSTEM_NAMES).format(n=self.name, N=self.name.upper())
                return self.one(name, elementary)
            return self.one(f"{high.identity.base[0]} High School", self.school(high, "high"))
        if roll < 0.6:
            return self.whole()
        if kind in {"ca_union", "ca_office_city", "az_levels"} and roll < 0.75:
            joint = " Joint" if kind == "ca_office_city" else ""
            form = rng.choice(("{t}{j} Union", "{t}{j} Union High School District"))
            if kind == "ca_union" and form == "{t}{j} Union":
                # Both districts' names say "Union" ("Julian Union Elementary",
                # "Julian Union High"): the listing names them both.
                return self.both(form.format(t=town, j=joint))
            return self.one(form.format(t=town, j=joint), high)
        if kind == "il_levels" and roll < 0.75:
            form = rng.choice(("{t} Twp HSD {k}", "{t} Township High School District {k}"))
            return self.one(form.format(t=town, k=high.identity.numbers[0]), high)
        if roll < 0.85:
            return self.elementary(elementary)
        if kind.startswith("mt_"):
            base = high.identity.base[0]
            label = (
                f"{base} County High School" if kind == "mt_office_city" else f"{base} High School"
            )
            return self.one(label, self.school(high, "high"))
        if kind == "il_levels":
            taken = {*elementary.identity.numbers, *high.identity.numbers}
            wrong = next(str(k) for k in range(1, 400) if str(k) not in taken)
            return self.one(f"{town} School District {wrong}", None)
        middle = self.school(elementary, "middle")
        return self.one(f"{town} Middle School", middle, note=SYSTEM_NOTE)

    def elementary(self, district: SyntheticRecord) -> Case:
        """A listing for the elementary district alone, by its level or its number."""
        rng, town, kind = self.rng, self.town, self.system.kind
        numbers = district.identity.numbers
        if numbers:
            form = rng.choice(("{t} ESD {k}", "{t} Elementary School District {k}"))
            return self.one(form.format(t=town, k=numbers[0]), district)
        said = {"ca_union": " Union", "ca_office_city": " City", "mt_office_city": " City"}
        form = rng.choice(("{t}{l} Elementary", "{t}{l} Elem.", "{t}{l} Elementary District"))
        return self.one(form.format(t=town, l=said.get(kind, "")), district)


def _system_case(rng: random.Random, scene: _Scene) -> Case:
    """A listing for a school system NCES splits into districts, or for one of them.

    The system's name, as a list writes a town's or a city's school system
    (:data:`_SYSTEM_NAMES`), names every district of it; a level, a number, a
    legal-form word only one of them says (``"Ashfield Union"``) or a school's
    name names that one. A town whose elementary and high school districts
    each have an office of their own (``mt_apart``) has no system: its name is
    its elementary district's. A city's name without its ``City``
    (``"Ashfield Public Schools"``) or with a district number it does not have
    names none of its districts.
    """
    writer = _SystemWriter(rng, rng.choice(scene.systems))
    roll = rng.random()
    return writer.city(roll) if writer.system.kind == "ny_city" else writer.town_system(roll)


def build_cases(records: Sequence[SyntheticRecord], *, count: int, seed: int) -> list[Case]:
    """Write ``count`` labelled listings for random records of ``records``.

    Most name a record in its own state, schools usually with their county (as
    a closings source would know its market's counties); some are aimed at
    another state, at the wrong county, say a level or number the record does
    not have, or leave out a qualifier, number, level or affiliation; some
    name a faith, a college or a civic body beside a town's name
    (:func:`_hard_negative`); some begin with a district code
    (:func:`_code_case`); some say a direction (:func:`_direction_case`); some
    are only a town's name (:func:`_place_case`); some name a charter
    network, or one of its campuses, from one market, or a district from a
    market that holds only one of its schools (:func:`_network_case`); and some
    name a charter district named as one academy by that name, or one of its
    schools (:func:`_academy_case`); and some name a town, or a district named
    for a town that lies far from it (:func:`_namesake_case`); and some name a
    district whose name ends with its county or a second name by that
    (:func:`_bracket_case`); and some write a state beside the name
    (:func:`_state_case`); and some name a saint's school or its parish's
    church, in a section of the list or none (:func:`_parish_case`); and some
    name a town's district or school whose namesake lies across a two-state
    market's line, just past its counties or far (:func:`_border_case`); and
    some say a municipal word the district's name does not, or leave out one
    it says, or name the town's government (:func:`_municipal_case`); and some
    name a town whose twin across a state line bears its district's name,
    written as the other state writes it (:func:`_across_case`). The last
    few (:data:`_SYSTEM_SHARE` of them) name a school system NCES splits into
    districts, or one of its districts (:func:`_system_case`), and after them
    (:data:`_TOWNSHIP_SHARE` of them) a township whose namesake in another
    county of its state runs a district too, in either word order, with
    ``Township`` or without (:func:`_township_case`), and last
    (:data:`_LEADING_SHARE` of them) a private school whose name begins with or
    holds a place word, by its name or without the word (``"Christian
    Academy"`` for ``"Village Christian Academy"``, :func:`_leading_case`), and
    after them (:data:`_LEVEL_SHARE` of them) a school by a level its name, or
    a namesake's in its county, leaves out (``"St. Joseph Elementary"`` for
    ``"ST JOSEPH SCHOOL"`` beside ``"ST JOSEPH ELEMENTARY SCHOOL"``,
    :func:`_level_case`), and after them (:data:`_FORENAME_SHARE` of them) a
    school named for a person by its surname or its person's name
    (:func:`_forename_case`), and last (:data:`_PLURAL_SHARE` of them) a school
    named for a word by that word with a plural's ``s`` or without
    (:func:`_plural_case`); every listing before them is the same with them or
    without.
    """
    rng = random.Random(seed)  # noqa: S311 - test data, not cryptography
    scene = _scene(records)
    cases: list[Case] = []
    # District-code, direction and place listings (and the rest below) draw
    # from their own generators, so the other listings are the same whatever
    # share of them is mixed in.
    streams = [random.Random(seed + n) for n in range(1, 12)]  # noqa: S311 - test data
    code, direction, place, network, academy, namesake, bracket, state, parish = streams[:9]
    border, municipal = streams[9:]
    towns = scene.towns
    special: tuple[tuple[object, random.Random, float, Callable[[], Case]], ...] = (
        (scene.coded, code, _CODE_SHARE, lambda: _code_case(code, scene.coded, scene.oracle)),
        (
            towns.lone,
            direction,
            _DIRECTION_SHARE,
            lambda: _direction_case(direction, towns, scene.schools, scene.oracle),
        ),
        (towns.places, place, _PLACE_SHARE, lambda: _place_case(place, towns, scene.oracle)),
        (scene.networks, network, _NETWORK_SHARE, lambda: _network_case(network, scene)),
        (scene.academies, academy, _ACADEMY_SHARE, lambda: _academy_case(academy, scene)),
        (scene.namesakes, namesake, _NAMESAKE_SHARE, lambda: _namesake_case(namesake, scene)),
        (scene.bracketed, bracket, _BRACKET_SHARE, lambda: _bracket_case(bracket, scene)),
        (scene.stated, state, _STATE_SHARE, lambda: _state_case(state, scene)),
        (scene.saints, parish, _PARISH_SHARE, lambda: _parish_case(parish, scene)),
        (scene.borders, border, _BORDER_SHARE, lambda: _border_case(border, scene)),
        (scene.municipal, municipal, _MUNICIPAL_SHARE, lambda: _municipal_case(municipal, scene)),
    )
    across = random.Random(seed + 13)  # noqa: S311 - test data, not cryptography
    special = (
        *special,
        (scene.twins, across, _ACROSS_SHARE, lambda: _across_case(across, scene)),
    )
    systems = round(count * _SYSTEM_SHARE) if scene.systems else 0
    townships = round(count * _TOWNSHIP_SHARE) if scene.townships else 0
    leading = round(count * _LEADING_SHARE) if scene.leading else 0
    levels = round(count * _LEVEL_SHARE) if scene.levels else 0
    forenames = round(count * _FORENAME_SHARE) if scene.forenames else 0
    plurals = round(count * _PLURAL_SHARE) if scene.plurals else 0
    last = systems + townships + leading + levels + forenames + plurals
    while len(cases) < count - last:
        for present, stream, share, make in special:
            if present and stream.random() < share:
                cases.append(make())
                break
        else:
            cases.append(_record_case(rng, rng.choice(scene.plain), scene))
    system = random.Random(seed + 12)  # noqa: S311 - test data, not cryptography
    cases.extend(_system_case(system, scene) for _ in range(systems))
    township = random.Random(seed + 14)  # noqa: S311 - test data, not cryptography
    cases.extend(_township_case(township, scene) for _ in range(townships))
    lead = random.Random(seed + 15)  # noqa: S311 - test data, not cryptography
    cases.extend(_leading_case(lead, scene) for _ in range(leading))
    level_stream = random.Random(seed + 16)  # noqa: S311 - test data, not cryptography
    cases.extend(_level_case(level_stream, scene) for _ in range(levels))
    forename_stream = random.Random(seed + 17)  # noqa: S311 - test data, not cryptography
    cases.extend(_forename_case(forename_stream, scene) for _ in range(forenames))
    plural_stream = random.Random(seed + 18)  # noqa: S311 - test data, not cryptography
    cases.extend(_plural_case(plural_stream, scene) for _ in range(plurals))
    return cases
