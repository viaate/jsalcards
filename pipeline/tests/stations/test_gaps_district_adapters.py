"""Part 4's district-level adapters (GOHSEP, Apptegy, Smart Sites, Finalsite) on fixtures.

Every fixture in fixtures/gaps/gohsep/, apptegy/, smartsites/ and finalsite/ is a real body
(see the folder's README and PROVENANCE.json). Bodies named ``SYNTHETIC_*`` are
made up here, confined to these tests, and exercise the refusals and edge cases.
"""

import json
import re
from typing import Any

import pytest

from snowlight.sources.stations import (
    apptegy,
    finalsite,
    gap_fixtures,
    gap_markup,
    gohsep,
    smartsites,
)
from snowlight.sources.stations.model import ListingState, ShapeError
from snowlight.sources.stations.registry import load_registry

FOLDER = gap_fixtures.DEFAULT_FOLDER


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


# GOHSEP ---------------------------------------------------------------------------


def test_the_live_parish_layer_lists_every_parish_on_every_date() -> None:
    listing = gohsep.parse(_body("gohsep/query-live-20260927.json"))
    assert listing.variant == gohsep.VARIANT
    assert listing.state is ListingState.POPULATED
    assert len(listing.rows) == 640
    assert len({row.extra["geoid"] for row in listing.rows}) == 64
    statuses: dict[str, int] = {}
    for row in listing.rows:
        statuses[row.status] = statuses.get(row.status, 0) + 1
    assert statuses == {"Open": 627, "Closed": 11, "Early Dismissal": 1, "Planned Closure": 1}
    closed = sorted(
        (row.name, row.extra["closure_date"]) for row in listing.rows if row.status == "Closed"
    )
    assert closed == [
        ("Ascension", "2026-06-18"),
        ("Cameron", "2026-09-01"),
        ("Jefferson", "2026-06-18"),
        ("Pointe Coupee", "2026-06-18"),
        ("St. Bernard", "2026-06-18"),
        ("St. Mary", "2026-06-18"),
        ("St. Tammany", "2026-06-18"),
        ("Washington", "2026-06-18"),
        ("West Baton Rouge", "2026-06-18"),
        ("West Carroll", "2026-06-17"),
        ("West Feliciana", "2026-06-18"),
    ]


def test_a_parish_row_keeps_its_raw_fields() -> None:
    listing = gohsep.parse(_body("gohsep/query-live-20260927.json"))
    cameron = next(r for r in listing.rows if r.name == "Cameron" and r.status == "Closed")
    assert cameron.updated_text is None
    assert cameron.extra == {
        "geoid": "22023",
        "objectid": 12,
        "date_group": 1,
        "closure_date_ms": 1788238800000,
        "closure_date": "2026-09-01",
    }


def test_the_registered_parishes_are_the_layers() -> None:
    station = load_registry().stations["gohsep-parish-schools"]
    listing = gohsep.parse(_body("gohsep/query-live-20260927.json"))
    assert station.counties is not None
    assert sorted({str(r.extra["geoid"]) for r in listing.rows}) == list(station.counties.fips)
    assert len(station.leaids) == 64
    assert all(leaid.startswith("22") for leaid in station.leaids)


def _answer(features: list[dict[str, Any]], **extra: Any) -> bytes:
    fields = [{"name": n} for n in ("OBJECTID", "GEOID", "NAME", "STATUS", "CLOSURE_DATE")]
    return json.dumps({"fields": fields, "features": features, **extra}).encode()


SYNTHETIC_EMPTY = _answer([])
SYNTHETIC_FEATURE = {
    "attributes": {
        "OBJECTID": 1,
        "GEOID": "22001",
        "NAME": "Acadia",
        "STATUS": "Closed",
        "CLOSURE_DATE": 1781758800000,
    }
}


def test_an_answer_with_no_features_is_an_empty_list() -> None:
    listing = gohsep.parse(SYNTHETIC_EMPTY)
    assert listing.state is ListingState.EMPTY
    assert listing.rows == ()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"<html>maintenance</html>", "not a JSON answer"),
        (json.dumps({"error": {"code": 400, "message": "Invalid"}}).encode(), "answered an error"),
        (_answer([SYNTHETIC_FEATURE], exceededTransferLimit=True), "partial page"),
        (json.dumps({"fields": [], "features": []}).encode(), "lacks the fields"),
        (json.dumps([1, 2]).encode(), "not a JSON object"),
        (
            _answer([{"attributes": {**SYNTHETIC_FEATURE["attributes"], "GEOID": "481"}}]),
            "no parish code",
        ),
        (
            _answer([{"attributes": {**SYNTHETIC_FEATURE["attributes"], "GEOID": "48001"}}]),
            "not in Louisiana",
        ),
        (
            _answer([{"attributes": {**SYNTHETIC_FEATURE["attributes"], "CLOSURE_DATE": "x"}}]),
            "not epoch milliseconds",
        ),
        (_answer([{"geometry": {}}]), "no attributes"),
    ],
)
def test_other_answers_are_refused(body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        gohsep.parse(body)


# Apptegy --------------------------------------------------------------------------


def test_a_published_banner_is_a_row() -> None:
    listing = apptegy.parse(_body("apptegy/lake-live-20260927.html"))
    assert listing.variant == apptegy.NUXT_STATE
    assert listing.state is ListingState.POPULATED
    assert [(r.name, r.status) for r in listing.rows] == [
        ("Lake County Schools", "School Board names Chad Farnsworth next Superintendent")
    ]
    assert listing.rows[0].extra["style"] == "banner"
    assert listing.rows[0].extra["banner"] == "separate"
    assert listing.rows[0].extra["host"] == "www.lake.k12.fl.us"


@pytest.mark.parametrize(
    "name", ["apptegy/hillsborough-live-20260927.html", "apptegy/martin-live-20260927.html"]
)
def test_banners_not_shown_are_not_rows(name: str) -> None:
    listing = apptegy.parse(_body(name))
    assert listing.state is ListingState.EMPTY
    assert listing.rows == ()
    assert listing.skipped_rows == 0


def test_a_banner_with_no_words_is_skipped() -> None:
    listing = apptegy.parse(_body("apptegy/fremont25-live-20260927.html"))
    assert listing.state is ListingState.EMPTY
    assert listing.skipped_rows == 1


def _page(table: list[Any]) -> bytes:
    script = f'<script type="application/json" id="__NUXT_DATA__">{json.dumps(table)}</script>'
    return f"<html><body>{script}</body></html>".encode()


def _synthetic(flag: bool | None, config: dict[str, Any], banners: list[dict[str, Any]]) -> bytes:
    """A made-up state in devalue's flat form, shaped like an Apptegy page's."""
    table: list[Any] = []

    def put(value: Any) -> int:
        table.append(None)
        index = len(table) - 1
        if isinstance(value, dict):
            table[index] = {key: put(item) for key, item in value.items()}
        elif isinstance(value, list):
            table[index] = [put(item) for item in value]
        else:
            table[index] = value
        return index

    flags = {} if flag is None else {apptegy.SEPARATE_FLAG: flag}
    root = {
        "pinia": {
            "main": {
                "host": "www.example.test",
                "flags": flags,
                "theme": {"school_name": "Example District", "alert_bg_color": "#000"},
            },
            "alertBanner": {"alertBannerConfig": config, "alertBannerSeparate": banners},
        }
    }
    table.append(["ShallowReactive", 1])
    put(root)
    return _page(table)


SYNTHETIC_BANNERS = [
    {
        "id": 1,
        "content": "<p>Schools <b>closed</b> today</p>",
        "status": "published",
        "style": "banner",
    },
    {"id": 2, "content": "<p>Old closure</p>", "status": "archived", "style": "banner"},
    {"id": 3, "content": "<p>Delay</p>", "status": "published", "style": "light_box"},
]
SYNTHETIC_CONFIG = {"enabled": True, "content": "<p>Single banner</p>"}


def test_the_separate_flag_shows_published_banners_newest_first() -> None:
    listing = apptegy.parse(_synthetic(True, SYNTHETIC_CONFIG, SYNTHETIC_BANNERS))
    assert [(r.status, r.extra["alert_id"]) for r in listing.rows] == [
        ("Delay", 3),
        ("Schools closed today", 1),
    ]
    assert {r.name for r in listing.rows} == {"Example District"}


def test_without_the_separate_flag_the_single_banner_shows() -> None:
    listing = apptegy.parse(_synthetic(False, SYNTHETIC_CONFIG, SYNTHETIC_BANNERS))
    assert [(r.status, r.extra["banner"]) for r in listing.rows] == [("Single banner", "single")]
    off = apptegy.parse(_synthetic(False, {**SYNTHETIC_CONFIG, "enabled": False}, []))
    assert off.state is ListingState.EMPTY


def test_without_any_flag_the_list_shows() -> None:
    listing = apptegy.parse(_synthetic(None, SYNTHETIC_CONFIG, SYNTHETIC_BANNERS))
    assert len(listing.rows) == 2


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"<html><body>Apptegy has moved</body></html>", "no __NUXT_DATA__"),
        (_page([["ShallowReactive", 1], {"pinia": 2}, {}]), "no alert banner store"),
        (
            _page(
                [{"pinia": 1}, {"alertBanner": 2}, {"alertBannerConfig": 3}, {"enabled": 4}, False]
            ),
            "names no organization",
        ),
        (_page([["Mystery", 1], {}]), "unknown form"),
        (_page([{"a": 7}]), "missing entry"),
        (b'<script type="application/json" id="__NUXT_DATA__">{oops</script>', "not JSON"),
    ],
)
def test_other_pages_are_refused(body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        apptegy.parse(body)


def test_the_slice_keeps_the_state_and_reads_the_same() -> None:
    body = _synthetic(True, SYNTHETIC_CONFIG, SYNTHETIC_BANNERS)
    sliced = apptegy.slice_body(b"<html><head><style>x</style></head>" + body)
    assert apptegy.parse(sliced) == apptegy.parse(body)
    assert apptegy.slice_body(sliced) == sliced
    assert apptegy.slice_body(b"<html></html>") == gap_markup.document("")


def test_every_apptegy_station_is_a_district_source() -> None:
    registry = load_registry()
    stations = [s for s in registry.stations.values() if s.platform == "apptegy"]
    # 86 in Florida and the mountain states, 33 in South Texas, South Lemhi (ID) of round 3,
    # 5 in the Mobile - Pensacola market (4 in Alabama, Santa Rosa FL) and 10 in the other
    # gap counties (MT, MI, OH, CA) of round 4
    assert len(stations) == 135
    for station in stations:
        # One district, or a Montana town's elementary and high school districts, which
        # the NCES LEA directory lists with the same website.
        assert 1 <= len(station.leaids) <= 2, station.id
        assert station.page_url in station.archive_urls
        assert station.data_url is None
    corvallis = registry.stations["apptegy-corvallis-mt"]
    assert corvallis.leaids == ("3007410",)
    hardin = registry.stations["apptegy-hardin-mt"]
    assert hardin.leaids == ("3013310", "3013340")  # Hardin Elem and Hardin H S
    assert hardin.counties is not None
    assert "lists with this website (hardin.k12.mt.us)" in hardin.counties.source


# ParentSquare Smart Sites -----------------------------------------------------------


def test_an_active_popup_alert_is_a_row() -> None:
    listing = smartsites.parse(_body("smartsites/belgrade-popup-alerts-live-20260927.json"))
    assert listing.variant == smartsites.VARIANT
    assert listing.state is ListingState.POPULATED
    (row,) = listing.rows
    assert row.name == (
        "Attention: Parents/Guardians of Special Education Students Born in 1999 & 2000"
    )
    assert row.status.startswith("Were you (or your student) born in 1999 or 2000")
    assert "\r" not in row.status
    assert row.updated_text == "57 days ago"
    assert row.extra == {
        "alert_id": 10611,
        "link": "https://www.bsd44.org/261242_3",
        "link_text": "Click HERE to learn more",
        "force_district_redirect": False,
        "district_url": None,
    }


def test_no_active_alert_is_an_empty_list() -> None:
    listing = smartsites.parse(_body("smartsites/orange-popup-alerts-live-20260927.json"))
    assert listing.state is ListingState.EMPTY
    assert listing.rows == ()


def test_an_alert_without_a_title_is_named_by_its_message() -> None:
    body = json.dumps(
        {
            "alerts": [{"id": 1, "title": "", "message": "Schools closed"}, {"id": 2}],
            "districtUrl": None,
        }
    ).encode()
    listing = smartsites.parse(body)
    assert [(r.name, r.status) for r in listing.rows] == [("Schools closed", "")]
    assert listing.skipped_rows == 1


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"<!DOCTYPE html><html>Sign in</html>", "not a JSON answer"),
        (b'{"items": []}', "no alerts list"),
        (b'{"alerts": [{"title": "x"}]}', "no numeric id"),
        (b'{"alerts": ["x"]}', "not an object"),
        (b'{"alerts": [], "districtUrl": 5}', "districtUrl"),
        (b'{"alerts": [{"id": 1, "title": 5}]}', "not text"),
    ],
)
def test_other_popup_answers_are_refused(body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        smartsites.parse(body)


def test_every_smartsites_station_reads_its_sites_alerts_file() -> None:
    stations = [s for s in load_registry().stations.values() if s.platform == "smartsites"]
    # 19, 17 in South Texas, Fremont #38 (WY) of round 3, and Orange Beach (AL) and 4 in the
    # other gap counties (OH, MS, CA) of round 4
    assert len(stations) == 42
    for station in stations:
        assert station.page_url is not None
        assert station.data_url == station.page_url + "api/popup-alerts"
        assert station.leaids, station.id


# Finalsite --------------------------------------------------------------------------


def test_a_page_pop_is_a_row() -> None:
    listing = finalsite.parse(_body("finalsite/great-falls-page-pops-live-20260927.html"))
    assert listing.variant == finalsite.POPS
    assert listing.state is ListingState.POPULATED
    (row,) = listing.rows
    assert row.name == (
        "Important Notice Regarding Settlement Agreement between MT OPI and C. DuPuis-Pablo"
    )
    assert row.status.startswith("Please review the attached Class Notice")
    assert row.status.endswith("MT OPI - ACLU of MT Settlement 3319_001")
    assert row.updated_text == "2026-09-10T13:16:49-06:00"
    assert row.extra == {
        "pop_id": 12,
        "visible_at": "2026-09-10T13:16:49-06:00",
        "hidden_at": "2026-10-31T22:30:00-06:00",
        "reset_at": None,
        "delay_option": None,
        "image_alt": None,
    }


def test_a_page_pops_style_block_is_not_text() -> None:
    listing = finalsite.parse(_body("finalsite/broward-page-pops-live-20260927.html"))
    (row,) = listing.rows
    assert row.name == "Notice"
    assert row.status == (
        "Learn more about the Secure the Next Generation Referendum at "
        "browardschools.com/referendum2026 ."
    )


def test_no_page_pop_is_an_empty_body() -> None:
    listing = finalsite.parse(_body("finalsite/billings-page-pops-live-20260927.html"))
    assert listing.variant == finalsite.NONE
    assert listing.state is ListingState.EMPTY
    assert finalsite.parse(b'<div id="fsPagePopCollection" hidden></div>').state is (
        ListingState.EMPTY
    )


def test_an_image_only_page_pop_is_named_by_its_alt_text() -> None:
    body = (
        b'<div id="fsPagePopCollection" hidden><article class="fsPagePop" data-id="7">'
        b'<h2 class="fsPagePopTitle"></h2><div class="fsPagePopMessage">'
        b'<img alt="Schools closed Friday"></div></article>'
        b'<article class="fsPagePop" data-id="8"><h2 class="fsPagePopTitle"></h2></article></div>'
    )
    listing = finalsite.parse(body)
    assert [(r.name, r.status, r.extra["image_alt"]) for r in listing.rows] == [
        ("Schools closed Friday", "", "Schools closed Friday")
    ]
    assert listing.skipped_rows == 1


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"<!DOCTYPE html><html><body>Sign in</body></html>", "not a Finalsite page"),
        (b'{"pops": []}', "JSON, not a Finalsite page"),
        (b"<div class='somethingElse'>x</div>", "no fsPagePopCollection"),
        (
            b'<div id="fsPagePopCollection"><article class="fsPagePop"><h2>x</h2></article></div>',
            "no data-id",
        ),
    ],
)
def test_other_page_pop_answers_are_refused(body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        finalsite.parse(body)


def test_every_finalsite_station_reads_its_homepages_page_pops() -> None:
    stations = [s for s in load_registry().stations.values() if s.platform == "finalsite"]
    # 30, 29 in South Texas and Clark County (ID) of round 3, and 8 in Alabama and 14 in the
    # other gap counties (MT, OH, MS, CA) of round 4
    assert len(stations) == 82
    for station in stations:
        assert station.page_url is not None
        # Read through the homepage (round 5): no data URL, so the poller reads the page
        # and follows its own data-pageid; the browser check pins the address it asks for.
        assert station.data_url is None
        assert station.poll_url == station.page_url
        check = station.page_check
        assert check is not None, station.id
        assert check.page == station.page_url
        (address,) = check.loads
        # The page-pops script asks /fs/pages/<data-pageid>/page-pops of the page's own site.
        origin = "/".join(station.page_url.split("/")[:3])
        assert re.fullmatch(re.escape(origin) + r"/fs/pages/[0-9]+/page-pops", address)
        assert [(f.url, f.loaded_by) for f in station.list_files] == [(address, "script")]
        assert {address, station.page_url} <= set(station.archive_urls)
        assert station.leaids, station.id


# South Texas (round 3) ------------------------------------------------------------------


def test_corpus_christis_live_banner_is_a_row() -> None:
    listing = apptegy.parse(_body("apptegy/corpus-christi-live-20260928.html"))
    assert listing.variant == apptegy.NUXT_STATE
    assert listing.state is ListingState.POPULATED
    assert [row.name for row in listing.rows] == ["CORPUS CHRISTI INDEPENDENT SCHOOL DISTRICT"]
    row = listing.rows[0]
    assert row.status.startswith(
        "Stay connected with Corpus Christi ISD by downloading our free mobile app"
    )
    assert row.updated_text is None
    assert row.extra["alert_id"] == 25919
    assert row.extra["host"] == "www.ccisd.us"


def test_brownsvilles_three_hiring_light_boxes_are_rows() -> None:
    listing = apptegy.parse(_body("apptegy/brownsville-live-20260928.html"))
    assert listing.state is ListingState.POPULATED
    assert [row.name for row in listing.rows] == ["Brownsville ISD"] * 3
    assert [row.extra["alert_id"] for row in listing.rows] == [46968, 46883, 45453]
    assert {row.extra["style"] for row in listing.rows} == {"light_box"}
    assert listing.rows[0].status.startswith("Now Hiring Special Education Teachers!")
    assert listing.rows[2].extra["image_alt"] == "librarians"


def test_tuloso_midways_public_notice_is_a_row() -> None:
    listing = smartsites.parse(_body("smartsites/tuloso-midway-popup-alerts-live-20260928.json"))
    assert listing.state is ListingState.POPULATED
    assert [row.name for row in listing.rows] == [
        "Notice of Public Meeting and Opportunity for Public Testimony Regarding Senate Bill 12 "
        "Compliance Certification"
    ]
    assert listing.rows[0].updated_text == "6 days ago"
    assert listing.rows[0].extra["alert_id"] == 11703


def test_south_texas_isds_two_page_pops_are_rows() -> None:
    listing = finalsite.parse(_body("finalsite/south-texas-page-pops-live-20260928.html"))
    assert listing.variant == finalsite.POPS
    assert [row.name for row in listing.rows] == ["STISD Announcements", "CTE at STISD"]
    assert [row.updated_text for row in listing.rows] == [
        "2026-08-15T19:00:00-05:00",
        "2025-07-23T08:49:00-05:00",
    ]
    assert [row.extra["pop_id"] for row in listing.rows] == [912, 882]


def test_psjas_empty_page_pops_answer_is_an_empty_list() -> None:
    listing = finalsite.parse(_body("finalsite/psja-page-pops-live-20260928.html"))
    assert listing.variant == finalsite.NONE
    assert listing.state is ListingState.EMPTY
    assert listing.rows == ()


@pytest.mark.parametrize(
    ("station_id", "leaids", "fips"),
    [
        # Nueces, Cameron and Hidalgo: the largest districts of the three South Texas
        # counties no list reached, each by the site the NCES LEA directory names for it.
        ("apptegy-corpus-christi-tx", ("4815270",), ("48355",)),
        ("apptegy-brownsville-tx", ("4811680",), ("48061",)),
        ("apptegy-mcallen-tx", ("4829670",), ("48215",)),
        ("finalsite-psja-tx", ("4834860",), ("48215",)),
        ("smartsites-harlingen-tx", ("4822530",), ("48061",)),
        ("smartsites-la-joya-tx", ("4826130",), ("48215",)),
        ("finalsite-south-texas-tx", ("4837150",), ("48061", "48215")),
    ],
)
def test_the_south_texas_district_sources(
    station_id: str, leaids: tuple[str, ...], fips: tuple[str, ...]
) -> None:
    station = load_registry().stations[station_id]
    assert station.leaids == leaids
    assert station.states == ("TX",)
    assert station.counties is not None
    assert station.counties.basis.value == "district"
    assert station.counties.fips == fips
    assert "NCES CCD 2024-25 LEA directory" in station.counties.source
    assert station.robots
    assert all(check.allowed for check in station.robots)


def test_leons_blackboard_homepage_on_the_debby_closing_is_read() -> None:
    """Leon County's homepage before its Smart Sites site, on 2024-08-05 (run 36361209861)."""
    listing = smartsites.parse(_body("smartsites/leon-home-20240805.html"))
    assert listing.variant == "schoolwires-important-announcements"
    assert [row.name for row in listing.rows] == ["Leon County Schools"]
    assert listing.rows[0].status.startswith(
        "All LCS offices and schools will be closed, Monday, August 5th 2024 Due to TS Debby"
    )
    assert listing.rows[0].extra["flex_id"] == "203957"


def test_hamiltons_phone_trouble_banner_is_a_row() -> None:
    """Hamilton (MT) on 2025-02-16, near a winter-warning day: a banner, not a closing."""
    listing = apptegy.parse(_body("apptegy/hamilton-20250216.html"))
    assert listing.state is ListingState.POPULATED
    assert [row.name for row in listing.rows] == ["Hamilton School District #3"]
    assert listing.rows[0].status.startswith("We are experiencing intermittent phone issues")
    assert listing.rows[0].extra["alert_id"] == 19846
