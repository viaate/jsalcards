"""Unit tests for reading the state a listing writes beside its name.

The listings are written the way closings lists write them; they are test
inputs, and no record is looked up here.
"""

import pytest

from snowlight.match.states import StateMention, category_states, spelled_in, state_mentions


def _market(states: str) -> frozenset[str]:
    return frozenset(states.split(","))


def _beside(listing: str, market: str) -> list[StateMention]:
    return [m for m in state_mentions(listing, _market(market)) if m.beside and m.in_market]


@pytest.mark.parametrize(
    ("listing", "market", "state", "texts"),
    [
        # Bare, before the designator or the level.
        ("Salem MA Public", "MA,NH", "MA", ("Salem Public",)),
        ("Madison County NC Schools", "NC,SC,GA", "NC", ("Madison County Schools",)),
        ("Pocahontas Co. WV Schools", "VA,WV", "WV", ("Pocahontas Co. Schools",)),
        ("Kansas City MO Public Schools", "MO,KS", "MO", ("Kansas City Public Schools",)),
        ("Kansas City KS USD500", "MO,KS", "KS", ("Kansas City USD500",)),
        ("Collinsville TX I.S.D.", "TX,OK", "TX", ("Collinsville I.S.D.",)),
        ("Harrisonville Cass MO R-IX School", "MO,KS", "MO", ("Harrisonville Cass R-IX School",)),
        ("Lincoln Central PA Schools", "PA,OH", "PA", ("Lincoln Central Schools",)),
        (
            "Tonganoxie KS Schools - USD 464",
            "MO,KS",
            "KS",
            ("Tonganoxie Schools - USD 464",),
        ),
        (
            "Kansas City KS Public Schools-USD 500",
            "MO,KS",
            "KS",
            ("Kansas City Public Schools-USD 500",),
        ),
        ("Kansas City KS-USD 500", "MO,KS", "KS", ("Kansas City - USD 500",)),
        # In brackets, after a comma, after a hyphen.
        ("Salem Public (MA)", "MA,NH", "MA", ("Salem Public",)),
        ("Collinsville (TX) ISD", "TX,OK", "TX", ("Collinsville ISD",)),
        ("Knox County, TN Schools", "TN,KY", "TN", ("Knox County Schools",)),
        ("WASHINGTON COUNTY SCHOOLS-KY", "TN,KY", "KY", ("WASHINGTON COUNTY SCHOOLS",)),
        ("MADISON SCHOOLS-IN", "IN,KY", "IN", ("MADISON SCHOOLS",)),
        ("Holly Springs, MS", "TN,MS", "MS", ("Holly Springs",)),
        ("Salem Public - MA (Closed)", "MA,NH", "MA", ("Salem Public (Closed)",)),
        ("Salem MA - All Schools", "MA,NH", "MA", ("Salem - All Schools",)),
        # A newspaper abbreviation, and a state's name.
        ("Salem, Ark.", "MO,AR", "AR", ("Salem",)),
        ("Salem, Mass. - All Schools", "MA,NH", "MA", ("Salem - All Schools",)),
        ("Kansas City, Kansas Public Schools", "MO,KS", "KS", ("Kansas City Public Schools",)),
        ("Escambia County, Florida schools", "FL,AL", "FL", ("Escambia County schools",)),
        # With the town in brackets, either side of the state.
        (
            "Lincoln Elementary (Leavenworth, KS)",
            "MO,KS",
            "KS",
            ("Lincoln Elementary (Leavenworth)",),
        ),
        (
            "Lincoln Elementary (KS, Leavenworth)",
            "MO,KS",
            "KS",
            ("Lincoln Elementary (Leavenworth)",),
        ),
        # A region word after a name's word ends the name.
        ("Mill Ave Middle KY", "KY,TN", "KY", ("Mill Ave Middle",)),
        ("Lincoln Elementary East MO", "MO,KS", "MO", ("Lincoln Elementary East",)),
        # A qualifier after the state, before the designator.
        ("Norton, VA City Schools", "VA,TN", "VA", ("Norton City Schools",)),
        ("Bristol TN City Schools", "VA,TN", "TN", ("Bristol City Schools",)),
        # A code that is also a word, after a county's word and before a designator.
        ("Randolph Co. AL Schools", "GA,AL", "AL", ("Randolph Co. Schools",)),
        ("Harrison County MS Schools", "MS,AL", "MS", ("Harrison County Schools",)),
        ("Lincoln Parish LA Schools", "LA,AR", "LA", ("Lincoln Parish Schools",)),
        # A state's name between a name's word and a designator, as a city's
        # schools call themselves; or before the name's qualifier.
        ("Kansas City Kansas Public Schools", "MO,KS", "KS", ("Kansas City Public Schools",)),
        ("Bristol Virginia Public Schools", "TN,VA", "VA", ("Bristol Public Schools",)),
        ("Bristol Tennessee City Schools", "TN,VA", "TN", ("Bristol City Schools",)),
        ("Texarkana Arkansas Public Schools", "TX,AR", "AR", ("Texarkana Public Schools",)),
    ],
)
def test_a_state_beside_the_name_is_read_and_left_out(
    listing: str, market: str, state: str, texts: tuple[str, ...]
) -> None:
    mentions = _beside(listing, market)
    assert [(m.state, m.texts) for m in mentions] == [(state, texts)]


@pytest.mark.parametrize(
    ("listing", "state", "texts"),
    [
        # The town after a name's last word is set apart, and when it repeats the
        # name's own town the name is read without it too.
        (
            "Holden R-III School Holden MO",
            "MO",
            ("Holden R-III School - Holden", "Holden R-III School"),
        ),
        ("Ballard R-II School Butler MO", "MO", ("Ballard R-II School - Butler",)),
        (
            "Liberty Schools 53 Liberty MO",
            "MO",
            ("Liberty Schools 53 - Liberty", "Liberty Schools 53"),
        ),
        (
            "Paola Schools - USD 368 Paola KS",
            "KS",
            ("Paola Schools - USD 368 - Paola", "Paola Schools - USD 368"),
        ),
        ("Livingston Co. R-III School, Chula, MO", "MO", ("Livingston Co. R-III School, Chula",)),
        ("Emerson Elementary Larkstead MO", "MO", ("Emerson Elementary - Larkstead",)),
        (
            "Holden R-III School Holden MO - All Schools",
            "MO",
            ("Holden R-III School - Holden - All Schools", "Holden R-III School - All Schools"),
        ),
        # Not a town: a word of the name, a region word alone, too many words.
        ("Crest Ridge R-7 School MO", "MO", ("Crest Ridge R-7 School",)),
        ("Kearney R-I School North MO", "MO", ("Kearney R-I School North",)),
        (
            "Ozark R-VI School Big Lake Point Farms MO",
            "MO",
            ("Ozark R-VI School Big Lake Point Farms",),
        ),
        ("Holden R-III School 42 MO", "MO", ("Holden R-III School 42",)),
    ],
)
def test_the_kansas_city_form_sets_the_town_apart(
    listing: str, state: str, texts: tuple[str, ...]
) -> None:
    mentions = _beside(listing, "MO,KS")
    assert [(m.state, m.texts) for m in mentions] == [(state, texts)]


@pytest.mark.parametrize(
    ("listing", "texts"),
    [
        # The state between the name and its town.
        ("Shawnee R-3 MO Chilhowee", ("Shawnee R-3 - Chilhowee",)),
        ("Holden R-III MO Holden", ("Holden R-III - Holden", "Holden R-III")),
        (
            "Holden R-III School MO Holden - Closed",
            ("Holden R-III School - Holden - Closed", "Holden R-III School - Closed"),
        ),
        ("Lincoln Elementary MO Lee's Summit", ("Lincoln Elementary - Lee's Summit",)),
    ],
)
def test_a_state_before_the_town_sets_the_town_apart(listing: str, texts: tuple[str, ...]) -> None:
    mentions = _beside(listing, "MO,KS")
    assert [(m.state, m.texts, m.firm) for m in mentions] == [("MO", texts, True)]


@pytest.mark.parametrize(
    "listing",
    [
        # Not after the end of a name, not in capitals, not a town, or more after it.
        "Shawnee MO Chilhowee",
        "Shawnee R-3 Mo Chilhowee",
        "Shawnee R-3 MO Chilhowee Lake Farm Area",
        "Shawnee R-3 MO Chilhowee - Lincoln Elementary",
    ],
)
def test_a_state_before_no_town_is_not_read(listing: str) -> None:
    assert _beside(listing, "MO,KS") == []


@pytest.mark.parametrize(
    ("listing", "market"),
    [
        # Codes that are words or abbreviations, after a name's word.
        ("Germantown MS", "TN,MS"),
        ("DOUGLAS CO SCHOOLS", "CO"),
        ("Brandon Valley SD", "SD"),
        ("Salem Ma Public", "MA,NH"),
        # Hyphens and slashes join a name.
        ("Put-In-Bay Local Schools", "OH,IN"),
        ("Westfield-Washington Schools", "IN,WA"),
        ("COMMUNITY ACTION SCHOOL-MS 258", "NY,MS"),
        ("PS/MS 498", "NY,MS"),
        ("Freeland El/MS", "MI,MS"),
        # A code that is also a word, after a county's word, that ends the listing.
        ("Harrison County MS", "MS,AL"),
        ("Douglas Co SD", "SD,NE"),
        ("Harrison County Ms Schools", "MS,AL"),
        # A code before another word of a name.
        ("GST MI Works", "MI"),
        ("Johnson County KS Meals on Wheels", "MO,KS"),
        ("Winston-Salem VA Outpatient Clinic", "NC,VA"),
        # A state's name that begins a town's or a school's, or comes after a
        # separator before a town's word ("Kansas City").
        ("Kansas City Public Schools", "MO,KS"),
        ("Lincoln - Kansas City Public Schools", "MO,KS"),
        ("Missouri City Schools", "TX,MO"),
        ("Booker Washington Carver Schools", "WA,OR"),
        ("Iowa City Schools", "IA"),
        ("Iowa School for the Deaf", "IA"),
        ("Tacoma - Washington Elementary", "WA,OR"),
        # A code or an abbreviation that shortens a word, first.
        ("MS School for the Blind", "MS"),
        ("Miss. School for the Blind", "MS"),
    ],
)
def test_no_state_where_none_stands_beside_the_name(listing: str, market: str) -> None:
    assert state_mentions(listing, _market(market)) == ()


@pytest.mark.parametrize(
    ("listing", "market", "state", "text"),
    [
        (
            "Southern NH Montessori Academy",
            "NH,MA",
            "NH",
            "Southern New Hampshire Montessori Academy",
        ),
        ("Western PA School for the Deaf", "PA", "PA", "Western Pennsylvania School for the Deaf"),
        ("Western Pa. School for the Deaf", "PA", "PA", "Western Pennsylvania School for the Deaf"),
        ("TN School for the Deaf", "TN", "TN", "Tennessee School for the Deaf"),
        ("MID-MI Leadership Academy", "MI", "MI", "MID-Michigan Leadership Academy"),
        ("Railroad Museum of PA", "PA", "PA", "Railroad Museum of Pennsylvania"),
        (
            "Young Scholars of Western Pennsylvania Charter School",
            "PA",
            "PA",
            "Young Scholars of Western PA Charter School",
        ),
        ("Montessori School of Central Vermont", "VT", "VT", "Montessori School of Central VT"),
        (
            "Easter Seals School- Western Pennsylvania",
            "PA",
            "PA",
            "Easter Seals School- Western PA",
        ),
    ],
)
def test_a_state_in_a_name_is_spelled_the_other_way(
    listing: str, market: str, state: str, text: str
) -> None:
    mentions = state_mentions(listing, _market(market))
    assert [(m.state, m.texts, m.beside) for m in mentions] == [(state, (text,), False)]


def test_a_state_in_a_name_outside_the_market_is_not_read() -> None:
    assert state_mentions("Southern NH Montessori Academy", _market("MA,VT")) == ()


@pytest.mark.parametrize(
    ("listing", "firm"),
    [
        ("Salem MA Public", True),
        ("Salem Public (MA)", True),
        ("Salem, Mass.", True),
        ("Knox County, Tennessee Schools", True),
        ("Holly Springs, MS", True),
        ("Germantown (MS)", True),
        ("MADISON SCHOOLS-IN", False),
        ("Capital City PCS - MS", False),
        ("Kansas City - Kansas Public Schools", False),
        ("Kansas City Kansas Public Schools", False),
        ("Bristol Tennessee City Schools", False),
    ],
)
def test_firm_says_whether_the_listing_can_name_no_other_state(listing: str, firm: bool) -> None:
    (mention,) = state_mentions(listing, _market("MA,TN,MS,IN,KS"))
    assert mention.firm is firm


@pytest.mark.parametrize(
    ("listing", "state"),
    [
        ("Salem MA Public", "MA"),
        ("Salem Public (Maine)", "ME"),
        ("Knox County Schools, TN", "TN"),
        ("Salem, Mass.", "MA"),
        ("Collinsville (OK) Public Schools", "OK"),
    ],
)
def test_a_state_outside_the_market_is_mentioned_only_to_rule_the_market_out(
    listing: str, state: str
) -> None:
    (mention,) = state_mentions(listing, _market("NH,KY,TX"))
    assert mention.state == state
    assert not mention.in_market
    assert mention.firm
    assert mention.texts == ()


@pytest.mark.parametrize(
    "listing",
    ["Salem Ma Public", "Salem Public - ME", "Salem SD", "Germantown MS", "Salem Public - Ind."],
)
def test_a_loose_state_outside_the_market_is_not_mentioned(listing: str) -> None:
    assert state_mentions(listing, _market("NH")) == ()


def test_the_same_state_twice_is_one_mention() -> None:
    mentions = state_mentions("Salem MA Public (MA)", _market("MA,NH"))
    assert {m.state for m in mentions} == {"MA"}
    assert all(m.beside for m in mentions)


def test_a_mention_says_the_state_after_the_word_before_it() -> None:
    (mention,) = state_mentions("Evergreen Montessori School - AR", _market("CA"))
    assert mention.said == "school ar"
    assert spelled_in("EVERGREEN MONTESSORI SCHOOL - AR", mention)
    assert not spelled_in("Evergreen Montessori School", mention)
    (kansas,) = state_mentions("Kansas City, Kansas Public Schools", _market("MO,KS"))
    assert kansas.said == "city kansas"
    assert not spelled_in("KANSAS CITY 33", kansas)
    (doctor,) = state_mentions("Leonides Cigarroa MD Elementary", _market("TX,MD"))
    assert spelled_in("LEONIDES GONZALEZ CIGARROA MD EL", doctor)


@pytest.mark.parametrize(
    ("category", "market", "states"),
    [
        # A code in capitals, as a word.
        ("RI Public Schools", "MA,RI,CT", {"RI"}),
        ("MA Private Schools", "MA,RI,CT", {"MA"}),
        ("KY Private", "KY,OH,WV", {"KY"}),
        ("WV", "KY,OH,WV", {"WV"}),
        ("Business-KY", "KY,OH,WV", {"KY"}),
        ("Cowlitz Co. & Lower Columbia (WA) Schools", "WA,OR", {"WA"}),
        # A code that is also a word, only where it stands apart.
        ("Schools-IN", "IN,KY,IL", {"IN"}),
        ("SCHOOLS-IN", "IN,KY,IL", {"IN"}),
        ("OH", "KY,OH,WV", {"OH"}),
        ("OH Private", "KY,OH,WV", {"OH"}),
        ("IN Schools", "IN,KY,IL", {"IN"}),
        ("SCHOOLS IN OHIO", "IN,OH", {"OH"}),
        ("Or Schools", "OR,WA", set()),
        # A state's name, unless a county's or a town's word follows it or it
        # ends another state's name.
        ("Kansas", "KS,MO", {"KS"}),
        ("Schools in Indiana", "IN,KY", {"IN"}),
        ("Southern Indiana", "IN,KY", {"IN"}),
        ("DELAWARE", "DE,MD", {"DE"}),
        ("Washington Co. Schools", "WA,OR,PA", set()),
        ("Delaware County", "DE,PA,OH", set()),
        ("Kansas City Schools", "KS,MO", set()),
        ("West Virginia Schools", "VA,WV", {"WV"}),
        ("Virginia", "VA,WV", {"VA"}),
        # Nothing, or a state outside the market.
        ("Schools", "MA,RI", set()),
        ("Closings", "MA,RI", set()),
        (None, "MA,RI", set()),
        ("", "MA,RI", set()),
        ("CT Public Schools", "MA,RI", set()),
        # A code the market holds that no state's name spells (a territory).
        ("PR Schools", "PR,MA", {"PR"}),
        ("Schools", "PR,MA", set()),
        # Two states: the matcher narrows to neither.
        ("MA & RI Schools", "MA,RI", {"MA", "RI"}),
    ],
)
def test_the_states_a_section_names(category: str | None, market: str, states: set[str]) -> None:
    assert category_states(category, _market(market)) == states
