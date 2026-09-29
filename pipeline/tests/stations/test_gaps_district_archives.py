"""Part 4's district sources on their archived storm-day captures, and the older page forms.

Miami-Dade's alerts file shows its Milton closure; the Apptegy adapter reads Nuxt 2
pages (``window.__NUXT__``, 2021 to 2024) and the 2025 layout of the Nuxt 3 state;
the Apptegy and Smart Sites adapters read a district's homepage from before its
move, when it was a Blackboard (Schoolwires) site with the Important Announcement
app; the Pasco adapter reads Pasco's own homepage banner. Every fixture named here
is a real body (fixtures/gaps/README.md gives each one's capture); bodies named
``SYNTHETIC_*`` or built here (``_nuxt2_page``, ``_state``, ``_json``) are made up,
confined to these tests.
"""

import json
from typing import Any

import pytest

from snowlight.sources.stations import (
    apptegy,
    campussuite,
    dadeschools,
    gap_fixtures,
    gap_markup,
    nuxt2,
    pasco,
    schoolwires,
    smartsites,
)
from snowlight.sources.stations.model import ListingState, ShapeError
from snowlight.sources.stations.registry import CountyBasis, load_registry

FOLDER = gap_fixtures.DEFAULT_FOLDER


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


# Apptegy's Nuxt 2 pages (archived) ------------------------------------------------------


def test_martin_county_showed_its_milton_closure_in_the_banner() -> None:
    listing = apptegy.parse(_body("apptegy/martin-20241009.html"))
    assert listing.variant == apptegy.NUXT2_STATE
    assert listing.state is ListingState.POPULATED
    [row] = listing.rows
    assert row.name == "MARTIN COUNTY SCHOOL DISTRICT"
    assert "HURRICANE MILTON UPDATE" in row.status
    assert "closed Wednesday, October 9 - Friday, October 11" in row.status
    assert row.extra["banner"] == "separate"
    assert row.extra["host"] == "www.martinschools.org"


def test_before_the_banner_list_the_single_banner_showed() -> None:
    listing = apptegy.parse(_body("apptegy/martin-20220928.html"))
    [row] = listing.rows
    assert row.extra["banner"] == "single"
    assert row.status.startswith("🌀Hurricane Ian Update - 9/27/22")


def test_hardins_campus_suite_homepage_showed_its_cold_closure() -> None:
    """Hardin (MT) before its Apptegy site: a Campus Suite page (run 36409494144)."""
    listing = apptegy.parse(_body("apptegy/hardin-20221221.html"))
    assert listing.variant == campussuite.VARIANT
    [row] = listing.rows
    assert row.name == "Hardin School District 17H&1"
    assert row.status.startswith(
        "School Closure Wednesday, Dec. 21st 2022: Good Afternoon, Due to the potential of "
        "extreme cold temperatures"
    )
    assert row.extra == {
        "alert_id": "1610039",
        "level": "urgent",
        "link": "https://www.hardin.k12.mt.us/alert/1610039/school-closure-wednesday-dec-21st-2022",
    }


def test_a_campus_suite_banner_widget_with_no_alert_is_an_empty_list() -> None:
    listing = apptegy.parse(_body("apptegy/hardin-20230327.html"))
    assert listing.variant == campussuite.VARIANT
    assert listing.state is ListingState.EMPTY
    sliced = _body("apptegy/hardin-20230327.html")
    assert campussuite.slice_body(sliced) == sliced


SYNTHETIC_CAMPUS_SUITE = b"""<html><head><title>SYNTHETIC District | Home</title></head><body>
<div data-cms-widget="widgets/AlertBanner/AlertBanner" id="w"><div class="cs-alert-banner">
<div class="cs-alert-banner__item cs-alert-banner__item--info"><p class="cs-alert-banner__msg">
<a href="/alert/7/late-start">Two-hour late start</a></p></div>
<div class="cs-alert-banner__item"><p class="cs-alert-banner__msg"> </p></div>
</div></div></body></html>"""


def test_a_campus_suite_alert_without_its_dialog_is_its_headline() -> None:
    listing = campussuite.parse_text(SYNTHETIC_CAMPUS_SUITE.decode())
    [row] = listing.rows
    assert (row.name, row.status) == ("SYNTHETIC District", "Two-hour late start")
    assert row.extra == {"alert_id": "7", "level": "info", "link": "/alert/7/late-start"}
    assert listing.skipped_rows == 1  # the item with no words


def test_a_page_without_the_campus_suite_widget_is_refused() -> None:
    with pytest.raises(ShapeError, match="not a Campus Suite page"):
        campussuite.parse_text("<html><title>SYNTHETIC</title></html>")


def test_drafts_in_a_nuxt2_state_are_not_rows() -> None:
    listing = apptegy.parse(_body("apptegy/putnam-20241012.html"))
    assert listing.variant == apptegy.NUXT2_STATE
    assert listing.state is ListingState.EMPTY


def test_the_2025_nuxt3_layout_keeps_the_banners_in_the_main_store() -> None:
    cassia = apptegy.parse(_body("apptegy/cassia-20250214.html"))
    assert cassia.variant == apptegy.NUXT_STATE
    assert cassia.state is ListingState.EMPTY
    fremont = apptegy.parse(_body("apptegy/fremont25-20251205.html"))
    assert fremont.state is ListingState.EMPTY
    assert fremont.skipped_rows == 1  # a published banner with no words


def _nuxt2_page(flag: str, config: str, banners: str, *, name: str = "Example District") -> bytes:
    """A made-up Nuxt 2 payload shaped like an Apptegy page's (parameters a to e)."""
    script = (
        "window.__NUXT__=(function(a,b,c,d,e){x.menu={style:a};"
        'return {layout:"default",state:{host:"www.example.test",'
        f'theme:{{school_name:"{name}",alert_bg_color:c}},'
        f"flags:{{{apptegy.SEPARATE_FLAG}:{flag}}},"
        f"alertBannerConfig:{config},alertBannerSeparate:{banners}}}}}}}"
        '(false,true,"#000","published",void 0));'
    )
    return f"<html><body><script>{script}</script></body></html>".encode()


SYNTHETIC_BANNERS = (
    '[{id:1,content:"\\u003Cp\\u003EClosed today\\u003C/p\\u003E",status:d,style:"banner"},'
    '{id:2,content:"\\u003Cp\\u003EOld\\u003C/p\\u003E",status:"archived",style:"banner"}]'
)
SYNTHETIC_CONFIG = '{content:"\\u003Cp\\u003ESingle\\u003C/p\\u003E",enabled:b}'


def test_a_nuxt2_state_follows_the_same_choice_as_nuxt3() -> None:
    on = apptegy.parse(_nuxt2_page("b", SYNTHETIC_CONFIG, SYNTHETIC_BANNERS))
    assert [(r.status, r.extra["alert_id"]) for r in on.rows] == [("Closed today", 1)]
    assert on.rows[0].name == "Example District"
    off = apptegy.parse(_nuxt2_page("a", SYNTHETIC_CONFIG, SYNTHETIC_BANNERS))
    assert [(r.status, r.extra["banner"]) for r in off.rows] == [("Single", "single")]


def test_a_nuxt2_page_without_a_banner_store_or_a_name_is_refused() -> None:
    no_store = _nuxt2_page("b", "{}", "[]").replace(b"alertBannerConfig", b"somethingElse")
    no_store = no_store.replace(b"alertBannerSeparate", b"somethingMore")
    with pytest.raises(ShapeError, match="no alert banner store"):
        apptegy.parse(no_store)
    with pytest.raises(ShapeError, match="names no organization"):
        apptegy.parse(_nuxt2_page("b", SYNTHETIC_CONFIG, "[]", name=""))


def test_the_v2_slice_keeps_a_nuxt2_script_and_reads_the_same() -> None:
    body = _body("apptegy/martin-20241009.html")
    assert apptegy.slice_body_v2(body) == body  # the fixture is its own slice
    page = b"<html><head><style>x</style></head>" + _nuxt2_page(
        "b", SYNTHETIC_CONFIG, SYNTHETIC_BANNERS
    )
    sliced = apptegy.slice_body_v2(page)
    assert apptegy.parse(sliced) == apptegy.parse(page)
    assert apptegy.slice_body_v2(sliced) == sliced
    nuxt3 = _body("apptegy/lake-live-20260927.html")
    assert apptegy.slice_body_v2(nuxt3) == apptegy.slice_body(nuxt3)
    assert apptegy.slice_body_v2(b"<html></html>") == gap_markup.document("")


# The Nuxt 2 reader ----------------------------------------------------------------------


def _state(body: str, args: str, params: str = "a,b,c") -> nuxt2.Nuxt2State:
    return nuxt2.read(f"<script>window.__NUXT__=(function({params}){{{body}}}({args}));</script>")


def test_the_reader_binds_parameters_and_reads_literals() -> None:
    state = _state(
        "x.y={k:a};return {v:{n:-1.5,t:!0,f:!1,u:void 0,d:new Date(1700),s:Array(2),"
        "m:c.inner,list:[b,,3]}}",
        '"text",null,{inner:"member"}',
    )
    found, value = state.value("v")
    assert found
    assert value == {
        "n": -1.5,
        "t": True,
        "f": False,
        "u": None,
        "d": 1700,
        "s": [None, None],
        "m": "member",
        "list": [None, None, 3],
    }
    assert state.value("k") == (True, "text")
    assert state.value("missing") == (False, None)


def test_the_reader_scopes_a_key_under_its_parents() -> None:
    state = _state('return {other:{host:"no"},state:{host:"yes"}}', "1")
    assert state.value("host") == (True, "no")
    assert state.value("host", after=("state",)) == (True, "yes")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("<script>var x = 1;</script>", "no window.__NUXT__"),
        ("<script>window.__NUXT__=(function(a){return {v:a}});</script>", "no argument list"),
        ("<script>window.__NUXT__=(function(a){return {v:a}}(1,2));</script>", "more arguments"),
        ("<script>window.__NUXT__=(function(a){return {v:a}}(1 # 2));</script>", "holds"),
    ],
)
def test_the_reader_refuses_what_it_cannot_read(text: str, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        nuxt2.read(text)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("return {v:zz}", "unknown name"),
        ("return {v:new Map()}", "constructs a Map"),
        ("return {v:Array(a)}", "unknown size"),
        ("return {v:-a}", "negates"),
        ("return {v:)}", "where a value"),
    ],
)
def test_a_value_the_reader_cannot_read_is_refused(body: str, message: str) -> None:
    state = _state(body, '"x"', "a")
    with pytest.raises(ShapeError, match=message):
        state.value("v")


# Schoolwires homepages (before a district moved) ----------------------------------------


def test_manatee_showed_its_milton_closure_in_the_important_announcements() -> None:
    listing = apptegy.parse(_body("apptegy/manatee-20241009.html"))
    assert listing.variant == schoolwires.VARIANT
    [row] = listing.rows
    assert row.name == "School District of Manatee County"
    assert row.status.startswith("All SDMC schools are closed to students through Friday 10/9/24.")
    assert row.extra["flex_id"] == "49226"
    assert row.extra["links"] == "https://www.manateeschools.net/storm"


def test_osceola_showed_its_ian_closure_before_its_smart_sites_site() -> None:
    listing = smartsites.parse(_body("smartsites/osceola-home-20220928.html"))
    assert listing.variant == schoolwires.VARIANT
    [row] = listing.rows
    assert row.status.startswith("Schools To Be Closed September 27, September 28")
    empty = smartsites.parse(_body("smartsites/osceola-home-20241010.html"))
    assert empty.state is ListingState.EMPTY


SYNTHETIC_REGION = (
    '<title>Example District / Homepage</title><div class="cs-important-announcements-outer" '
    'data-pmi-id="7"><ul class="cs-important-announcements-list">{items}</ul></div>'
)


def test_a_schoolwires_item_without_words_is_skipped_and_one_without_an_id_refused() -> None:
    blank = SYNTHETIC_REGION.format(
        items='<li class="cs-important-announcement" data-flex-id="1">'
        '<div class="cs-important-announcement-text"><p> </p></div></li>'
    )
    listing = schoolwires.parse_text(blank)
    assert listing.state is ListingState.EMPTY
    assert listing.skipped_rows == 1
    no_id = SYNTHETIC_REGION.format(items='<li class="cs-important-announcement">x</li>')
    with pytest.raises(ShapeError, match="no data-flex-id"):
        schoolwires.parse_text(no_id)
    with pytest.raises(ShapeError, match="not a Schoolwires homepage"):
        schoolwires.parse_text("<html><body>no region</body></html>")
    untitled = SYNTHETIC_REGION.format(items="").replace("Example District / Homepage", "")
    with pytest.raises(ShapeError, match="no title"):
        schoolwires.parse_text(untitled)


def test_the_schoolwires_slice_reads_the_same() -> None:
    body = _body("apptegy/monroe-20241007.html")
    assert schoolwires.slice_body(body) == body
    region = SYNTHETIC_REGION.format(items="")
    page = f"<html><head><style>x</style></head><body>{region}</body></html>"
    sliced = schoolwires.slice_body(page.encode())
    assert schoolwires.parse_text(sliced.decode()) == schoolwires.parse_text(page)
    assert schoolwires.slice_body(b"<html></html>") == gap_markup.document("")


# Pasco -----------------------------------------------------------------------------------


def test_pasco_showed_its_milton_closure_in_the_emergency_banner() -> None:
    listing = pasco.parse(_body("pasco/home-20241009.html"))
    assert listing.variant == pasco.BANNER
    [row] = listing.rows
    assert row.name == "Pasco County Schools"
    assert row.status.startswith("All Schools and District Offices will now be closed")
    assert row.extra["level"] == "red"
    assert row.extra["links"] == "https://www.pasco.k12.fl.us/weather"


def test_pasco_in_2022_used_a_red_rectangle_and_today_shows_none() -> None:
    old = pasco.parse(_body("pasco/home-20221003.html"))
    assert old.variant == pasco.RECTANGLE
    assert old.rows[0].status.startswith("All Pasco County schools and offices will reopen")
    live = pasco.parse(_body("pasco/home-live-20260927.html"))
    assert live.variant == pasco.BANNER
    assert live.state is ListingState.EMPTY


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            b"<html><title>Pasco County Schools</title><body>redesigned</body></html>",
            "no emergency",
        ),
        (
            b"<html><title>Pasco County Schools</title><body>"
            + pasco.MARK.encode()
            + b"<div>nothing</div><!-- next --></body></html>",
            "neither a banner",
        ),
        (
            pasco.MARK.encode() + b'<div class="pcs_emergency_banner_red">x</div><!-- next -->',
            "no title",
        ),
    ],
)
def test_other_pasco_pages_are_refused(body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        pasco.parse(body)


def test_the_pasco_slice_reads_the_same() -> None:
    for name in ("pasco/home-20241009.html", "pasco/home-live-20260927.html"):
        body = _body(name)
        assert pasco.slice_body(body) == body
        assert pasco.parse(pasco.slice_body(body)) == pasco.parse(body)
    assert pasco.slice_body(b"<html></html>") == gap_markup.document("")


def test_pasco_is_a_district_level_source() -> None:
    station = load_registry().stations["pasco-county-fl"]
    assert station.leaids == ("1201530",)
    assert station.counties is not None
    assert station.counties.basis is CountyBasis.DISTRICT
    assert station.counties.fips == ("12101",)
    assert station.page_url in station.archive_urls


def _json(value: Any) -> bytes:
    return json.dumps(value).encode()


def test_a_smart_sites_answer_that_is_neither_json_nor_a_schoolwires_page_is_refused() -> None:
    with pytest.raises(ShapeError, match="not a JSON answer"):
        smartsites.parse(b"<html><body>login</body></html>")
    assert smartsites.parse(_json({"alerts": [], "districtUrl": None})).state is (
        ListingState.EMPTY
    )


# Miami-Dade ------------------------------------------------------------------------------


def test_miami_dade_showed_its_milton_closure_in_the_alerts_file() -> None:
    listing = dadeschools.parse(_body("dadeschools/alerts-20241009.json"))
    assert listing.variant == dadeschools.VARIANT
    [row] = listing.rows
    assert row.name == "Hurricane Milton"
    assert row.status.startswith("All M-DCPS schools, as well as Region and District offices")
    assert row.extra == {"alert_id": 0, "type": "Danger", "clients": "Mobile,Web", "link": None}


def test_miami_dade_keeps_hidden_items_that_are_never_rows() -> None:
    listing = dadeschools.parse(_body("dadeschools/alerts-live-20260927.json"))
    assert listing.state is ListingState.EMPTY
    assert listing.skipped_rows == 0


def test_a_visible_item_with_only_markup_is_read_and_one_with_nothing_skipped() -> None:
    items = [
        {"id": 7, "visible": True, "title": "", "innerHTML": "<p>Schools <b>closed</b></p>"},
        {"id": 8, "visible": True, "title": None, "body": None},
        {"id": 9, "visible": False, "title": "Old"},
    ]
    listing = dadeschools.parse(_json({"items": items}))
    assert [(r.name, r.status) for r in listing.rows] == [("Schools closed", "")]
    assert listing.skipped_rows == 1


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"<html>maintenance</html>", "not a JSON answer"),
        (_json({"alerts": []}), "no items list"),
        (_json({"items": [{"visible": True}]}), "no numeric id"),
        (_json({"items": [{"id": 1, "visible": "yes"}]}), "boolean 'visible'"),
        (_json({"items": [{"id": 1, "visible": True, "title": 5}]}), "is not text"),
        (_json({"items": ["x"]}), "not an object"),
    ],
)
def test_other_alert_answers_are_refused(body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        dadeschools.parse(body)


def test_miami_dade_is_a_district_level_source_read_through_its_alerts_file() -> None:
    station = load_registry().stations["dadeschools-miami-dade-fl"]
    assert station.leaids == ("1200390",)
    assert station.data_url == "https://mainapi.dadeschools.net/api/v1/alerts/"
    assert station.data_url in station.archive_urls
