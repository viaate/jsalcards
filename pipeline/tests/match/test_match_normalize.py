"""Unit tests for name normalization: both spellings of a name must meet."""

import pytest

from snowlight.match import Level
from snowlight.match.forenames import GIVEN_NAMES
from snowlight.match.normalize import (
    DirectoryName,
    NameForm,
    Section,
    SpelledName,
    affiliations_of,
    bracket_form,
    bracketed_forenames,
    chains_of,
    church_name,
    clean_listing,
    clear_caches,
    county_words,
    directory_name,
    district_codes,
    expand_directions,
    fold,
    is_bare_name,
    legal_words,
    listing_forms,
    listing_section,
    named_as_school,
    non_k12,
    not_school,
    qualifies,
    record_form,
    roman_value,
    spelled_name,
    split_brackets,
    without_charter_school,
)


def _key(form: NameForm) -> tuple[object, ...]:
    """What the matcher treats as the same name: compact spelling, levels, qualifiers, numbers."""
    return (form.compact, form.levels, form.qualifiers, form.numbers)


def _district(text: str) -> tuple[object, ...]:
    return _key(listing_forms(text).district)


def _school(text: str) -> tuple[object, ...]:
    return _key(listing_forms(text).school)


@pytest.mark.parametrize(
    ("listing", "directory"),
    [
        ("Houston ISD", "Houston Independent School District"),
        ("Houston Schools", "HOUSTON ISD"),
        ("Brazos Bend C.I.S.D.", "Brazos Bend Consolidated Independent School District"),
        ("Wentzville R-4 School District", "WENTZVILLE R-IV"),
        ("Wentzville R4", "Wentzville R-IV"),
        ("Wentzville R-IV Schools", "WENTZVILLE R-IV"),
        ("Kearney R-1", "KEARNEY R-I"),
        ("Albertville City Schools", "Albertville City"),
        ("Albertville City School System", "Albertville City"),
        ("Fairfax County Public Schools", "Fairfax Co Pblc Schs"),
        ("Lancaster Co. SD", "Lancaster County School District"),
        ("Scarsdale UFSD", "SCARSDALE UNION FREE SCHOOL DISTRICT"),
        ("Scarsdale U.F.S.D.", "Scarsdale Union Free School District"),
        ("Riverhead CSD", "RIVERHEAD CENTRAL SCHOOL DISTRICT"),
        ("Los Angeles USD", "Los Angeles Unified"),
        ("Los Angeles Unified School District", "Los Angeles Unified"),
        ("Waunakee Community Schools", "Waunakee Community School District"),
        ("Waunakee School District", "Waunakee Community School District"),
        ("CUSD #300", "Community Unit School District 300"),
        ("C.U.S.D. No. 300", "Community Unit School District 300"),
        ("Palatine CCSD 15", "Palatine Community Consolidated School District 15"),
        ("Pekin PSD 108", "Pekin Public School District 108"),
        ("School District of Lancaster", "Lancaster SD"),
        ("Public Schools of Robeson County", "Robeson County"),
        ("Madison County Board of Education", "Madison County"),
        ("Madison County BOE", "Madison County"),
        ("Caddo Parish School Board", "Caddo Parish"),
        ("Hamilton Twp. Schools", "Hamilton Township School District"),
        ("Mt. Vernon City Schools", "Mount Vernon City School District"),
        ("Penn-Harris-Madison School Corp.", "Penn Harris Madison School Corporation"),
        ("M.S.A.D. #72", "MSAD 72"),
        ("Adams-Arapahoe 28-J", "Adams Arapahoe School District 28J"),
        ("Grandview C-IV Schools", "GRANDVIEW C-4"),
        ("Hydro-Eakly Schools", "HYDRO-EAKLY"),
    ],
)
def test_district_spellings_meet(listing: str, directory: str) -> None:
    assert _district(listing) == _key(record_form(directory, district=True))


@pytest.mark.parametrize(
    ("listing", "directory"),
    [
        ("St. Mary's Elem.", "ST MARYS ELEMENTARY SCHOOL"),
        ("Saint Mary Elementary", "St. Mary's Elementary School"),
        ("St. Francis School", "ST. FRANCIS'S SCHOOL"),
        ("Sts. Peter & Paul School", "St. Peter and Paul School"),
        ("Grace Park Elementary", "Grace Park El Sch"),
        ("Cinco Ranch High School", "CINCO RANCH H S"),
        ("Cinco Ranch HS", "CINCO RANCH H S"),
        ("Cinco Ranch H.S.", "Cinco Ranch High School"),
        ("Bonham Elementary", "BONHAM EL"),
        ("Riverside Junior High", "RIVERSIDE J H"),
        ("Riverside Jr. High School", "RIVERSIDE JHS"),
        ("Lincoln Senior High", "Lincoln High School"),
        ("Lincoln Sr. High School", "LINCOLN SHS"),
        ("Lincoln Jr/Sr High", "Lincoln Junior-Senior High School"),
        ("Hillcrest Intermediate", "HILLCREST INT"),
        ("Hillcrest Primary", "HILLCREST PRI"),
        ("Main St. Elementary", "Main Street Elementary School"),
        ("Elm St H S", "Elm Street High School"),
        ("Union St. JHS", "Union Street Junior High"),
        ("Oak Ridge Elementary", "Oakridge El Sch"),
        ("Arts & Sciences Academy", "Arts and Sciences Academy"),
        ("Academia Senora del Valle", "Academia Señora del Valle"),
        ("MONTRÉAL ACADÉMIE", "Montreal Academie"),
        ("Martin Luther King Jr. Elementary", "Martin Luther King Jr Elementary School"),
        ("MLK Elementary", "Martin Luther King Elementary School"),
        ("Children's Academy", "CHILDRENS ACADEMY"),
        ("Pre-K Center", "PreK Center"),
        ("Ft. Hill Middle", "Fort Hill Middle School"),
        ("Baden Academy Charter School", "Baden Academy CS"),
        ("Lincoln K-8 School", "Lincoln K8 School"),
        ("Orvell High School of Keston", "ORVELL H S OF KESTON"),
        ("Orvell High School Brantley", "ORVELL H S - BRANTLEY"),
        ("Orvell High School at Dalby", "ORVELL H S AT DALBY"),
        ("Orvell High School for the Arts", "ORVELL H S FOR THE ARTS"),
    ],
)
def test_school_spellings_meet(listing: str, directory: str) -> None:
    assert _school(listing) == _key(record_form(directory, district=False))


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("Lincoln Elementary", "Lincoln Middle"),
        ("Washington Junior High", "Washington High"),
        ("St. Mary's", "St. Paul's"),
        ("Main St. Elementary", "Main Saint Elementary"),
        ("El Paso ISD", "Elementary Paso ISD"),
        ("Oakwood R-2", "Oakwood R-3"),
        ("Lancaster County Schools", "Lancaster Schools"),
        ("Lancaster City Schools", "Lancaster County Schools"),
        ("Kettleby Local Schools", "Kettleby City Schools"),
        ("Martin Luther King Jr High School", "Martin Luther King Junior High School"),
        ("Martin Luther King Jr High School", "Martin Luther King Jr. Jr. High"),
    ],
)
def test_different_names_stay_apart(one: str, other: str) -> None:
    assert _school(one) != _school(other)


def test_st_is_saint_before_a_name_and_street_after_one() -> None:
    assert listing_forms("St. Charles").school.tokens == ("saint", "charle")
    assert listing_forms("Main St.").school.tokens == ("main", "street")
    assert listing_forms("Main St Charter School").school.tokens == ("main", "street", "charter")
    assert listing_forms("Ste. Genevieve").school.tokens == ("sainte", "genevieve")
    assert listing_forms("St Intermed.").school.tokens == ("street",)


def test_el_is_elementary_only_where_nces_uses_it() -> None:
    assert listing_forms("El Campo ISD").district.tokens == ("el", "campo")
    assert listing_forms("Bonham El").school.levels == {"elementary"}
    assert listing_forms("Grace Park El Sch").school.levels == {"elementary"}
    assert listing_forms("El").school.tokens == ("el",)


def test_king_jr_high_is_a_high_school() -> None:
    assert listing_forms("Martin Luther King Jr High School").school.levels == {"high"}
    assert listing_forms("Martin Luther King Jr. Junior High").school.levels == {"juniorhigh"}


def test_district_legal_form_words_stay_on_schools() -> None:
    assert record_form("Waunakee Community School District", district=True).tokens == ("waunakee",)
    assert record_form("Waunakee Community School", district=False).tokens == (
        "waunakee",
        "community",
    )
    assert record_form("Central SD", district=True).tokens == ("central",)


@pytest.mark.parametrize(
    ("text", "hint"),
    [
        ("Albertville City Schools", Level.DISTRICT),
        ("Houston ISD", Level.DISTRICT),
        ("Genesee School System", Level.DISTRICT),
        ("Caddo Parish School Board", Level.DISTRICT),
        ("School District of Lancaster", Level.DISTRICT),
        ("Lincoln Elementary", Level.SCHOOL),
        ("St. Mary's School", Level.SCHOOL),
        ("Kipp Academy", Level.SCHOOL),
        ("Baden Charter", Level.SCHOOL),
        ("Albertville", Level.UNKNOWN),
        ("St. Mary's", Level.UNKNOWN),
        ("Wentzville R-IV", Level.UNKNOWN),
    ],
)
def test_level_hint(text: str, hint: Level) -> None:
    assert listing_forms(text).hint is hint


def test_all_schools_settles_a_bare_name_but_not_a_school() -> None:
    assert listing_forms("Albertville", district_hint=True).hint is Level.DISTRICT
    assert listing_forms("Lincoln Elementary", district_hint=True).hint is Level.SCHOOL


def test_numbers() -> None:
    assert listing_forms("District 007").district.numbers == {"7"}
    assert listing_forms("Adams 12 Five Star Schools").district.numbers == {"12"}
    assert listing_forms("Weld RE-1").district.numbers == {"1"}
    assert listing_forms("Weld RE-1").district.tokens == ("weld",)
    assert listing_forms("Lincoln School 5").school.numbers == {"5"}
    assert listing_forms("Class V Academy").school.numbers == {"5"}
    assert listing_forms("Louis V Academy").school.numbers == frozenset()
    assert listing_forms("Louis V Academy").school.tokens == ("loui", "v", "academy")


def test_fold_and_roman_value() -> None:
    assert fold("\u00c9COLE \u00d1and\u00fa\u2019s") == "ecole nandu's"
    assert roman_value("iv") == 4
    assert roman_value("xxxix") == 39
    assert roman_value("ix") == 9
    assert roman_value("mix") is None
    assert roman_value("") is None
    assert roman_value("iiii") is None


def test_empty_forms() -> None:
    assert listing_forms("Schools").is_empty
    assert listing_forms("School District").is_empty
    assert not listing_forms("District 5").is_empty
    assert not listing_forms("Central SD").is_empty


@pytest.mark.parametrize(
    ("raw", "text", "segments", "all_schools"),
    [
        ("Lincoln Elementary (Closed)", "Lincoln Elementary", ("Lincoln Elementary",), False),
        ("Lincoln Elementary [2 hr delay]", "Lincoln Elementary", ("Lincoln Elementary",), False),
        (
            "Albertville City Schools - All Schools",
            "Albertville City Schools",
            ("Albertville City Schools",),
            True,
        ),
        ("Albertville City Schools, all locations", "Albertville City Schools", None, True),
        ("Madison County Schools and All Schools", "Madison County Schools", None, True),
        ("Kettering City Schools -- Closed", "Kettering City Schools", None, False),
        ("Kettering City Schools: Remote Learning Day", "Kettering City Schools", None, False),
        ("Lincoln School - Early Dismissal at 12:30 PM", "Lincoln School", None, False),
        ("Lincoln School: dismissing at noon", "Lincoln School", None, False),
        ("Lincoln School - Two Hour Delay", "Lincoln School", None, False),
        (
            "St. Mary's School (Springfield) - 2 Hour Delay",
            "St. Mary's School Springfield",
            ("St. Mary's School", "Springfield"),
            False,
        ),
        (
            "Springfield - Virtual Academy",
            "Springfield Virtual Academy",
            ("Springfield", "Virtual Academy"),
            False,
        ),
        ("Early Childhood Center", "Early Childhood Center", ("Early Childhood Center",), False),
        ("Hall-Woodward Elementary", "Hall-Woodward Elementary", None, False),
        ("Wentzville R-IV", "Wentzville R-IV", None, False),
        ("  Lincoln   Elementary  ", "Lincoln Elementary", None, False),
        ("Schools", "", (), False),
        ("(Closed)", "", (), False),
        ("All Schools", "", (), True),
    ],
)
def test_clean_listing(
    raw: str, text: str, segments: tuple[str, ...] | None, all_schools: bool
) -> None:
    clean = clean_listing(raw)
    assert clean.text == text
    if segments is not None:
        assert clean.segments == segments
    assert clean.all_schools is all_schools


@pytest.mark.parametrize(
    ("listing", "directory"),
    [
        ("Madison County Bd. of Ed.", "Madison County Board of Education"),
        ("5th Street Elementary", "5th St. Elementary School"),
        ("Riverside J H S", "Riverside Junior High School"),
        ("Riverside Jr. Hi", "Riverside Junior High"),
        ("Central Sr", "Central High"),
        ("Pre School Center", "Preschool Center"),
        ("Valley Co-op School", "Valley Co Op School"),
        ("Lincoln Consolidated School No. 2", "LINCOLN CONSOLIDATED SCHOOL #2"),
        ("The Linder Academy", "Linder Academy (The)"),
    ],
)
def test_more_spellings_meet(listing: str, directory: str) -> None:
    assert _school(listing) == _key(record_form(directory, district=False))


def test_co_op_is_cooperative_not_a_county() -> None:
    form = listing_forms("Valley Co-op School").school
    assert form.qualifiers == frozenset({"cooperative"})
    assert form.tokens == ("valley",)
    assert listing_forms("Valley Coop. School").school == form
    # New Hampshire's cooperative school districts: a legal form a list may leave out.
    district = record_form("Oyster Brook Coop School District", district=True)
    assert district.tokens == ("oyster", "brook")
    assert district.qualifiers == frozenset({"cooperative"})
    assert listing_forms("Oyster Brook Cooperative School District").district == district._replace(
        hint=listing_forms("Oyster Brook Cooperative School District").district.hint
    )
    # A cooperative that is the name's only word names it.
    alone = record_form("Cooperative Middle School", district=False)
    assert alone.tokens == ("cooperative",)
    assert alone.levels == frozenset({"middle"})


@pytest.mark.parametrize(
    ("nces", "listing"),
    [
        ("North Harrisby Com School Corp", "North Harrisby Community Schools"),
        ("South Ripton Com Sch Corp", "South Ripton Community School Corporation"),
        ("Centerby-Abington Com Schs", "Centerby-Abington Community Schools"),
        ("Rising Sunby-Ohio Co Com", "Rising Sunby-Ohio County Community Schools"),
        ("Bartley Con School Corp", "Bartley Consolidated School Corp"),
        ("Southwestern-Jeffery Co Con", "Southwestern-Jeffery County Consolidated"),
        ("Rossby Con School District", "Rossby Cons. School District"),
        ("Brownsby Cnt Com Sch Corp", "Brownsby Central Community School Corporation"),
        ("Huntley Co Com Sch Corp", "Huntley County Community Schools"),
        ("Washby ISD", "Washby Intermediate School District"),
        ("Washby ISD", "Washby Int School District"),
        ("Washby ISD", "Washby Intermediate SD"),
        ("Washby ISD", "Washby Intermediate District"),
        ("EAGLEBY MT-SAGINOW ISD", "Eagleby Mountain Saginow ISD"),
        ("EAGLEBY MT-SAGINOW ISD", "Eagleby Mountain-Saginow Independent School District"),
    ],
)
def test_nces_district_habits_read_both_ways(nces: str, listing: str) -> None:
    record = record_form(nces, district=True)
    read = listing_forms(listing).district
    assert read.tokens == record.tokens, (nces, listing)
    assert read.qualifiers == record.qualifiers
    assert read.levels == record.levels


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        # Mt is Mount before a name ...
        ("Mt. Pleasant High", ("mount", "pleasant")),
        ("Our Lady of Mt Carmel School", ("our", "lady", "of", "mount", "carmel")),
        ("Winfieldby-Mt Union Jr-Sr High School", ("winfieldby", "mount", "union")),
        ("Ludby Mt. Holly School", ("ludby", "mount", "holly")),
        # ... and Mountain where a name ends with it.
        ("BLUE MT CHRISTIAN SCHOOL", ("blue", "mountain", "christian")),
        ("SHADE MT MENNONITE", ("shade", "mountain", "mennonite")),
        ("Monumentby Mt Regional High", ("monumentby", "mountain")),
        ("Rocky Mt", ("rocky", "mountain")),
        ("EAGLEBY MT-SAGINOW HIGH SCHOOL", ("eagleby", "mountain", "saginow")),
        # Indiana's Con and Cnt only where they are Consolidated and Central.
        ("Con Amore School", ("con", "amore")),
        (
            "Pontoby Ridge Career & Tech. Cnt.",
            ("pontoby", "ridge", "career", "and", "tech", "center"),
        ),
        ("Lee A. Tolby Com. Academy", ("lee", "a", "tolby", "community", "academy")),
    ],
)
def test_abbreviations_read_by_context(name: str, tokens: tuple[str, ...]) -> None:
    assert record_form(name, district=False).tokens == tokens


def test_an_intermediate_school_district_is_an_isd_only_after_a_name() -> None:
    # Minnesota's "Intermediate School District 287" is no ISD 287.
    form = record_form("Intermediate School District 287", district=True)
    assert form.levels == frozenset({"intermediate"})
    # A school's level stays one.
    school = listing_forms("Washby Intermediate School")
    assert school.hint is Level.SCHOOL
    assert school.school.levels == frozenset({"intermediate"})


def test_an_independent_school_is_one_school() -> None:
    forms = listing_forms("The Stonby Independent School")
    assert forms.hint is Level.SCHOOL
    assert forms.school.tokens == ("stonby", "independent")
    assert listing_forms("Beechby Independent Schools").hint is Level.DISTRICT
    assert listing_forms("Saltby Independent School District").hint is Level.DISTRICT


def test_a_qualifier_that_begins_a_name_is_noted() -> None:
    assert listing_forms("City University Schools").district.qualifier_first
    assert not listing_forms("Murrowby City Schools").district.qualifier_first
    # A qualifier alone, with a number, stays a qualifier.
    numbered = record_form("Township High School District 214", district=True)
    assert numbered.tokens == ()
    assert numbered.qualifiers == frozenset({"township"})


def test_caches_can_be_cleared() -> None:
    first = listing_forms("Lincoln Elementary")
    record_form("Lincoln Elementary", district=False)
    clear_caches()
    assert listing_forms("Lincoln Elementary") == first


# -- affiliations -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "affiliations"),
    [
        ("Omaha Catholic Schools", {"catholic"}),
        ("St. Mary's Catholic School", {"catholic"}),
        ("Grand Rapids Christian Schools", {"christian"}),
        ("York Adventist Christian School", {"adventist", "christian"}),
        ("Springfield SDA School", {"adventist"}),
        ("St. John Luth. School", {"lutheran"}),
        ("Lancaster Mennonite School", {"mennonite"}),
        ("Denver Jewish Day School", {"jewish"}),
        ("Minneapolis Islamic School", {"islamic"}),
        ("Archdiocese of Chicago Schools", {"archdiocese"}),
        ("Montessori Academy of Lancaster", {"montessori"}),
        ("Christian County", set()),
        ("Christian Co. Public Schools", set()),
        ("St. John the Baptist Parish", set()),
        ("St. John the Baptist School", set()),
        ("First Baptist Academy", {"baptist"}),
        ("Lancaster SD", set()),
        ("St. Mary's School", set()),
    ],
)
def test_affiliations(name: str, affiliations: set[str]) -> None:
    assert listing_forms(name).school.affiliations == affiliations
    assert record_form(name, district=False).affiliations == affiliations


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("St. John the Baptist School", ("saint", "john", "thebaptist")),
        (
            "ST JOHN BAPTIST DE LA SALLE SCHOOL",
            ("saint", "john", "thebaptist", "de", "la", "salle"),
        ),
        ("First Baptist Academy", ("first", "baptist", "academy")),
        ("St. John School", ("saint", "john")),
    ],
)
def test_a_saint_s_epithet_is_a_name_s_word(name: str, tokens: tuple[str, ...]) -> None:
    """``Baptist`` after ``John`` is the saint's, weighing as a name's word, not a faith."""
    for form in (listing_forms(name).school, record_form(name, district=False)):
        assert form.tokens == tokens


@pytest.mark.parametrize(
    ("name", "tokens", "devoted"),
    [
        ("ST JOHN XXIII CATHOLIC SCHOOL", ("saint", "john", "xxiii", "catholic"), True),
        ("PAUL VI CATHOLIC HIGH SCHOOL", ("paul", "vi", "catholic"), True),
        ("Pope John Paul II High School", ("pope", "john", "paul", "ii"), True),
        ("ST PIUS X SCHOOL", ("saint", "piu", "x"), True),
        ("Pope Pius X High School", ("pope", "piu", "x"), True),
        ("John V Lindsay Elementary", ("john", "v", "lindsay"), False),
        ("Leo High School", ("leo",), False),
    ],
)
def test_a_pope_s_numeral_is_his_name_s(name: str, tokens: tuple[str, ...], devoted: bool) -> None:
    """``"St. John XXIII"`` is named for a pope, not numbered; his school is a parish's."""
    for form in (listing_forms(name).school, record_form(name, district=False)):
        assert form.tokens == tokens
        assert form.numbers == frozenset()
        assert form.devoted is devoted
    # A numeral after anything else is still a number.
    assert record_form("Kansas City R-II", district=True).numbers == {"2"}
    assert record_form("District XII", district=True).numbers == {"12"}


def test_affiliations_of_reads_places_and_saints() -> None:
    assert affiliations_of(["christian", "county"]) == frozenset()
    assert affiliations_of(["pass", "christian"]) == {"christian"}
    assert affiliations_of(["saint", "john", "baptist"]) == frozenset()
    assert affiliations_of(["baptist"]) == {"baptist"}
    assert affiliations_of([]) == frozenset()


@pytest.mark.parametrize(
    ("text", "hint", "system"),
    [
        ("Omaha Catholic Schools", Level.UNKNOWN, True),
        ("Grand Rapids Christian School System", Level.UNKNOWN, True),
        ("Omaha Catholic", Level.UNKNOWN, False),
        ("Omaha Catholic High Schools", Level.SCHOOL, False),
        ("Lancaster Catholic High School", Level.SCHOOL, False),
        ("Pass Christian School District", Level.DISTRICT, False),
        ("Pass Christian Public Schools", Level.DISTRICT, False),
        ("Christian County Schools", Level.DISTRICT, False),
        ("Omaha Public Schools", Level.DISTRICT, False),
    ],
)
def test_an_affiliation_is_no_public_district(text: str, hint: Level, system: bool) -> None:
    forms = listing_forms(text)
    assert forms.hint is hint
    assert forms.school.system is system
    assert forms.district.system is system


def test_all_schools_makes_a_group_of_an_affiliated_name() -> None:
    forms = listing_forms("Omaha Catholic", district_hint=True)
    assert forms.hint is Level.UNKNOWN
    assert forms.school.system


# -- colleges and universities -------------------------------------------------------


@pytest.mark.parametrize(
    ("listing", "word"),
    [
        ("Boston College", "college"),
        ("Boston University", "university"),
        ("University of Denver", "university"),
        ("College of Charleston", "college"),
        ("Harrisburg Area Community College", "college"),
        ("Wichita State University", "university"),
        ("Denver Seminary", "seminary"),
        ("Boston Univ.", "university"),
        ("Boston College (Closed)", "college"),
        ("Boston College - Chestnut Hill", "college"),
        ("Maricopa County Community College District", "college"),
        ("Dallas College - All Campuses", "college"),
        ("Dallas College closed today", "college"),
    ],
)
def test_colleges_are_not_k12(listing: str, word: str) -> None:
    assert non_k12(clean_listing(listing)) == word


@pytest.mark.parametrize(
    "listing",
    [
        "Boston College High School",
        "Boston College High",
        "Boston College HS",
        "Boston University Academy",
        "University Preparatory Academy",
        "University of Nebraska High School",
        "Lab School - Boston University",
        "Northeast Early College",
        "Clackamas Middle College",
        "Gateway to College",
        "College Park Elementary",
        "College Station ISD",
        "University Heights City Schools",
        "University City",
        "Lincoln Elementary - University Heights",
        "Collegiate Academy",
        "Wichita Collegiate",
        "Lancaster SD",
        "",
    ],
)
def test_k12_names_are_not_colleges(listing: str) -> None:
    assert non_k12(clean_listing(listing)) is None


# -- civic bodies ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("listing", "what", "may_be_a_place"),
    [
        ("City of Monessen", "city of", False),
        ("City Of Monessen", "city of", False),
        ("City of Central City", "city of", False),
        ("CITY OF AKRON (Closed)", "city of", False),
        ("City of Baltimore - Offices Closed", "city of", False),
        ("Village of Oak Park", "village of", False),
        ("Town of Webb", "town of", False),
        ("Borough of Elkland", "borough of", False),
        ("Twp. of Ocean", "township of", False),
        ("County of Washtenaw", "county of", False),
        ("Monessen City Hall", "city hall", True),
        ("Foley City Council", "city council", True),
        ("Orange Beach City Offices", "city offices", True),
        ("Cass County Council on Aging", "county council", True),
        ("Harlowe Town Clerk", "town clerk", True),
        ("Lake County Government Center", "county government", True),
        ("Sabine Pass Senior Center", "senior center", True),
        ("Valley Senior Ctr of Ligonier", "senior center", True),
        ("Farrowdale Sr. Citizens Center", "senior citizens", True),
        ("Woodville Community Center - Closed", "community center", True),
        ("Ligonier Valley Meals on Wheels", "meals on wheels", True),
        ("Ashfield Public Library", "library", True),
        ("Ashfield YMCA", "ymca", True),
        ("Ashfield Parks & Recreation", "recreation", True),
        ("North Fond du Lac Hospital", "hospital", True),
        ("North Fond du Lac Water Department", "department", True),
        ("Ashfield Police Dept.", "police", True),
        ("Ashfield Volunteer Fire Dept", "volunteer fire", True),
        ("Ashfield Fire Company No. 1", "fire company", True),
        ("Chico 4-H", "4 h", True),
        ("Chico 4H Club - Meeting Cancelled", "4h", True),
        ("Boy Scouts Troop 12", "scouts", True),
        ("Ashfield Little League", "little league", True),
        ("Roselle Park District", "park district", True),
        ("Prince William County Parks", "county parks", True),
        ("Polk County Board of Supervisors", "county board", True),
        ("Polk County Fair", "county fair", True),
        ("Leon County Jail", "county jail", True),
        ("Ashfield Housing Authority", "authority", True),
        ("Ashfield Medical Center", "medical center", True),
        ("First Baptist Church of Marion", "church", True),
        ("Farrowdale United Methodist Church", "church", True),
        ("Grace Church closed today", "church", True),
        ("First Baptist Church Daycare", "church", True),
        ("Church on the Rock", "church", True),
        ("United Church of Christ - Central City", "church", True),
        ("Ashfield Assembly of God", "assembly of god", True),
        ("Falls Church", "church", True),
        # A church's Mass, classes and places of worship; a court.
        ("St. Peter's Parish: No Mass", "no mass", True),
        ("Holy Name Parish - No Masses", "masses", True),
        ("St. Elizabeth Parish: Mass canceled", "mass canceled", True),
        ("Christ the King Sunday School", "sunday school", True),
        ("Vacation Bible School", "vacation bible school", True),
        ("Ascension Religious Education", "religious education", True),
        ("Our Lady of Sorrows Faith Formation", "faith formation", True),
        ("St. Peter's Bible Study", "bible study", True),
        ("Bethel Chapel", "chapel", True),
        ("Cathedral of the Incarnation", "cathedral", True),
        ("Basilica of St. Mary", "basilica", True),
        ("Grace Worship Center", "worship", True),
        ("Hertby Co NC District Court", "district court", True),
        ("Bristol VA General District Court", "district court", True),
    ],
)
def test_civic_bodies_are_not_schools(listing: str, what: str, *, may_be_a_place: bool) -> None:
    civic = not_school(clean_listing(listing))
    assert civic is not None
    assert civic.what == what
    assert civic.may_be_a_place is may_be_a_place


@pytest.mark.parametrize(
    "listing",
    [
        "City of Chicago SD 299",
        "City of Marlowe School District",
        "Township of Ocean School District",
        "Town of Webb UFSD",
        "Los Angeles County Office of Education",
        "Harwick County Board of Education",
        "Harwick County BOE",
        "Polk County School Board",
        "Parks Elementary",
        "Rosa Parks",
        "County Line",
        "Harwick County",
        "Lincoln Elementary - City of Kettleby",
        "Kettleby City Schools - City Hall Closed",
        "St. Mary's Church and School",
        "Hospital Street Elementary",
        "Monessen City SD",
        "Central City",
        "Kettleby City",
        "Oak Park",
        "P.S. 124 Osmond A. Church",
        "Mary Church Terrell",
        "Church Point",
        "Shelter Island",
        "Shelter Cove",
        "Fire Island UFSD",
        "Fire Island",
        "Fire Ridge",
        "District 4 H.S.",
        "St. John the Baptist Parish Schools",
        "Athens Bible School",
        "Mt. Zion Bible School",
        "Christ the King Parish School",
        "Christian County",
        "Chapel Hill",
        "Cathedral City",
        "Cathedral High School",
        "Salem, Mass.",
        "Senior High",
        "Waconia Learning Center",
        "Heart Prints Center for Early Education",
        "",
    ],
)
def test_schools_and_places_are_not_civic_bodies(listing: str) -> None:
    assert not_school(clean_listing(listing)) is None


@pytest.mark.parametrize(
    ("listing", "louisiana"),
    [
        # A saint's parish, or a Louisiana parish: the directory tells them apart.
        ("Christ the King Parish", True),
        ("Visitation Parish", True),
        ("Acadia Parish", True),
        ("St. Mary Parish", True),
        # A saint's parish in the possessive is a church outright.
        ("St. Peter's Parish", False),
        ("Most Precious Blood's Parish - Dover", False),
    ],
)
def test_a_parish_is_a_church_or_a_louisiana_county(listing: str, *, louisiana: bool) -> None:
    civic = not_school(clean_listing(listing))
    assert civic is not None
    assert civic.what == "parish"
    assert civic.parish is louisiana
    assert not civic.may_be_a_place


@pytest.mark.parametrize(
    ("category", "section"),
    [
        (None, Section.UNKNOWN),
        ("", Section.UNKNOWN),
        ("Schools", Section.SCHOOLS),
        ("School", Section.SCHOOLS),
        ("Public Schools", Section.SCHOOLS),
        ("RI Catholic Schools", Section.SCHOOLS),
        ("Parochial School", Section.SCHOOLS),
        ("School District", Section.SCHOOLS),
        ("Church", Section.OTHER),
        ("03Church", Section.OTHER),
        ("Churches", Section.OTHER),
        ("Business", Section.OTHER),
        ("Business-IN", Section.OTHER),
        ("Gov&apos;t.", Section.OTHER),
        ("Civic", Section.OTHER),
        ("Daycare", Section.OTHER),
        ("PreSkl.", Section.OTHER),
        ("Pre-Schools/Daycare", Section.OTHER),
        ("Childcare/Preschool", Section.OTHER),
        ("Day Care", Section.OTHER),
        ("Commun./Relig./Day-Sr. Care", Section.UNKNOWN),
        ("Religious", Section.UNKNOWN),
        ("KY Private", Section.SCHOOLS),
        ("Private & Charter Schools - Portland area", Section.SCHOOLS),
        ("Colleges & Universities - Private", Section.UNKNOWN),
        ("Worship", Section.OTHER),
        ("Colleges", Section.OTHER),
        ("Business/Government/Other", Section.OTHER),
        ("School/College", Section.UNKNOWN),
        ("Closings", Section.UNKNOWN),
        ("Other", Section.UNKNOWN),
        ("noneselected", Section.UNKNOWN),
        ("FRANKLIN", Section.UNKNOWN),
    ],
)
def test_a_lists_section_says_what_its_listings_are(category: str | None, section: Section) -> None:
    assert listing_section(category) is section


@pytest.mark.parametrize(
    ("listing", "said"),
    [
        ("St. Peter's", "saint"),
        ("Christ the King", "christ"),
        ("Visitation", "visitation"),
        ("Our Lady of Unity", "lady"),
        ("Good Shepherd", "shepherd"),
        ("Holy Spirit Lee's Summit", "holy"),
        ("St. Peter's - Kansas City", "saint"),
        ("St. Peter's Catholic", "saint"),
        ("Trinity Lutheran", "trinity lutheran"),
        ("Grace Baptist", "baptist"),
        ("Immanuel Lutheran - Crystal Lake", "lutheran"),
        ("Southfield Christian", None),
        ("Lowell Catholic", None),
        # A school's word, or no church at all.
        ("St. Peter's School", None),
        ("Visitation Catholic School", None),
        ("St. Pius X High", None),
        ("St. Teresa's Academy", None),
        ("Lincoln", None),
        ("Ashfield Montessori", None),
    ],
)
def test_a_church_is_named_by_its_devotion_or_its_faith(listing: str, said: str | None) -> None:
    assert church_name(clean_listing(listing)) == said


@pytest.mark.parametrize(
    ("listing", "segments"),
    [
        ("Sacred Heart School-Troy", ("Sacred Heart School", "Troy")),
        ("Southeast Local SD-Ravenna", ("Southeast Local SD", "Ravenna")),
        ("Central School District 104-O'Fallon", ("Central School District 104", "O'Fallon")),
        ("Cody Kilgore Unified Schools-Cody, NE", ("Cody Kilgore Unified Schools", "Cody", "NE")),
        ("Lincoln Elem-Springfield", ("Lincoln Elem", "Springfield")),
        # A hyphen inside a name, before a level or a noun, or before a letter.
        ("Lincoln Elementary-Middle School", ("Lincoln Elementary-Middle School",)),
        ("Winston-Salem Forsyth", ("Winston-Salem Forsyth",)),
        ("Holden R-III", ("Holden R-III",)),
        ("Brambleton County 4-H", ("Brambleton County 4-H",)),
        ("Menominee public-private", ("Menominee public-private",)),
        ("Pre-K Center", ("Pre-K Center",)),
        ("Lincoln School-All", ("Lincoln School-All",)),
    ],
)
def test_a_town_joined_by_a_hyphen_is_a_part_of_its_own(
    listing: str, segments: tuple[str, ...]
) -> None:
    assert clean_listing(listing).segments == segments


@pytest.mark.parametrize(
    ("text", "bare"),
    [
        ("Falls Church", True),
        ("Falls Church City", True),
        ("State College", True),
        ("Roselle Park", True),
        ("Roselle Park District", False),
        ("Roselle Parks Department", False),
        ("Lancaster Schools", False),
        ("School District of Lancaster", False),
        ("Wentzville R-4", False),
        ("Public Schools of Robeson County", False),
    ],
)
def test_is_bare_name(text: str, *, bare: bool) -> None:
    assert is_bare_name(text) is bare


# -- numbers and Colorado's legal names ------------------------------------------------


@pytest.mark.parametrize(
    ("name", "tokens", "numbers"),
    [
        ("St. Vrain Valley School District No. Re1J", ("saint", "vrain", "valley"), {"1j"}),
        ("St. Vrain Valley RE-1J", ("saint", "vrain", "valley"), {"1j"}),
        ("Calhan District No. RJ1", ("calhan",), {"1"}),
        ("Buena Vista School District No. R-31", ("buena", "vista"), {"31"}),
        ("Crowley County School District No. Re-1-J", ("crowley",), {"1j"}),
        ("Center Consolidated School District No. 26 Jt. of the count", ("center",), {"26"}),
        ("Cherry Creek School District No. 5 in the county of Arapah", ("cherry", "creek"), {"5"}),
        ("Aurora Joint District No. 28 of the counties of Adams and A", ("aurora",), {"28"}),
        ("Mapleton School District No. 1 in the county of Adams & St", ("mapleton",), {"1"}),
        ("Douglas County School District No. Re 1", ("dougla",), {"1"}),
        ("Limon School District No. Re 4J", ("limon",), {"4j"}),
    ],
)
def test_colorado_numbered_names(name: str, tokens: tuple[str, ...], numbers: set[str]) -> None:
    form = record_form(name, district=True)
    assert form.tokens == tokens
    assert form.numbers == numbers
    assert form.implied == frozenset()


def test_a_district_named_only_by_its_county_implies_county() -> None:
    form = record_form(
        "School District No. 1 in the county of Denver and State of C", district=True
    )
    assert form.tokens == ("denver",)
    assert form.numbers == {"1"}
    assert form.implied == {"county"}
    assert form.qualifiers == frozenset()
    weld = record_form("School District No. Re-10 in the county of Weld and State o", district=True)
    assert weld.tokens == ("weld",)
    assert weld.numbers == {"10"}
    assert weld.implied == {"county"}
    adams = record_form(
        "School District N. 14 in the county of Adams & State of Colo", district=True
    )
    assert adams.tokens == ("adam",)
    assert adams.numbers == {"14"}
    assert adams.implied == {"county"}


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("Hamlow School District of the City of", ("hamlow",)),
        ("Muskwood Public Schools of the City of", ("muskwood",)),
        ("Harlow Woods The School District of the City of", ("harlow", "wood")),
    ],
)
def test_michigan_city_districts_imply_city(name: str, tokens: tuple[str, ...]) -> None:
    form = record_form(name, district=True)
    assert form.tokens == tokens
    assert form.implied == {"city"}
    assert form.qualifiers == frozenset()
    # "City of" at the front is a government's name, and stays as it was.
    assert record_form("City of Chicago SD 299", district=True).implied == frozenset()
    # Nothing before it: the words stay.
    assert record_form("of the City of", district=True).implied == frozenset()


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("Clarksvale Municipal School District", ("clarksvale",)),
        ("Clevemoor Municipal", ("clevemoor",)),
        ("Millbrook Municipal Schools", ("millbrook",)),
    ],
)
def test_municipal_is_a_legal_form(name: str, tokens: tuple[str, ...]) -> None:
    assert record_form(name, district=True).tokens == tokens
    # "Clevemoor Metropolitan School District" is how a closings list names it.
    assert listing_forms("Clevemoor Metropolitan School District").district.tokens == ("clevemoor",)
    # A school keeps the word.
    assert "municipal" in record_form("Municipal Stadium School", district=False).tokens


def test_n_dot_is_a_number_mark_only_before_a_number() -> None:
    assert listing_forms("N. 5th Street Elementary").school.numbers == {"5th"}
    assert listing_forms("District N. 14").district.numbers == {"14"}
    assert listing_forms("Noble Academy 2").school.tokens == ("noble", "academy")


@pytest.mark.parametrize(
    ("text", "tokens", "codes", "district_numbers", "hint"),
    [
        ("USD 320 Wamego", ("wamego",), set(), {"320"}, Level.DISTRICT),
        ("U.S.D. #320 - Wamego", ("wamego",), set(), {"320"}, Level.DISTRICT),
        ("Wamego USD 320", ("wamego",), set(), {"320"}, Level.DISTRICT),
        ("RSU 19", (), {"rsu 19"}, set(), Level.DISTRICT),
        ("RSU13", (), {"rsu 13"}, set(), Level.DISTRICT),
        ("Regional School Unit 13", (), {"rsu 13"}, set(), Level.DISTRICT),
        ("M.S.A.D. #17", (), {"sad 17"}, set(), Level.DISTRICT),
        ("Maine School Administrative District 17", (), {"sad 17"}, set(), Level.DISTRICT),
        ("SAD 4 / RSU 80", (), {"sad 4", "rsu 80"}, set(), Level.DISTRICT),
        ("MSAD 17 - Oxford Hills", ("oxford", "hill"), {"sad 17"}, set(), Level.DISTRICT),
        ("RSU 13 Oceanside High School", ("oceanside",), {"rsu 13"}, set(), Level.SCHOOL),
        ("AOS 98 Edgecomb Eddy School", ("edgecomb", "eddy"), {"aos 98"}, set(), Level.SCHOOL),
        ("SAU #16 Exeter", ("exeter",), {"sau 16"}, set(), Level.DISTRICT),
        ("D-3 Widefield", ("widefield",), set(), {"3"}, Level.DISTRICT),
        ("RE-2 Woodland Pk", ("woodland", "park"), set(), {"2"}, Level.DISTRICT),
        ("CUSD 300 Hampshire", ("hampshire",), set(), {"300"}, Level.DISTRICT),
        ("School District 5 Lincoln Elementary", ("lincoln",), set(), {"5"}, Level.SCHOOL),
        ("Canon City RE-1", ("canon",), set(), {"1"}, Level.UNKNOWN),
    ],
)
def test_district_codes(
    text: str, tokens: tuple[str, ...], codes: set[str], district_numbers: set[str], hint: Level
) -> None:
    """A district code names a district, at the start as at the end."""
    forms = listing_forms(clean_listing(text).text)
    form = forms.district if hint is not Level.SCHOOL else forms.school
    assert form.tokens == tokens
    assert form.codes == codes
    assert form.district_numbers == district_numbers
    assert forms.hint is hint


@pytest.mark.parametrize(
    "text", ["High School 5", "P.S. 5 Port Morris", "School 12", "Lincoln Elementary No. 2"]
)
def test_school_numbers_are_no_district_codes(text: str) -> None:
    form = listing_forms(text).school
    assert not form.codes
    assert not form.district_numbers
    assert form.numbers


def test_a_leading_code_reads_like_a_trailing_one() -> None:
    assert _district("USD 320 Wamego") == _district("Wamego USD 320")
    assert _district("RSU 13 Oceanside") == _district("Oceanside RSU 13")


def test_district_code_records() -> None:
    both = record_form("RSU 83/MSAD 13", district=True)
    assert both.codes == {"rsu 83", "sad 13"}
    assert both.numbers == {"83", "13"}
    assert not both.tokens
    assert both.context_numbers == {"83", "13"}
    named = record_form("RSU 01 - LKRSU", district=True)
    assert named.codes == {"rsu 1"}
    assert named.tokens == ("lkrsu",)
    # Colorado's legal names: the number follows "District".
    legal = record_form(
        "School District No. 3 in the county of El Paso and State of", district=True
    )
    assert legal.district_numbers == {"3"}
    assert "county" in legal.implied
    plain = record_form("Lincoln Elementary School", district=False)
    assert plain.context_numbers == frozenset()


def test_district_codes_keep_the_numbers_in_the_words() -> None:
    found = district_codes(["regional", "school", "unit", "13", "oceanside"])
    assert found.words == ["13", "oceanside"]
    assert found.codes == {"rsu 13"}
    assert found.coded
    found = district_codes(["unified", "school", "district", "320", "wamego"])
    assert found.words == ["320", "wamego"]
    assert found.numbers == {"320"}
    # Not at the start: the designator stays, the number is taken later.
    found = district_codes(["wamego", "unified", "school", "district", "320"])
    assert found.words == ["wamego", "unified", "school", "district", "320"]
    assert not found.coded
    # A designator without a number is no code.
    assert not district_codes(["regional", "school", "unit"]).codes


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("Woodland Pk", ("woodland", "park")),
        ("Washington Pk Campus", ("washington", "park", "campu")),
        ("McCorkle PK-8", ("mccorkle",)),
        ("David Ellis Academy PK", ("david", "elli", "academy")),
        ("PK Center", ("center",)),
    ],
)
def test_pk_is_park_after_a_name(text: str, words: tuple[str, ...]) -> None:
    assert listing_forms(text).school.tokens == words


def test_pk_before_a_grade_is_prekindergarten() -> None:
    assert listing_forms("McCorkle PK-8").school.levels == {"prekindergarten"}
    assert listing_forms("David Ellis Academy PK").school.levels == {"prekindergarten"}
    assert not listing_forms("Woodland Pk").school.levels


def test_ex_vill_is_exempted_village() -> None:
    assert _district("Chagrin Falls Ex Vill SD") == _district("Chagrin Falls Exempted Village")
    assert _district("Milford Ex. Village Schools") == _district("Milford Exempted Village")
    assert listing_forms("Ex Libris").school.tokens == ("ex", "libri")


def test_chartered_is_charter() -> None:
    assert _school("Gathering Falls Chartered Public School") == _school(
        "Gathering Falls Charter Public School"
    )


@pytest.mark.parametrize(
    ("text", "hint", "public_school"),
    [
        ("Elba Public School", Level.UNKNOWN, True),
        ("ELBA PUBLIC SCHOOL - Closed", Level.UNKNOWN, True),
        ("Elba Public Schools", Level.DISTRICT, False),
        ("Marblehead Community Charter Public School", Level.SCHOOL, True),
        ("Elba Elementary Public School", Level.SCHOOL, True),
        ("Elba School", Level.SCHOOL, False),
    ],
)
def test_public_school(text: str, hint: Level, *, public_school: bool) -> None:
    """A town's "Public School" is its system or a school of that name: either."""
    forms = listing_forms(clean_listing(text).text)
    assert forms.hint is hint
    assert forms.district.public_school is public_school


def test_records_say_their_kind() -> None:
    assert record_form("CAREY PUBLIC SCHOOL", district=False).public_school
    assert not record_form("ELBA PUBLIC SCHOOLS", district=True).public_school
    assert record_form("BIRCHES SCHOOL", district=False).names_kind
    assert record_form("Lincoln Elementary", district=False).names_kind
    assert record_form("Seacliff Academy", district=False).names_kind
    assert record_form("Craftsbury Schools", district=False).names_kind
    assert not record_form("GLORIA DEO", district=False).names_kind
    assert not record_form("Robert Frost", district=False).names_kind


@pytest.mark.parametrize(
    ("listing", "word"),
    [
        ("Royston, LLC", "llc"),
        ("Royston LLC", "llc"),
        ("Penn Waste Inc.", "inc"),
        ("Bindery Associates, L.L.C.", "llc"),
        ("Harbor Tool Ltd - Closed", "ltd"),
    ],
)
def test_businesses_are_not_schools(listing: str, word: str) -> None:
    clean = clean_listing(listing)
    assert clean.business == word
    found = not_school(clean)
    assert found is not None
    assert found.business
    assert found.kind == "business"
    assert found.what == word
    assert not found.may_be_a_place


@pytest.mark.parametrize(
    "listing",
    [
        "River Academy of Excellence, LLC",
        "Synergy Public School Inc.",
        "Little Sprouts Elementary, Inc.",
        "Incline Village Elementary",
        "Lincoln Middle School",
    ],
)
def test_schools_that_are_companies_are_schools(listing: str) -> None:
    assert not_school(clean_listing(listing)) is None


def test_a_civic_body_is_not_a_business() -> None:
    found = not_school(clean_listing("Monessen City Hall"))
    assert found is not None
    assert found.kind == "civic body"


def test_a_number_and_of_without_a_county_is_no_legal_description() -> None:
    form = record_form("Academy 5 of Arts and Letters", district=False)
    assert form.numbers == {"5"}
    assert form.tokens == ("academy", "of", "art", "and", "letter")
    assert not form.implied


# -- directions -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "spelled"),
    [
        ("e. lansing public schools", "east lansing public schools"),
        ("e lansing schools", "east lansing schools"),
        ("w des moines", "west des moines"),
        ("s. portland schools", "south portland schools"),
        ("n. little rock sd", "north little rock sd"),
        ("no. little rock sd", "north little rock sd"),
        ("so. burlington high school", "south burlington high school"),
        ("so sioux city community schs", "south sioux city community schs"),
        ("so. st. paul public schools", "south st. paul public schools"),
        ("n. mt. vernon", "north mt. vernon"),
        ("ne polk", "northeast polk"),
        ("nw webster", "northwest webster"),
        ("sw livingston co. r-i", "southwest livingston co. r-i"),
        ("pontiac-w holliday sd 105", "pontiac-west holliday sd 105"),
        ("manson-nw webster schools", "manson-northwest webster schools"),
        ("usd 251 n. lyon county", "usd 251 north lyon county"),
        ("usd 306 se of saline", "usd 306 southeast of saline"),
        ("village school of n. bennington", "village school of north bennington"),
        ("village school of no.bennington", "village school of north bennington"),
        ("e.lansing public schools", "east lansing public schools"),
        ("berwick, lebanon, n. berwick", "berwick, lebanon, north berwick"),
        ("cumberland and n. yarmouth", "cumberland and north yarmouth"),
        ("lake zurich middle - n campus", "lake zurich middle - north campus"),
        ("e./n. providence schools", "east/north providence schools"),
        ("e/n providence", "east/north providence"),
    ],
)
def test_directions_are_spelled_out_where_a_direction_stands(text: str, spelled: str) -> None:
    assert expand_directions(text) == spelled


@pytest.mark.parametrize(
    "text",
    [
        "harry s. truman elementary",  # a middle initial
        "joel e. barber elementary",
        "robert e. lee elementary",
        "davis n elem school",  # Chicago names a school for Nathan Davis so
        "e h gentry elementary",  # an initial before another initial
        "w. d. hall middle",
        "s and j sanitation",  # initials before "and"
        "cumberland and n yarmouth",  # "and" needs the dot
        "e prep woodmere",  # a letter before a school's kind is part of a name
        "no limits academy",  # "No" is North only with its dot
        "college of so nv",  # "So" without a dot only at the start
        "se do mo cha",  # a two-letter direction needs a longer word
        "no ky",
        "omaha, ne",  # nothing after it
        "lincoln elementary - s",
    ],
)
def test_a_letter_that_is_no_direction_stays(text: str) -> None:
    assert expand_directions(text) == text


@pytest.mark.parametrize(
    ("listing", "directory"),
    [
        ("E. Lansing Public Schools", "East Lansing School District"),
        ("W. Des Moines Schools", "West Des Moines Comm School District"),
        ("So. Burlington High School", "South Burlington High School"),
        ("No. Little Rock School District", "NORTH LITTLE ROCK SCHOOL DISTRICT"),
        ("South Sioux City Schools", "SO SIOUX CITY COMMUNITY SCHS"),
        ("N.E. Polk Schools", "Northeast Polk Comm School District"),
        ("West Harlan-Dixby School District 147", "W Harlan-Dixby PSD 147"),
        ("Village School of N. Bennmoor", "VILLAGE SCHOOL OF NO.BENNMOOR"),
    ],
)
def test_abbreviated_and_spelled_directions_meet(listing: str, directory: str) -> None:
    listed = listing_forms(clean_listing(listing).text).district
    assert _key(listed) == _key(record_form(directory, district=True))
    assert listed.directions


@pytest.mark.parametrize(
    ("name", "directions"),
    [
        ("E. Lansing Public Schools", {"east"}),
        ("E./N. Providence Schools", {"east", "north"}),
        ("SE Polk", {"southeast"}),
        ("Lansing Public Schools", set()),
        ("Harry S. Truman Elementary", set()),
        ("Northwood Elementary", set()),  # one word, not a direction
    ],
)
def test_a_name_says_its_directions(name: str, directions: set[str]) -> None:
    assert listing_forms(clean_listing(name).text).district.directions == directions


def test_a_direction_that_begins_a_part_is_spelled_out() -> None:
    clean = clean_listing("Lake Zurich Middle - N Campus")
    assert clean.text == "Lake Zurich Middle North Campus"
    assert clean.segments == ("Lake Zurich Middle", "N Campus")
    assert clean_listing("Harwick High - s campus").text == "Harwick High south campus"
    # Not before a school's kind, nor before an initial.
    assert clean_listing("Tolland - E Prep").text == "Tolland E Prep"
    assert clean_listing("Tolland - W. D. Hall").text == "Tolland W. D. Hall"


@pytest.mark.parametrize(
    ("name", "levels"),
    [
        ("Great Bay Charter School (H)", {"high"}),
        ("North Country Charter Academy (M)", {"middle"}),
        ("Academy for Science and Design Charter (M)", {"middle"}),
        ("Virtual Learning Academy (E)", {"elementary"}),
        ("Alton Central School (Elem)", {"elementary"}),
        ("Harwick Park E", set()),  # a letter after a name is no level
        ("Joel E. Barber", set()),
    ],
)
def test_new_hampshire_level_letters(name: str, levels: set[str]) -> None:
    assert record_form(name, district=False).levels == levels


def test_h_s_after_a_name_is_high_school_and_first_is_initials() -> None:
    assert record_form("ORVELL H S OF KESTON", district=False).levels == {"high"}
    assert record_form("Keston Township H S Brantley", district=False).levels == {"high"}
    # First in a name, a person's initials, unless a school word or nothing follows.
    initials = record_form("H S Thompson Learning Center", district=False)
    assert initials.levels == frozenset()
    assert initials.tokens[:2] == ("h", "s")
    assert record_form("H S", district=False).levels == {"high"}


@pytest.mark.parametrize(
    ("name", "named"),
    [
        ("PREMIER HIGH SCHOOLS", True),
        ("Orvell High Schools", True),
        ("Arrow Academy", True),
        ("Orenda Charter School", True),
        ("Ravensburg County Career and Technology Center", True),
        ("Naytahwaush Community School", True),
        ("Harlow Preparatory Academies", True),
        ("Fortuna Elementary", False),
        ("Siskiyou Union High", False),
        ("Township High School District 214", False),
        ("Hunterdon Central Regional High School District", False),
        ("Lake View Charter District", False),
        ("IDEA Public Schools", False),
        ("Harwell City Schools", False),
        ("Halloran ISD", False),
        ("Keston Unified", False),
        ("Keston School Corporation", False),
    ],
)
def test_a_name_named_as_one_school(name: str, *, named: bool) -> None:
    assert record_form(name, district=True).school_named is named


def test_named_as_school_reads_canonical_words() -> None:
    assert named_as_school(("premier", "high", "schools"))
    assert not named_as_school(("premier", "high", "schools", "district"))
    assert not named_as_school(("high", "point"))
    assert not named_as_school(())


@pytest.mark.parametrize(
    ("name", "tokens", "qualifiers", "levels"),
    [
        # A legal form before the levels or qualifiers a district's name ends with.
        ("Westside Union Elementary", ("westside",), set(), {"elementary"}),
        ("Roseville Joint Union High", ("roseville",), set(), {"high"}),
        ("Clay Joint Elementary", ("clay",), set(), {"elementary"}),
        ("Buckeye Union High School District (4284)", ("buckeye",), set(), {"high"}),
        ("Sycamore Community City", ("sycamore",), {"city"}, set()),
        ("Oak Hill Union Local", ("oak", "hill"), {"local"}, set()),
        ("St Henry Consolidated Local", ("saint", "henry"), {"local"}, set()),
        ("Bremen CHSD 228", ("bremen",), set(), {"high"}),
        # "Union" at the end, and then the legal form before it.
        ("Cupertino Union", ("cupertino",), set(), set()),
        ("Mountain Views Unified Union School District #76", ("mountain", "view"), set(), set()),
        # A name that is no name alone keeps it.
        ("Mount Union Area SD", ("mount", "union"), {"area"}, set()),
        ("North Union Local School District", ("north", "union"), {"local"}, set()),
        ("Union Local", ("union",), {"local"}, set()),
        ("Union City School District", ("union",), {"city"}, set()),
        # Before an exempted village, as before any other kind of place.
        ("Chesapeake Union Exempted Village", ("chesapeake", "exempted"), {"village"}, set()),
        ("Chesapeake Union", ("chesapeake",), set(), set()),
        # "Central" is a legal form only where it ends one, after a name alone.
        ("Greene Central School District", ("greene",), set(), set()),
        ("West Central Comm School District", ("west", "central"), set(), set()),
        ("West Central Schools", ("west", "central"), set(), set()),
        (
            "Washington Central Unified Union School District #92",
            ("washington", "central"),
            set(),
            set(),
        ),
        ("La Union Schools", ("la", "union"), set(), set()),
        # "Community" only before City, Local or High; "Central" is a name there.
        ("Irvington Community Middle School", ("irvington", "community"), set(), {"middle"}),
        ("Buckeye Central Local", ("buckeye", "central"), {"local"}, set()),
        ("Shade-Central City SD", ("shade", "central"), {"city"}, set()),
    ],
)
def test_legal_forms_inside_a_district_name_go(
    name: str, tokens: tuple[str, ...], qualifiers: set[str], levels: set[str]
) -> None:
    form = record_form(name, district=True)
    assert form.tokens == tokens
    assert form.qualifiers == qualifiers
    assert form.levels == levels


def test_legal_forms_inside_a_name_stay_in_its_school_reading() -> None:
    # A school's name is not stripped: "Westside Union School" is its name.
    assert record_form("Westside Union Elementary", district=False).tokens == ("westside", "union")
    assert legal_words("Sycamore Community City") == {"community"}
    assert legal_words("Roseville Joint Union High") == {"joint", "union"}
    assert listing_forms("Sycamore Community Schools").district.tokens == ("sycamore",)


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("Oak Hills", ("oak", "hills")),
        ("Oak Hill", ("oak", "hill")),
        ("Scotts Valley", ("scotts", "valley")),
        ("St. Mary's", ("saint", "marys")),
        ("SAINT MARYS", ("saint", "marys")),
        ("Mt. Lindell", ("mount", "lindell")),
        ("Coeur d'Alene", ("coeur", "dalene")),
    ],
)
def test_a_name_as_spelled_keeps_its_plurals(text: str, words: tuple[str, ...]) -> None:
    assert spelled_name(text).words == words


def test_a_name_as_spelled_sets_levels_and_qualifiers_apart() -> None:
    spelled = spelled_name("Oak Hills Local School District", district=True)
    assert spelled == SpelledName(("oak", "hills"), frozenset({"local"}), frozenset())
    assert spelled_name("High Point").levels == {"high"}
    assert spelled_name("Tarrow Union Elementary", district=True).words == ("tarrow",)
    assert listing_forms("Oak Hill Schools").spelled == ("oak", "hill")


# -- brackets NCES ends a name with (SYNTHETIC names in NCES's shapes) -------------


@pytest.mark.parametrize(
    ("name", "base", "parts"),
    [
        ("Everbrook School District (Tallis)", "Everbrook School District", ("Tallis",)),
        ("Flagmoor Unified District (4192)", "Flagmoor Unified District", ("4192",)),
        ("NEWMOOR SCHOOL (THE) (G & T)", "NEWMOOR SCHOOL", ("THE", "G & T")),
        # The CCD cut the name at 60 characters, inside a bracket.
        (
            "Southmoor Technical District of Varnell (ST (92705)",
            "Southmoor Technical District of Varnell",
            ("92705",),
        ),
        ("Portmoor Preparation Inc. ( (4431)", "Portmoor Preparation Inc.", ("4431",)),
        # A school's level letter is its name's.
        ("Great Harrow Charter School (H)", "Great Harrow Charter School (H)", ()),
        ("Lindell Elementary", "Lindell Elementary", ()),
        ("(4192)", "(4192)", ()),
    ],
)
def test_brackets_are_split_from_a_name(name: str, base: str, parts: tuple[str, ...]) -> None:
    assert split_brackets(name) == (base, parts)


@pytest.mark.parametrize(
    ("county", "words", "kind"),
    [
        ("Tallis County", ["tallis"], "county"),
        ("Van Harrow County", ["van", "harrow"], "county"),
        ("Orlane Parish", ["orlane"], "parish"),
        ("Alderton city", ["alderton"], None),
        ("Capitol Planning Region", ["capitol", "planning"], None),
        ("Tallis", ["tallis"], None),
    ],
)
def test_county_words_leave_out_the_county(county: str, words: list[str], kind: str | None) -> None:
    assert county_words(county) == (words, kind)


def test_a_county_in_brackets_tells_namesakes_apart() -> None:
    read = directory_name(
        "Everbrook School District (Tallis)", district=True, county="Tallis County"
    )
    assert read == DirectoryName(
        "Everbrook School District", frozenset({"talli"}), "county", frozenset(), ()
    )
    assert directory_name(
        "Van Harrow Public Schools (Van Harrow County)", district=True, county="Van Harrow County"
    ).county == {"van", "harrow"}
    # Another county's name is a second name, as any other bracket of a district's.
    assert directory_name(
        "Everbrook School District (Tallis)", district=True, county="Quenby County"
    ).second == ("Tallis",)
    assert directory_name("Everbrook School District (Tallis)", district=True).second == ("Tallis",)


@pytest.mark.parametrize(
    ("name", "district", "expected"),
    [
        (
            "Flagmoor Unified District (4192)",
            True,
            DirectoryName("Flagmoor Unified District", entity="4192"),
        ),
        (
            "Harrow Education Services (025076)",
            True,
            DirectoryName("Harrow Education Services", entity="25076"),
        ),
        ("Harrow Charter School (12)", False, DirectoryName("Harrow Charter School")),
        ("Harrow Strict Academy (PSAD)", True, DirectoryName("Harrow Strict Academy")),
        ("BRACKENDALE CHARTER SCHOOL (THE)", True, DirectoryName("BRACKENDALE CHARTER SCHOOL")),
        ("Shellmoor Lake Elementary (3-6)", False, DirectoryName("Shellmoor Lake Elementary")),
        ("Shellmoor Primary (PK-2)", False, DirectoryName("Shellmoor Primary")),
        ("Hollis Academy ()", False, DirectoryName("Hollis Academy")),
        (
            "COMANDRA ACADEMY (CHARTER)",
            True,
            DirectoryName("COMANDRA ACADEMY", legal=frozenset({"charter"})),
        ),
        (
            "CARVERTON-STONY MILL CSD (NORTH ROCKMERE)",
            True,
            DirectoryName("CARVERTON-STONY MILL CSD", second=("NORTH ROCKMERE",)),
        ),
        (
            "Edvale Local (formerly Berrow-Millan)",
            True,
            DirectoryName("Edvale Local", second=("Berrow-Millan",)),
        ),
        (
            "Vistamoor Academy Inc. (FRM LA Connections)",
            True,
            DirectoryName("Vistamoor Academy Inc.", second=("LA Connections",)),
        ),
        # A church's or faith's initials, or nothing that names, are no second name.
        ("Clarabel Ford Academy (SDA)", True, DirectoryName("Clarabel Ford Academy")),
        ("Harrow Learning Center (& of)", True, DirectoryName("Harrow Learning Center")),
        # A school keeps a bracket that says its level, campus or kind.
        ("The Vesper School (Middle)", False, DirectoryName("The Vesper School (Middle)")),
        (
            "Marlow Charter School (THE) (North Campus)",
            False,
            DirectoryName("Marlow Charter School (North Campus)"),
        ),
        ("Harlow High (Continuation)", False, DirectoryName("Harlow High (Continuation)")),
        ("Lindell Elementary", False, DirectoryName("Lindell Elementary")),
    ],
)
def test_brackets_are_read_for_what_they_say(
    name: str, district: bool, expected: DirectoryName
) -> None:
    assert directory_name(name, district=district, county="Tallis County") == expected


def test_an_entity_number_is_no_part_of_a_name() -> None:
    form = record_form(
        directory_name("Flagmoor Unified District (4192)", district=True).base, district=True
    )
    assert form.tokens == ("flagmoor",)
    assert not form.numbers


@pytest.mark.parametrize(
    ("name", "tokens", "qualifiers", "levels"),
    [
        ("High Township School District", ("high",), {"township"}, set()),
        ("High Township Middle School", ("high",), {"township"}, {"middle"}),
        # More of the name follows "Village": a word of the name, not a qualifier.
        (
            "MIDDLE VILLAGE PREPARATORY CHARTER SCHOOL",
            ("middle", "village", "preparatory", "charter"),
            set(),
            set(),
        ),
        ("Middle Village Elementary", ("middle",), {"village"}, {"elementary"}),
        # Elsewhere a level word is a level.
        (
            "Middle Area Learning Center",
            ("area", "learning", "center"),
            set(),
            {"middle"},
        ),
        ("Harrow Middle Township School", ("harrow",), {"township"}, {"middle"}),
    ],
)
def test_a_level_word_that_names_a_place_is_a_name(
    name: str, tokens: tuple[str, ...], qualifiers: set[str], levels: set[str]
) -> None:
    form = record_form(name, district=False)
    assert form.tokens == tokens
    assert form.qualifiers == qualifiers
    assert form.levels == levels


def test_a_listing_of_a_level_word_that_names_a_place() -> None:
    forms = listing_forms("High Township")
    assert forms.hint is Level.UNKNOWN
    assert forms.district.tokens == ("high",)
    assert listing_forms("High Township Schools").hint is Level.DISTRICT
    assert listing_forms("High Township Middle School").hint is Level.SCHOOL
    assert spelled_name("High Township").words == ("high",)
    assert is_bare_name("High Township")


def test_common_is_a_legal_form() -> None:
    assert record_form("TUCKERMOOR COMMON SCHOOL DISTRICT", district=True).tokens == ("tuckermoor",)
    assert legal_words("Tuckermoor Common School District") == {"common", "school", "district"}
    # Not the name itself.
    assert record_form("Common Harrow High School District", district=True).tokens == (
        "common",
        "harrow",
    )


@pytest.mark.parametrize("text", ["St.", "St", "Mt.", "Ft", "Ste.", "Saint", "Street", "MT."])
def test_an_abbreviation_alone_names_nothing(text: str) -> None:
    assert listing_forms(clean_listing(text).text).is_empty


@pytest.mark.parametrize(
    "text", ["St. Marys", "Mount Elementary", "Street El", "Fort County Schools", "Mt. 7"]
)
def test_an_abbreviation_with_more_names_something(text: str) -> None:
    assert not listing_forms(clean_listing(text).text).is_empty


def test_a_bracket_the_ccd_left_unbalanced_ends_the_peeling() -> None:
    assert split_brackets("Harrow Academy (North))") == ("Harrow Academy (North))", ())


def test_a_bracket_after_one_a_school_keeps_is_kept_too() -> None:
    read = directory_name("Marlow Charter School (North Campus) (THE)", district=False)
    assert read.base == "Marlow Charter School (North Campus) (THE)"


@pytest.mark.parametrize(
    ("text", "text_after", "base", "brackets"),
    [
        (
            "Masonby Consolidated Schools (Monrow) - Closed",
            "Masonby Consolidated Schools Monrow",
            "Masonby Consolidated Schools",
            ("Monrow",),
        ),
        (
            "Everbrook SD (Tallis) (Closed): 2 Hour Delay",
            "Everbrook SD Tallis",
            "Everbrook SD",
            ("Tallis",),
        ),
        ("Flagmoor Unified District (4192)", "Flagmoor Unified District", "", ()),
        ("Harrow Strict Academy (SDA)", "Harrow Strict Academy", "", ()),
        ("Comandra Academy (Charter) - Closed", "Comandra Academy", "", ()),
        ("Shellmoor Lake Elementary (K-5)", "Shellmoor Lake Elementary", "", ()),
        ("Brackendale Charter School (The)", "Brackendale Charter School", "", ()),
        ("Duskmoor (All Schools)", "Duskmoor", "", ()),
        ("Harrow - Lincoln Elementary", "Harrow Lincoln Elementary", "", ()),
    ],
)
def test_a_listing_keeps_its_brackets_apart(
    text: str, text_after: str, base: str, brackets: tuple[str, ...]
) -> None:
    clean = clean_listing(text)
    assert clean.text == text_after
    assert clean.base == base
    assert clean.brackets == brackets


def test_a_bracket_says_its_words_without_formerly() -> None:
    assert bracket_form("formerly Berrow-Millan").token_set == {"berrow", "millan"}
    assert bracket_form("Elementary").levels == {"elementary"}
    assert not bracket_form("Elementary").token_set


@pytest.mark.parametrize(
    ("text", "entity"),
    [
        ("Flagmoor Unified District (4192)", "4192"),
        ("Harrow Services (025076) - Closed", "25076"),
        ("Harrow Charter School (12)", None),
        ("Harrow Elementary (K-5)", None),
        ("Harrow Elementary", None),
    ],
)
def test_a_listing_s_entity_number_is_kept_apart(text: str, entity: str | None) -> None:
    clean = clean_listing(text)
    assert clean.entity == entity
    assert not any(ch.isdigit() for ch in clean.text) or entity is None


@pytest.mark.parametrize(
    ("listing", "record"),
    [
        # Missouri's state schools, which NCES names without "State".
        ("Mapleby Valley State School", "MAPLEBY VALLEY SCHOOL"),
        # Pennsylvania's "CS" inside a name, before a word, is Charter School.
        ("Pennby Hills Charter School of Enterprise", "Pennby Hills CS of Enterprise"),
        ("Provby Charter School West", "Provby CS - West"),
    ],
)
def test_school_habits_read_both_ways(listing: str, record: str) -> None:
    assert listing_forms(listing).school.tokens == record_form(record, district=False).tokens


def test_state_and_cs_stay_where_they_name() -> None:
    # "State" that is not the last word before School, or all there is, stays.
    assert "state" in record_form("Ohby State School for the Blind", district=False).tokens
    assert record_form("State Schools", district=True).tokens == ("state",)
    # A number after "CS" is New York's community school, and "C.S." first a
    # person's initials, which stay letters (``"C. S. Lewby"``), never a charter school.
    assert "charter" not in record_form("CS 211", district=False).tokens
    lewby = record_form("C.S. Lewby Academy", district=False)
    assert lewby.tokens[:3] == ("c", "s", "lewby")
    assert "charter" not in lewby.tokens


def test_a_and_m_names_a_university() -> None:
    assert non_k12(clean_listing("TEXBY A&M")) == "university"
    assert non_k12(clean_listing("Texby A & M")) == "university"
    assert non_k12(clean_listing("A&M Consolidated High School")) is None


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Memby Merit Academy Charter School", "Memby Merit Academy"),
        ("Memby Merit Acad. Charter School", "Memby Merit Acad."),
        ("Kippby Preparatory Charter School.", "Kippby Preparatory"),
        ("Arts Institute Charter School", "Arts Institute"),
        # Without a type before it, Charter is the school's kind, and stays.
        ("Robby Frost Charter School", None),
        ("Memby Charter Academy", None),
        ("Memby Merit Academy Charter Schools", None),
    ],
)
def test_charter_school_after_a_type_may_be_read_without(text: str, name: str | None) -> None:
    assert without_charter_school(text) == name


@pytest.mark.parametrize(
    ("name", "district", "tokens", "qualifiers", "levels"),
    [
        # A place word that begins a name is a word of it.
        ("VILLAGE CHRISTIAN ACADEMY", False, ("village", "christian", "academy"), set(), set()),
        ("TOWN & COUNTRY DAY SCHOOL", False, ("town", "and", "country", "day"), set(), set()),
        ("CITY ACADEMY", False, ("city", "academy"), set(), set()),
        ("County Line Elementary", False, ("county", "line"), set(), {"elementary"}),
        ("Village Elementary", False, ("village",), set(), {"elementary"}),
        # So is a kind of town with more of the name after it.
        ("KID CITY ACADEMY", False, ("kid", "city", "academy"), set(), set()),
        ("Kansas City Christian School", False, ("kansa", "city", "christian"), set(), set()),
        ("Global Village Academy", False, ("global", "village", "academy"), set(), set()),
        # A county's, a township's or a district's kind after a name is its qualifier.
        ("Lebanon Area Career Ctr", False, ("lebanon", "career", "center"), {"area"}, set()),
        (
            "ST ELIZABETH AREA CATHOLIC SCHOOL",
            False,
            ("saint", "elizabeth", "catholic"),
            {"area"},
            set(),
        ),
        ("Laclede County R-1 Conway", True, ("laclede", "conway"), {"county"}, set()),
        # A state's name adds nothing to a town's.
        ("Kansas City Kansas", True, ("kansa", "kansa"), {"city"}, set()),
        # And a kind of place after no place's name, or after a linking word.
        ("EAST VILLAGE ELEMENTARY", False, ("east", "village"), set(), {"elementary"}),
        ("MONTESSORI IN TOWN", False, ("montessori", "in", "town"), set(), set()),
        # One that ends a name after the name it qualifies is a qualifier.
        ("Toledo City", True, ("toledo",), {"city"}, set()),
        ("Faketown City Schools", True, ("faketown",), {"city"}, set()),
        ("Milford Exempted Village", True, ("milford", "exempted"), {"village"}, set()),
        ("Union City High School", False, ("union",), {"city"}, {"high"}),
        ("Crawford County Schools", True, ("crawford",), {"county"}, set()),
        ("Oak Hill Union Local", True, ("oak", "hill"), {"local"}, set()),
        ("Tri-County Area SD", True, ("tri",), {"county", "area"}, set()),
        # A district kind follows a direction as well as a town's name.
        ("Northwest Local", True, ("northwest",), {"local"}, set()),
        # A name of a qualifier and a number keeps its qualifier.
        ("Township High School District 214", True, (), {"township"}, {"high"}),
        # A government's name is read name first.
        ("City Schools of Decatur", True, ("decatur",), {"city"}, set()),
        ("School City of Hammond", True, ("hammond",), {"city"}, set()),
        ("School Town of Speedway", True, ("speedway",), {"town"}, set()),
        ("Township of Union School District", True, ("union",), {"township"}, set()),
    ],
)
def test_a_qualifier_ends_a_name_after_the_name_it_qualifies(
    name: str,
    *,
    district: bool,
    tokens: tuple[str, ...],
    qualifiers: set[str],
    levels: set[str],
) -> None:
    form = record_form(name, district=district)
    assert form.tokens == tokens
    assert form.qualifiers == qualifiers
    assert form.levels == levels


def test_a_listing_that_leaves_out_a_leading_place_word_is_another_name() -> None:
    record = record_form("VILLAGE CHRISTIAN ACADEMY", district=False)
    listing = listing_forms("Christian Academy").school
    assert listing.token_set < record.token_set
    assert listing.compact != record.compact
    assert record.qualifier_first
    assert not record_form("Toledo City", district=True).qualifier_first
    # The words around a qualifier, not the qualifier alone, say whether it is one.
    words = ["kid", "city", "academy"]
    classes = [(0, "kid"), (2, "city"), (0, "academy")]
    assert not qualifies(words, classes, 1)
    assert qualifies(words[:2], classes[:2], 1)
    assert not qualifies(["in", "town"], [(0, "in"), (2, "town")], 1)


def test_spelled_names_read_a_government_s_name_first() -> None:
    assert spelled_name("Township of Union School District", district=True) == spelled_name(
        "Union Township School District", district=True
    )
    assert spelled_name("Village Christian Academy").words == ("village", "christian", "academy")


@pytest.mark.parametrize(
    ("listing", "numbers"),
    [
        ("Spartanburg District Seven", {"7"}),
        ("Anderson School District Five", {"5"}),
        ("Richland One", {"1"}),
        ("Florence One Schools", {"1"}),
        ("Lexington-Richland Five", {"5"}),
        ("Unit Twelve", {"12"}),
        # Elsewhere a number word is a word of the name.
        ("Anderson Five Charter School", set()),
        ("Five Points Elementary", set()),
        ("Seven Hills School", set()),
        ("One", set()),
    ],
)
def test_a_district_number_in_words_is_a_number(listing: str, numbers: set[str]) -> None:
    assert listing_forms(listing).district.numbers == numbers


def test_friends_is_a_faith_but_not_before_of() -> None:
    assert affiliations_of(["sidwell", "friends"]) == {"friends"}
    assert affiliations_of(["friends", "of", "the", "library"]) == frozenset()
    assert affiliations_of(["friends", "for", "life"]) == frozenset()
    assert listing_forms("Friends").school.affiliations == {"friends"}
    assert not listing_forms("Friend Public Schools").district.affiliations


def test_a_child_care_chain_is_named_by_its_brand() -> None:
    assert chains_of(["goddard", "school", "of", "dallas"]) == {"goddard school"}
    assert chains_of(["goddard", "middle", "school"]) == frozenset()
    assert chains_of(["kids", "r", "kids"]) == {"kids r kids"}
    assert listing_forms("The Goddard School").school.affiliations == {"goddard school"}
    assert listing_forms("Children's Lighthouse").school.affiliations == {"childrens lighthouse"}
    assert not record_form("Goddard High", district=False).affiliations


@pytest.mark.parametrize(
    ("name", "count"),
    [
        ("J F Kennaby Middle School", 2),
        ("John F Kennaby Middle", 2),
        ("R. D. Whiteby Elementary", 2),
        ("J.F. Kennaby Middle School", 2),
        ("Charles Whiteby Elementary", 1),
        ("LYNDON B JOHNBY EL", 2),
        ("BEATRIZ G GARZBY MIDDLE", 2),
        ("Martin Luther Kingby Jr Elementary", 2),
        ("George H W Bushby Elementary", 3),
        ("Dr. W.J. Creelby Elementary", 3),
        ("Dr. Charles Drewby Elementary", 2),
        ("J. Fithian Tatby School", 2),
        ("LLOYD & DOLLY BENTSBY EL", 3),
        ("J K Smithby Elementary", 2),
        ("Nettie S Freedby K-8 Expeditionary School", 2),
        # A trailing initial, no forename, a place's words, a title alone.
        ("WHITBY E EL", 0),
        ("Whitby Elementary", 0),
        ("Oak Park Elementary", 0),
        ("North Parkby Elementary", 0),
        ("Saint John Elementary", 0),
        ("Sacred Heart School", 0),
        ("Chief Charby School", 0),
        # "And" joins two forenames only: "Lewis and Clarkby" are two surnames.
        ("Lewis and Clarkby Elementary", 0),
        ("K-8 School of the Artsby", 0),
        # The word after them must name: a kind, a faith or a level names no one.
        ("Plan B Academy", 0),
        ("Grace Christian Academy", 0),
    ],
)
def test_a_school_s_name_says_how_many_forenames_it_begins_with(name: str, count: int) -> None:
    assert record_form(name, district=False).forenames == count


def test_a_district_s_name_begins_with_no_forenames() -> None:
    assert record_form("Warren County", district=True).forenames == 0
    assert record_form("Glen Rose ISD", district=True).forenames == 0


def test_the_given_names_are_the_census_list_s() -> None:
    assert len(GIVEN_NAMES) == 1555
    assert {"john", "charles", "pearl", "mark", "lyndon"} - GIVEN_NAMES == {"lyndon"}
    assert all(name == name.casefold() and name.isalpha() for name in GIVEN_NAMES)


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("J.F. Kennaby Middle School", ("j", "f", "kennaby")),
        ("Robert J.C. Riceby Elementary School", ("robert", "j", "c", "riceby")),
        ("DR. W.J. CREELBY ELEMENTARY SCHOOL", ("dr", "w", "j", "creelby")),
        ("Huby/A.G. Bellby Elementary School", ("huby", "a", "g", "bellby")),
        ("G.W.STOUTBY ELEMENTARY", ("g", "w", "stoutby")),
        # A dotted group that is no one's initials closes up, as before.
        ("A.C.E. Academy", ("ace", "academy")),
        ("Premby H.S. of Tylby", ("premby", "school", "of", "tylby")),
    ],
)
def test_a_person_s_dotted_initials_stay_letters(text: str, tokens: tuple[str, ...]) -> None:
    assert record_form(text, district=False).tokens == tokens


def test_dotted_groups_that_are_no_initials_close_up() -> None:
    assert record_form("Genby I.S.D.", district=True).tokens == ("genby",)
    assert record_form("Old Turnby M.S.", district=False).levels == frozenset({"middle"})
    assert "northeast" in record_form("N.E. Regional Center", district=False).tokens


def test_a_dotted_initial_is_no_roman_numeral() -> None:
    watby = record_form("J. I. Watby Elementary School", district=False)
    assert watby.tokens == ("j", "i", "watby")
    assert not watby.numbers
    assert record_form("C.V. KOOGBY MIDDLE", district=False).tokens == ("c", "v", "koogby")
    # A numbered district's letter and numeral are no initials.
    assert record_form("Avaby R-I", district=True).numbers == frozenset({"1"})
    assert record_form("Grainby Valley R-V", district=True).numbers == frozenset({"5"})
    assert record_form("Avaby R-I Elementary", district=False).numbers == frozenset({"1"})


def test_j_h_first_before_a_name_is_a_person_s_initials() -> None:
    willby = record_form("J.H. Willby Middle School", district=False)
    assert willby.tokens == ("j", "h", "willby")
    assert willby.levels == frozenset({"middle"})
    assert record_form("Lincby J H", district=False).levels == frozenset({"juniorhigh"})
    assert record_form("J H S 45", district=False).levels == frozenset({"juniorhigh"})


def test_a_number_before_a_person_s_initials_is_no_joint_district() -> None:
    forms = listing_forms("DIST #201 (J.S. MORTBY HIGH SCHOOLS)")
    assert forms.district.numbers == frozenset({"201"})
    assert forms.district.tokens[:3] == ("j", "s", "mortby")
    assert record_form("Sherby 28-J", district=True).numbers == frozenset({"28j"})


@pytest.mark.parametrize(
    ("name", "said", "count"),
    [
        ("Kenby (John F.) Elementary", "John F. Kenby Elementary", 2),
        ("Lincby (Abraham) Elementary", "Abraham Lincby Elementary", 1),
        ("Chipby (W.T.) Middle School", "W.T. Chipby Middle School", 2),
        ("Morrby (Evelyn I.) Early Childhood", "Evelyn I. Morrby Early Childhood", 2),
        ("Stowby(Cecil B.) Elementary", "Cecil B. Stowby Elementary", 2),
        ("Dickby (Billy Joe) High (Continuation)", "Billy Joe Dickby High (Continuation)", 2),
    ],
)
def test_forenames_nces_brackets_after_the_surname_go_before_it(
    name: str, said: str, count: int
) -> None:
    assert bracketed_forenames(name) == (said, count)
    read = directory_name(name, district=False)
    assert read.forenames == count
    assert read.base == said.removesuffix(" (Continuation)") or read.base == said


@pytest.mark.parametrize(
    "name",
    [
        "Knowledge Enlightens You (KEY) Academy",
        "William (Bill) Robby ECE-8 School",
        "William J. (Pete) Knightby High",
        "Sierra Vistby (SV) Academy",
        "Great Bay Charter School (H)",
    ],
)
def test_other_brackets_are_no_forenames(name: str) -> None:
    assert bracketed_forenames(name) is None
    assert directory_name(name, district=False).forenames == 0


def test_a_district_s_bracket_is_never_forenames() -> None:
    assert directory_name("Kenby (John F.) Elementary", district=True).forenames == 0


def test_a_plural_s_is_kept_apart_from_a_possessive() -> None:
    assert record_form("Parks Elementary", district=False).plurals == frozenset({"park"})
    assert record_form("The Oaks School", district=False).plurals == frozenset({"oak"})
    assert not record_form("Park Elementary", district=False).plurals
    # A saint's possessive is no plural, nor a saint's own word.
    assert not record_form("St Marys School", district=False).plurals
    assert not record_form("STS. PETER & PAUL SCHOOL", district=False).plurals
    # An apostrophe's, and one NCES writes as a space.
    assert record_form("Kings Academy", district=False).plurals == frozenset({"king"})
    assert record_form("King's Academy", district=False).possessives == frozenset({"king"})
    terry = record_form("TERRY S MONTESSORI SCHOOL", district=False)
    assert "terry" in terry.possessives


def test_initials_run_together_as_one_word() -> None:
    assert record_form("F. C. Boydby School", district=False).letters == ("fc",)
    assert record_form("W W Walkby Elem School", district=False).letters == ("ww",)
    assert record_form("Walkby School", district=False).letters == ()
