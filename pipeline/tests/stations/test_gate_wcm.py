"""Older district homepages the gate reads: WCM announcements apps and Google Sites banners.

Every fixture is a real archived homepage (fixtures/gate/, provenance in its
PROVENANCE.json; the folder's Northside ISD fixtures, one of them live, are tested in
test_gate_nisd.py): Clarke County's Announcements app on the day after Hurricane Zeta,
Charlotte County's "Breaking News" headlines app during Tropical Storm Idalia, Duval
County's "Announcements" headlines app during Hurricanes Ian and Helene, Baldwin
County's announcements (populated during Zeta, empty in January 2018) and Collier
County's "District Announcements" during Helene, and Clay County's Google Sites homepage
with its announcement banner during Hurricane Ian and without one during Milton; Socorro
ISD's homepage, whose only app is its "Top Stories" news, defers to its on-screen alert
file (see test_gate_alerts.py for those files) unless its own text shows a closing
(test_gate_text.py). The folder
also keeps the storm-day captures that first proved three station lists the gate asked
the archive for (KTIV's in January 2024, WJET's and WETM's during lake-effect snow and a
nor'easter) and Comal ISD's homepage alert (the January 2025 winter storm's closure),
read by their own adapters, and the SharpSchool homepages and alert answer of Lee and
Marion counties (tested in test_gate_sharpschool.py). The small documents built in a
few tests are synthetic and say so.
"""

import hashlib

import pytest

from snowlight.sources.stations import (
    apptegy,
    finalsite,
    gate_fixtures,
    googlesites,
    notices,
    smartsites,
    wcm,
)
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.gap_markup import document
from snowlight.sources.stations.model import MAX_STATUS, ListingState, ShapeError

FOLDER = gate_fixtures.DEFAULT_FOLDER
ENTRIES = {entry.file: entry for entry in gate_fixtures.load_entries(FOLDER)}
ERRORS = {item.file: item for item in gate_fixtures.load_errors(FOLDER)}
# The sources' own variants, for the captures that proved them.
STATION_VARIANTS = {
    "gray-fusion-orgs",
    "nexstar-page",
    "edlio-homepage-alert",
    "nisd-notices",
    "sharpschool-alerts",
    "sharpschool-slider",
    "sharpschool-homepage",
    "wordpress-smartslider",
    "elementor-alert-widgets",
    "finalsite-homepage",
    "finalsite-homepage-pops",
    "tegna-closings-link",
    "tegna-closings-article",
    # Round 3: the forms the closure-text check found misread, and the Utah districts.
    "cowles-closures-article",
    "cowles-section-cards",
    "sharpschool-banner-slider",
    "homepage-text",
    "tegna-liferay-page",
    "tegna-subindex-page",
    "sinclair-facade-page",
    "district-alerts-empty",
    "wcsd-alerts",
    "district-homepage-text",
    "district-homepage-alerts",
    "district-homepage-alert-loader",
    # Round 3's second pass: an older site alert module.
    "site-alert-module",
    # Round 3, resumed: Scripps' 2017 Liferay layout with no portlet placed.
    "scripps-liferay-empty-layout",
}


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_each_fixture_reads_as_its_provenance_says(name: str) -> None:
    entry = ENTRIES[name]
    body = _body(name)
    assert hashlib.sha256(body).hexdigest() == entry.sha256
    assert len(body) == entry.bytes
    listing = adapter_for(entry.adapter)(body)
    assert listing.variant == entry.expected.variant
    assert listing.variant in {
        wcm.VARIANT,
        wcm.ALERT_PAGE_VARIANT,
        wcm.ALERT_VARIANT,
        googlesites.VARIANT,
        *STATION_VARIANTS,
    }
    assert listing.state is entry.expected.state
    assert tuple(row.name for row in listing.rows) == entry.expected.names
    assert gate_fixtures.SLICERS[entry.slice](body) == body


def test_clarke_announcements_hold_the_zeta_closing() -> None:
    listing = finalsite.parse(_body("wcm/clarke-20201030.html"))
    assert listing.state is ListingState.POPULATED
    first = listing.rows[0]
    assert first.name == "Clarke Co School District"
    assert first.status.startswith(
        "ALL CLARKE COUNTY SCHOOLS ARE CLOSED FRIDAY, 10/30 DUE TO DAMAGE FROM HURRICANE ZETA"
    )
    assert first.extra["app"] == "announcements"
    assert first.extra["app_title"] == "Announcements"
    assert first.extra["module_id"] == "4"
    assert notices.row_qualifies(first.name, first.status, listing.variant)


def test_charlotte_reads_breaking_news_and_not_featured_stories() -> None:
    listing = smartsites.parse(_body("wcm/charlotte-20230830.html"))
    titles = {row.extra["app_title"] for row in listing.rows}
    assert titles == {"Breaking News"}
    assert listing.rows[0].status.startswith("Tropical Storm Idalia Announcement - 8/28/23")
    assert "will be closed on Tuesday, August 29 and Wednesday, August 30" in listing.rows[0].status
    assert all(row.extra["app"] == "headlines" for row in listing.rows)


def test_duval_reads_its_announcements_headlines_only() -> None:
    listing = apptegy.parse(_body("wcm/duval-20220928.html"))
    assert {row.extra["app_title"] for row in listing.rows} == {"Announcements"}
    assert listing.rows[0].status == "Hurricane Ian: Impact on Duval schools"
    helene = apptegy.parse(_body("wcm/duval-20240926.html"))
    assert helene.rows[0].status == "Potential Hurricane Helene: Closure Information and Updates"
    # Comment links are the app's own controls, not the notice's links.
    assert all("Comments=true" not in str(row.extra["links"]) for row in helene.rows)


def test_baldwin_announcements_populated_and_empty() -> None:
    zeta = finalsite.parse(_body("wcm/baldwin-20201029.html"))
    assert any("storm Zeta" in row.status for row in zeta.rows)
    empty = finalsite.parse(_body("wcm/baldwin-20180119.html"))
    assert empty.state is ListingState.EMPTY
    assert empty.variant == wcm.VARIANT


def test_weather_update_headlines_are_not_closings() -> None:
    # Collier's homepage of 2024-10-05: five "Tropical Weather Update" headlines and news;
    # none announces a closing, so the capture proves nothing (the gate of 2026-10-13).
    listing = finalsite.parse(_body("wcm/collier-20241005.html"))
    assert any("Tropical Weather Update" in row.status for row in listing.rows)
    kept = [
        row for row in listing.rows if notices.row_qualifies(row.name, row.status, listing.variant)
    ]
    assert kept == []


def test_a_news_only_homepage_slice_without_its_text_defers_to_its_alert_file() -> None:
    # The wcm-v2 slice keeps no text of the page: read alone it is the deferred page
    # (the whole page, whose Top Stories announce a delayed start, is read as that
    # line beside the alert file: wcm/socorro-text-20220203.html, test_gate_text.py).
    body = _body("wcm/socorro-20220203.html")
    text = body.decode("utf-8", "replace")
    assert not wcm.holds_announcements(text)
    with pytest.raises(ShapeError):
        wcm.parse_text(text)
    listing = apptegy.parse(body)
    assert listing.variant == wcm.ALERT_PAGE_VARIANT
    assert listing.state is ListingState.DEFERRED
    assert listing.follows == (
        "/cms/Tools/OnScreenAlerts/UserControls/OnScreenAlertDialogListWrapper.aspx"
        "?OnScreenAlertCookie=&SiteID=1",
    )
    assert not ERRORS


def _synthetic(inner: str, title: str = "Synthetic District / Homepage") -> str:
    return f"<html><head><title>{title}</title></head><body>{inner}</body></html>"


def _app(kind: str, title: str, articles: str) -> str:
    return (
        f'<div id="module-content-9"><div class="ui-widget app {kind}">'
        f'<div class="ui-widget-header"><h1>{title}</h1></div>'
        f'<div class="ui-widget-detail"><ul class="ui-articles">{articles}</ul></div></div></div>'
    )


def test_synthetic_titles_decide_which_headlines_apps_are_read() -> None:
    article = '<li><div class="ui-article"><h1 class="ui-article-title">Snow day</h1></div></li>'
    for title in ("District Alerts", "Urgent Notices", "Emergency Information", "Important"):
        text = _synthetic(_app("headlines", title, article))
        assert wcm.holds_announcements(text)
        assert wcm.parse_text(text).rows[0].status == "Snow day"
    for title in ("District News", "Top Stories", "Newsroom"):
        assert not wcm.holds_announcements(_synthetic(_app("headlines", title, article)))


def test_synthetic_edge_cases() -> None:
    # An article with neither title nor description keeps its words in its body.
    loose = '<li><div class="ui-article"><span>Closed today</span></div></li>'
    listing = wcm.parse_text(_synthetic(_app("announcements", "", loose)))
    assert listing.rows[0].status == "Closed today"
    assert listing.rows[0].extra["app_title"] is None
    # An article with no words is skipped; a long one is cut to the status limit.
    blank = '<li><div class="ui-article"><div class="ui-article-description"> </div></div></li>'
    long_words = "x" * (MAX_STATUS + 50)
    long_item = (
        f'<li><div class="ui-article"><p class="ui-article-description">{long_words}</p></div></li>'
    )
    listing = wcm.parse_text(_synthetic(_app("announcements", "Notes", blank + long_item)))
    assert listing.skipped_rows == 1
    assert len(listing.rows[0].status) == MAX_STATUS
    assert listing.rows[0].status.endswith("…")
    # No title: no district name to give the rows.
    with pytest.raises(ShapeError, match="no title"):
        wcm.parse_text("<html><body>" + _app("announcements", "A", loose) + "</body></html>")
    # No module wrapper: no module id.
    bare = _synthetic(_app("announcements", "A", loose).removeprefix('<div id="module-content-9">'))
    assert wcm.parse_text(bare).rows[0].extra["module_id"] is None


def test_slice_of_a_page_without_apps_is_empty() -> None:
    assert wcm.slice_body(b"<html><body><p>nothing</p></body></html>") == document("")


def test_a_school_closed_for_good_is_not_a_closing() -> None:
    # Salt Lake City School District's live pop-up alert of 2026-09-29 (a survey on the
    # future of three schools the district closed), not a day's closing.
    title = "Help Decide What's Next for Three Closed Schools"
    status = (
        "The district is working to determine the best future use of three closed schools: "
        "Mary W. Jackson, M. Lynn Bennion, and Hawthorne."
    )
    assert not notices.announces_closing(status, title)
    assert not notices.announces_closing("Closed school buildings will be sold")
    assert not notices.announces_closing("Hawthorne Elementary will permanently close in June")
    assert notices.announces_closing("All district schools are closed Monday")
    assert notices.announces_closing("School Closure: All schools closed Tuesday January 21")


def test_clay_google_sites_banner_announces_the_ian_closing() -> None:
    listing = apptegy.parse(_body("googlesites/clay-20220928.html"))
    assert listing.variant == googlesites.VARIANT
    (row,) = listing.rows
    assert row.name == "Clay County District Schools, Florida"
    assert row.status == (
        "All Clay County Schools and the district offices will officially be closed "
        "Wednesday-Friday."
    )
    assert row.extra == {"button": "Click Here.", "link": "http://alert.claycountygov.com"}
    assert notices.row_qualifies(row.name, row.status, listing.variant)
    empty = apptegy.parse(_body("googlesites/clay-20241009.html"))
    assert (empty.variant, empty.state, empty.rows) == (googlesites.VARIANT, ListingState.EMPTY, ())


def test_synthetic_google_sites_edge_cases() -> None:
    # Synthetic documents in the Google Sites header's shape.
    with pytest.raises(ShapeError, match="not a Google Sites page"):
        googlesites.parse_text("<html><body><p>no header</p></body></html>")
    with pytest.raises(ShapeError, match="not a Google Sites page"):
        googlesites.parse_text('<html><body><div id="atIdViewHeader"></div></body></html>')
    region = '<div role="region" aria-labelledby="i9"><p id="i1">x</p></div>'
    with pytest.raises(ShapeError, match="labelling paragraph"):
        googlesites.parse_text(
            f'<html><head><title>T</title></head><body><header id="atIdViewHeader">{region}'
            "</header></body></html>"
        )
    blank = '<div role="region" aria-labelledby="i1"><p id="i1"> </p></div>'
    listing = googlesites.parse_text(
        f'<html><head><title>Titled</title></head><body><header id="atIdViewHeader">{blank}'
        "</header></body></html>"
    )
    assert (listing.state, listing.skipped_rows) == (ListingState.EMPTY, 1)
    with pytest.raises(ShapeError, match="no name or title"):
        googlesites.parse_text('<html><body><header id="atIdViewHeader"></header></body></html>')
    assert googlesites.slice_body(b"<html><body></body></html>") == document("")
    assert googlesites.slice_body(b'<div id="atIdViewHeader"></div>') == document("")
    plain = '<div role="region" aria-labelledby="i1"><p id="i1">Closed</p><a href="/x">x</a></div>'
    listing = googlesites.parse_text(
        f'<html><head><title>T</title></head><body><header id="atIdViewHeader">{plain}'
        "</header></body></html>"
    )
    assert listing.rows[0].extra == {"button": None, "link": "/x"}


def test_great_falls_district_information_holds_a_weather_alert_but_no_closing() -> None:
    listing = finalsite.parse(_body("wcm/great-falls-20231102.html"))
    assert {row.extra["app_title"] for row in listing.rows} == {"District Information"}
    assert listing.rows[0].status.startswith("Freezing Rain Alert 11/01/2023 URGENT")
    # A freezing-rain alert that points to bus routes' delays announces no closing or delay
    # of the schools: it proves nothing (the gate of 2026-10-13).
    assert not notices.row_qualifies(listing.rows[0].name, listing.rows[0].status, listing.variant)


@pytest.mark.parametrize(
    ("name", "rows", "kept", "first"),
    [
        (
            "lists/ktiv-20240108.html",
            45,
            35,
            ("Akron-Westfield Comm. Schools", "Delayed Monday 2 Hours"),
        ),
        (
            "lists/wjet-20241204.html",
            24,
            # "Closed through Thursday", "2 Hr Delay" too; a bare "No Classes Tuesday &
            # Wednesday" is how a calendar writes its days off, so the channel rule wants a
            # reason for it (a TV list is not gated by the rule: any row proves it)
            12,
            ("Barber National Institute \u2013 Elizabeth Lee Black School", "CLOSED"),
        ),
        ("lists/wetm-20230314.html", 22, 18, ("Athens Area Schools", "Delayed 3 hours Today")),
        (
            "edlio/comal-20250121.html",
            1,
            1,
            (
                "School Closure Tuesday, Jan. 21, for Comal ISD",
                "Due to the weather conditions and for the safety of students and staff, all Comal "
                "ISD campuses and departments will be closed Tuesday, January 21.",
            ),
        ),
    ],
)
def test_the_storm_day_captures_prove_their_stations(
    name: str, rows: int, kept: int, first: tuple[str, str]
) -> None:
    entry = ENTRIES[name]
    listing = adapter_for(entry.adapter)(_body(name))
    assert listing.state is ListingState.POPULATED
    assert len(listing.rows) == rows
    assert (listing.rows[0].name, listing.rows[0].status) == first
    qualifying = [
        row for row in listing.rows if notices.row_qualifies(row.name, row.status, listing.variant)
    ]
    assert len(qualifying) == kept


def test_synthetic_slice_drops_the_apps_scripts_and_styles() -> None:
    # A SYNTHETIC page: an announcements app holding a script and a style.
    article = (
        '<li><div class="ui-article"><h1 class="ui-article-title">Closed today</h1></div></li>'
    )
    app = _app("announcements", "Announcements", article).replace(
        '<div class="ui-widget-detail">',
        '<script>x()</script><style>p{}</style><div class="ui-widget-detail">',
    )
    sliced = wcm.slice_body(_synthetic(app).encode("utf-8"))
    assert b"<script" not in sliced
    assert b"<style" not in sliced
    assert wcm.parse_text(sliced.decode("utf-8")).rows[0].status == "Closed today"
