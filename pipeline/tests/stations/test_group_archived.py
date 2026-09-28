"""The Nexstar, TEGNA and Scripps adapters against archived storm-day pages.

Every fixture here is a Wayback ``id_`` capture downloaded by the archive-captures
workflow (fixtures/groups/README.md gives each one's capture link, capture time,
download time and original SHA-256), sliced with a ``-v2`` method. For each
variant, the names a browser shows are read here a second way, with a regular
expression over the markup (or a plain walk of the JSON), independently of the
adapter's HTML parser, and every name the adapter reads is compared with them
one by one. A few rows are also checked field by field, as read by eye from the
fixture.
"""

import json
import re
from collections.abc import Callable
from html import unescape

import pytest

from snowlight.sources.stations import group_fixtures, nexstar, scripps, tegna
from snowlight.sources.stations.adapters import ADAPTERS
from snowlight.sources.stations.archive import station_index, url_key
from snowlight.sources.stations.fixtures import FixtureEntry
from snowlight.sources.stations.model import Listing, ListingState, ReadMode, ShapeError
from snowlight.sources.stations.registry import load_registry

FOLDER = group_fixtures.DEFAULT_FOLDER
ARCHIVED = [e for e in group_fixtures.load_entries(FOLDER) if e.mode is ReadMode.ARCHIVE]
DASH = "\N{EN DASH}"


def text(file: str) -> str:
    return (FOLDER / file).read_text(encoding="utf-8")


def read(file: str) -> Listing:
    adapter = file.split("/", 1)[0]
    return ADAPTERS[adapter]((FOLDER / file).read_bytes())


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def _plain(fragment: str) -> str:
    """Markup to the text a browser shows: tags dropped, entities decoded, spaces collapsed."""
    return _collapse(unescape(re.sub(r"<[^>]+>", "", fragment)))


def _first_line(fragment: str) -> str:
    """The first line a browser shows of markup broken by ``<br>``."""
    return _plain(re.split(r"<br\s*/?>", fragment, flags=re.IGNORECASE)[0])


def _all(pattern: str, flags: int = re.DOTALL) -> Callable[[str], list[str]]:
    def names(markup: str) -> list[str]:
        found = (_plain(m.group(1)) for m in re.finditer(pattern, markup, flags))
        return [name for name in found if name]

    return names


def _scripps_names(markup: str) -> list[str]:
    found = re.finditer(
        r"<(?:p|h1|div) class=\"text--primary[^\"]*\">(.*?)</(?:p|h1|div)>", markup, re.DOTALL
    )
    return [_first_line(m.group(1)) for m in found]


def _scripps_json_names(markup: str) -> list[str]:
    (module,) = json.loads(markup)["closings"]
    return [_collapse(row["name"]) for row in module["data"]["resultsArray"]]


def _ecc_names(markup: str) -> list[str]:
    return [_collapse(closing["Name1"][0]) for closing in json.loads(markup).get("Closing", [])]


def _newsticker_names(markup: str) -> list[str]:
    # A "[WEB]" link written after a name is a link to the organization, not its name.
    markup = re.sub(r"\[\s*<a[^>]*>\s*WEB\s*</a>\s*\]", "", markup, flags=re.IGNORECASE)
    found = re.finditer(r"<FONT CLASS=\"orgname\">(.*?)</FONT>", markup, re.IGNORECASE)
    return [_plain(m.group(1)) for m in found]


def _psg_names(markup: str) -> list[str]:
    found = re.finditer(r"<div class=\"closing_row\"><strong>(.*?)</strong>", markup)
    return [_plain(m.group(1)).removesuffix(":").strip() for m in found]


def _school_information_names(markup: str) -> list[str]:
    rows = re.finditer(r"<tr[^>]*><td width=400>(.*?)</td>", markup, re.IGNORECASE | re.DOTALL)
    return [_plain(m.group(1)) for m in rows]


def _storm_tracker_names(markup: str) -> list[str]:
    after = markup.split("(posted:", 1)[1]
    return [_plain(m.group(1)) for m in re.finditer(r"<b>([^<]*)</b><br>", after)]


def _scn_names(markup: str) -> list[str]:
    body = markup.split("<tbody>", 1)[1]
    rows = re.finditer(r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>", body, re.DOTALL)
    return [_plain(m.group(1)) for m in rows]


def _tegna_legacy_names(markup: str) -> list[str]:
    # Only the "ALL" tab: the letter tabs after it repeat its rows.
    tab = markup.split("slide-all", 1)[1].split('class="closings-content slide-', 1)[0]
    return [
        _plain(m.group(1)) for m in re.finditer(r"<div class=\"closing-name\">(.*?)</div>", tab)
    ]


def _tribune_tab_names(markup: str) -> list[str]:
    found = re.finditer(r"<span class=\"place\">(.*?)<span class=\"pstatus\">", markup)
    return [_plain(m.group(1)).removesuffix("|").strip() for m in found]


def _app_feed_names(markup: str) -> list[str]:
    return [_collapse(item["content"]) for item in json.loads(markup)]


INDEPENDENT: dict[str, Callable[[str], list[str]]] = {
    "tegna-closings-module": _all(r"class=\"closings__title\">(.*?)</(?:span|p)>"),
    "tegna-closings-grid": _all(r"class=\"closings__title\">(.*?)</(?:span|p)>"),
    "tegna-closings-legacy": _tegna_legacy_names,
    "nexstar-page": _all(r"<h3 class=\"closing__title\">(.*?)</h3>"),
    "nexstar-app-feed": _app_feed_names,
    "nexstar-closing-alerts": _all(r"<h4>(.*?)</h4>"),
    "nexstar-tribune-tab": _tribune_tab_names,
    "nexstar-cgs-all-active": _all(r"<td class=\"org(?:dark)?\">(.*?)</td>"),
    "nexstar-newsticker-table": _newsticker_names,
    "nexstar-psg-closings": _psg_names,
    "nexstar-school-information": _school_information_names,
    "nexstar-storm-tracker": _storm_tracker_names,
    "schoolclosingsnet-table": _scn_names,
    "nexstar-ecc-json": _ecc_names,
    "scripps-closings-module": _scripps_names,
    "scripps-closings-liferay": _scripps_names,
    "scripps-closings-json": _scripps_json_names,
}
"""A second reading of each variant's names, by regular expression (or a JSON walk)."""

TYPED = frozenset(
    {
        "nexstar-typed-page",
        "nexstar-typed-entry-content",
        "nexstar-page-typed-beside",
        "scripps-typed-page",
    }
)
"""Variants of closings typed by hand (snowlight.sources.stations.typed)."""
TYPED_BY_EYE = frozenset(
    {
        "nexstar-typed/whnt-page-20210215043159.html",
        "nexstar-typed/whnt-page-20250108205534.html",
        "nexstar-typed/wdhn-page-20241109012642.html",
        "nexstar-typed/wdhn-page-20250201215557.html",
        "nexstar-typed/wrbl-page-20240926023920.html",
        "nexstar-typed/wntz-article-20240116202750.html",
        "scripps-typed/kstu-page-20221213030846.html",
        "scripps-typed/kstu-page-20230222072846.html",
        "scripps-typed/kstu-page-20230226220604.html",
        "nexstar-typed/kiah-page-20250125183900.html",
        "nexstar-typed/kiah-page-20260111124431.html",
        "nexstar-typed/whnt-page-20181211023820.html",
    }
)
"""The archived typed fixtures whose names test_typed.py and test_typed_beside.py check one by
one (and, for the pages typed as lists, against their list items read a second way)."""


@pytest.mark.parametrize("entry", ARCHIVED, ids=[entry.file for entry in ARCHIVED])
def test_every_archived_name_matches_a_second_reading(entry: FixtureEntry) -> None:
    listing = read(entry.file)
    names = [row.name for row in listing.rows]
    assert tuple(names) == entry.expected.names
    if entry.expected.state is ListingState.POPULATED and entry.expected.variant in INDEPENDENT:
        assert names == INDEPENDENT[entry.expected.variant](text(entry.file))
    elif entry.expected.state is ListingState.POPULATED and entry.expected.variant in TYPED:
        # A list typed by hand: its names were read by eye, one by one, in test_typed.py,
        # which also reads each list-typed page's top-level items a second way.
        assert entry.file in TYPED_BY_EYE
    elif entry.expected.state is ListingState.POPULATED:
        # A vendor file read by gray_files (its own tests read those formats).
        assert entry.expected.variant.startswith("gray-file-")
    else:
        assert names == []


def test_the_archive_has_a_storm_day_fixture_for_every_variant() -> None:
    seen = {(e.expected.variant, e.expected.state) for e in ARCHIVED}
    assert seen >= {
        ("tegna-closings-grid", ListingState.POPULATED),
        ("tegna-closings-grid", ListingState.EMPTY),
        ("tegna-closings-module", ListingState.POPULATED),
        ("tegna-closings-module", ListingState.EMPTY),
        ("tegna-frame", ListingState.DEFERRED),
        ("tegna-closings-legacy", ListingState.POPULATED),
        ("tegna-closings-legacy", ListingState.EMPTY),
        ("nexstar-app-feed", ListingState.POPULATED),
        ("nexstar-app-feed", ListingState.EMPTY),
        ("nexstar-closing-alerts", ListingState.POPULATED),
        ("nexstar-closing-alerts", ListingState.EMPTY),
        ("nexstar-tribune-tab", ListingState.POPULATED),
        ("nexstar-tribune-tab", ListingState.EMPTY),
        ("nexstar-clmod", ListingState.EMPTY),
        ("gray-file-flashalert", ListingState.POPULATED),
        ("nexstar-page", ListingState.POPULATED),
        ("nexstar-page", ListingState.EMPTY),
        ("nexstar-page-frame", ListingState.DEFERRED),
        ("nexstar-feed-page", ListingState.DEFERRED),
        ("nexstar-cgs-all-active", ListingState.POPULATED),
        ("nexstar-newsticker-table", ListingState.POPULATED),
        ("gray-file-newsticker", ListingState.EMPTY),
        ("nexstar-psg-closings", ListingState.POPULATED),
        ("nexstar-school-information", ListingState.POPULATED),
        ("nexstar-storm-tracker", ListingState.POPULATED),
        ("nexstar-storm-tracker", ListingState.EMPTY),
        ("gray-file-grid", ListingState.POPULATED),
        ("gray-file-newsticker-xml", ListingState.EMPTY),
        ("nexstar-psg-closings", ListingState.EMPTY),
        ("schoolclosingsnet-table", ListingState.POPULATED),
        ("nexstar-ecc-json", ListingState.POPULATED),
        ("scripps-closings-liferay", ListingState.POPULATED),
        ("scripps-closings-liferay", ListingState.EMPTY),
        ("scripps-closings-module", ListingState.POPULATED),
        ("scripps-closings-module", ListingState.EMPTY),
        ("scripps-closings-json", ListingState.POPULATED),
        ("scripps-closings-json", ListingState.EMPTY),
        ("scripps-frame", ListingState.DEFERRED),
        ("gray-file-grid", ListingState.POPULATED),
        ("nexstar-typed-page", ListingState.POPULATED),
        ("nexstar-typed-page", ListingState.EMPTY),
        ("nexstar-typed-entry-content", ListingState.POPULATED),
        ("nexstar-page-typed-beside", ListingState.POPULATED),
        ("scripps-typed-page", ListingState.POPULATED),
        ("scripps-typed-page", ListingState.EMPTY),
    }


def test_the_fixtures_span_the_platforms_regions() -> None:
    stations = {entry.source_id for entry in ARCHIVED}
    # TEGNA: DC, NC, WA, ME, KY, VA, OH, MO, OR, TX, IN, PA, TN, IA, AR; Nexstar: CT, RI, SD,
    # TN, OH, MO, IL, IA,
    # DC, MA, OR, OK, CO, NY, KS, MI, WV, IL (Chicago); Scripps: MO, TN, NY, OH, MI, MD,
    # CO, OK, WI, VA, KY.
    assert len({s for s in stations if s.startswith("tegna-")}) >= 20
    assert len({s for s in stations if s.startswith("nexstar-")}) >= 20
    assert len({s for s in stations if s.startswith("scripps-")}) >= 13


# TEGNA -------------------------------------------------------------------------------------


def test_wusa_2018_grid_reads_both_columns_under_their_heading() -> None:
    listing = read("tegna/wusa-grid-20181115063939.html")
    assert (listing.variant, len(listing.rows), listing.declared_count) == (
        "tegna-closings-grid",
        33,
        None,
    )
    first, fifth = listing.rows[0], listing.rows[4]
    assert (first.name, first.status, first.extra) == (
        "Berkeley Co Schools",
        "Closed Today",
        {"heading": "DELAYS/CLOSINGS"},
    )
    assert (fifth.name, fifth.status) == ("FFX Bapt Temple Academy", "Delayed 2 hours")


def test_king_2019_grid_says_there_are_none() -> None:
    listing = read("tegna/king-grid-20190219072640.html")
    assert (listing.variant, listing.state) == ("tegna-closings-grid", ListingState.EMPTY)


def test_archived_module_counts_match_their_lists() -> None:
    for file, rows in [
        ("tegna/wusa-page-20210131223248.html", 33),
        ("tegna/whas-page-20210211031825.html", 149),
        ("tegna/wvec-page-20210127223458.html", 13),
        ("tegna/wbns-page-20250106023125.html", 73),
        ("tegna/ksdk-page-20260126140342.html", 656),
        ("tegna/wtol-page-20260121212037.html", 1),
    ]:
        listing = read(file)
        assert (len(listing.rows), listing.declared_count) == (rows, rows), file
    assert read("tegna/krem-page-20210215110034.html").declared_count == 0


def test_wtol_2026_row() -> None:
    (row,) = read("tegna/wtol-page-20260121212037.html").rows
    assert (row.name, row.status, row.extra) == (
        "Triangular Processing Inc.",
        "Open Transportation 2 hour delay",
        {},
    )


def test_kthv_2017_gannett_era_list_reads_its_all_tab_once() -> None:
    listing = read("tegna/kthv-legacy-20170106144721.html")
    assert (listing.variant, listing.state, len(listing.rows)) == (
        "tegna-closings-legacy",
        ListingState.POPULATED,
        159,
    )
    first = listing.rows[0]
    assert (first.name, first.status, first.extra) == (
        "ABUNDANT LIFE SCHOOL",
        "Closed- Cyber Day 1",
        {"id": "5353"},
    )
    # The letter tabs repeat the ALL tab's rows: each name is read once.
    assert len({row.name for row in listing.rows}) == 159
    markup = text("tegna/kthv-legacy-20170106144721.html")
    assert markup.count('<div class="closing-name">') == 2 * 159
    empty = read("tegna/kvue-legacy-20180116054326.html")
    assert (empty.variant, empty.state, empty.rows) == (
        "tegna-closings-legacy",
        ListingState.EMPTY,
        (),
    )


def test_kgw_2020_page_frames_its_flashalert_report() -> None:
    listing = read("tegna/kgw-page-20200116003002.html")
    assert listing.follows == ("https://content.kgw.com/station/flashalert/allclosures.html",)


# Nexstar -----------------------------------------------------------------------------------


def test_wtnh_2020_page_before_perimeterx_keeps_every_detail() -> None:
    listing = read("nexstar/wtnh-page-20200316132421.html")
    assert (listing.variant, len(listing.rows)) == ("nexstar-page", 206)
    row = listing.rows[0]
    assert (row.name, row.status, row.extra) == (
        "ABC's Gymnastics Stars",
        "Closed",
        {"locality": "Niantic", "category": "School", "letter": "A"},
    )


def test_wdaf_page_whose_rest_object_has_no_list_showed_rows_on_storm_days() -> None:
    # FOX4 Kansas City: the page's REST object holds only a dead Tribune frame, but the
    # page itself (drawn by the theme) listed closings; these captures are the proof
    # behind reading its app feed.
    listing = read("nexstar/wdaf-page-20250212112913.html")
    assert (listing.variant, listing.state, len(listing.rows)) == (
        "nexstar-page",
        ListingState.POPULATED,
        151,
    )
    first = listing.rows[0]
    assert (first.name, first.status, first.extra) == (
        "Academie Lafayette",
        "Virtual Learning Wednesday",
        {"locality": "Kansas City", "category": "Schools", "letter": "A"},
    )
    chillicothe = read("nexstar/wdaf-page-20240117034351.html").rows[2]
    assert (chillicothe.name, chillicothe.status) == ("Chillicothe R-2", "Closed Tomorrow")
    empty = read("nexstar/wdaf-page-20240121160111.html")
    assert (empty.state, empty.rows) == (ListingState.EMPTY, ())


def test_2019_page_said_all_is_good_when_empty() -> None:
    # WLAX (La Crosse) in October 2019: the list's own words for "nothing listed".
    listing = read("nexstar/wlax-page-20191016204933.html")
    assert (listing.variant, listing.state, listing.rows) == (
        "nexstar-page",
        ListingState.EMPTY,
        (),
    )
    assert "<h2>All is good</h2>" in text("nexstar/wlax-page-20191016204933.html")


def test_indianapolis_2022_storm_day_page() -> None:
    listing = read("nexstar/wxin-page-20220203141041.html")
    assert (listing.variant, len(listing.rows)) == ("nexstar-page", 422)
    first = listing.rows[0]
    assert (first.name, first.status, first.extra) == (
        "A Plus Childcare and Learning Center",
        "Closed Today",
        {"locality": "Marion", "category": "Daycare/Preschool", "letter": "A"},
    )


def test_pages_of_sites_whose_rest_api_holds_no_list_showed_rows_on_storm_days() -> None:
    # The archived closings pages behind the app feeds these sites' entries poll.
    for file, rows, first in [
        ("nexstar/wsav-page-20220929043553.html", 5, ("Beaufort County Schools", "Beaufort")),
        ("nexstar/wlax-page-20240110071729.html", 5, ("Boscobel Area Schools", "Boscobel")),
        ("nexstar/wncn-page-20220930044816.html", 12, None),
        ("nexstar/wvns-page-20210203143914.html", 13, ("Fayette County", "Fayetteville")),
        ("nexstar/wnct-page-20250122103636.html", 114, ("Agape Community Health Clinic", None)),
        ("nexstar/klbk-page-20230125234330.html", 1, ("New Hope Foursquare Church", "Lubbock")),
        ("nexstar/kmid-page-20230131142550.html", 29, ("Andrews ISD", "Andrews")),
        ("nexstar/kget-page-20240202043228.html", 2, ("El Tejon Unified School District", None)),
        ("nexstar/wbre-page-20220204100622.html", 236, None),
    ]:
        listing = read(file)
        assert (listing.variant, listing.state, len(listing.rows)) == (
            "nexstar-page",
            ListingState.POPULATED,
            rows,
        ), file
        if first is not None:
            assert (listing.rows[0].name, listing.rows[0].extra.get("locality")) == first, file
    kmid = read("nexstar/kmid-page-20230131142550.html").rows[2]
    assert (kmid.name, kmid.status, kmid.extra) == (
        "Buena Vista ISD",
        "Delayed 2 Hours",
        {"locality": "Pecos", "category": "Schools", "letter": "B"},
    )


def test_whbf_app_feed_archived_with_rows() -> None:
    # The feed WHBF's entry polls, itself archived on a storm day (not only its page).
    listing = read("nexstar/whbf-feed-20250205204455.json")
    assert (listing.variant, listing.state, len(listing.rows)) == (
        "nexstar-app-feed",
        ListingState.POPULATED,
        17,
    )
    items = json.loads(text("nexstar/whbf-feed-20250205204455.json"))
    first, row = items[0], listing.rows[0]
    assert (row.name, row.status) == (_collapse(first["content"]), first["status"])
    assert read("nexstar/kveo-feed-20250121002324.json").state is ListingState.EMPTY
    (lakeland,) = read("nexstar/wdaf-feed-20250214035445.json").rows
    assert (lakeland.name, lakeland.status, lakeland.extra["city"]) == (
        "Lakeland R-3 School Dist MO",
        "Closed",
        "Deepwater",
    )
    assert len(read("nexstar/wric-feed-20260208074307.json").rows) == 13
    wane = read("nexstar/wane-feed-20250115064930.json")
    assert (wane.state, [row.name for row in wane.rows][:2]) == (
        ListingState.POPULATED,
        ["Adams Central Community Schools", "Central Noble Schools"],
    )


def test_liferay_era_closing_alerts_module() -> None:
    (row,) = read("nexstar/wjmn-alerts-20160317042348.html").rows
    assert (row.name, row.status, row.extra) == (
        "Wakefield-Marensico",
        "Closed 3/17",
        {"range": "S-Z"},
    )
    empty = read("nexstar/wbre-alerts-20170207005629.html")
    assert (empty.variant, empty.state) == ("nexstar-closing-alerts", ListingState.EMPTY)


def test_tribune_tab_files() -> None:
    listing = read("nexstar/wjw-tab-20170131032848.html")
    assert [(row.name, row.status) for row in listing.rows] == [
        ("Cleveland State University", "Delayed 2 Hours"),
        ("Great Lakes Truck Driving School", "Delayed 2 Hours"),
    ]
    assert listing.rows[0].updated_text == "Mon Jan 30 22:24:03 EST 2017"
    assert listing.rows[0].extra == {"tab": "School", "letter": "c", "updated_scope": "page"}
    empty = read("nexstar/wgn-tab-20190301191748.html")
    assert (empty.variant, empty.state) == ("nexstar-tribune-tab", ListingState.EMPTY)


def test_2016_media_general_file_in_its_empty_form() -> None:
    listing = read("nexstar/wric-clmod-20160312184149.html")
    assert (listing.variant, listing.state, listing.rows) == (
        "nexstar-clmod",
        ListingState.EMPTY,
        (),
    )
    # Any other content of the list block is refused: its populated form has not been seen.
    markup = text("nexstar/wric-clmod-20160312184149.html").replace(
        "There are no reported closings or delays at this time.", "Some School: Closed"
    )
    with pytest.raises(ShapeError):
        nexstar.parse(markup.encode())


def test_older_variants_refuse_what_they_cannot_read() -> None:
    # Synthetic edits of the real fixtures above (confined to this test): each reader
    # refuses a body it would otherwise have to guess at.
    tab = text("nexstar/wjw-tab-20170131032848.html")
    with pytest.raises(ShapeError):  # an item in a layout the reader does not know
        nexstar.parse(
            tab.replace("</ul>", "<li class='odd'>Some School | Closed</li></ul>").encode()
        )
    alerts = text("nexstar/wbre-alerts-20170207005629.html")
    with pytest.raises(ShapeError):  # a tab sentence the reader does not know
        nexstar.parse(alerts.replace("Please check back later.", "Check again soon.", 1).encode())
    legacy = text("tegna/kvue-legacy-20180116054326.html")
    with pytest.raises(ShapeError):  # rows and the no-closings sentence in the ALL tab
        tegna.parse(
            legacy.replace(
                '<div class="closings-empty">',
                '<div class="closing-container 1"><div class="closing-name">X</div>'
                '<div class="closing-status">Closed</div></div><div class="closings-empty">',
                1,
            ).encode()
        )


def test_2016_and_2017_pages_frame_their_list_files() -> None:
    assert read("nexstar/wutr-frame-20170315035155.html").follows == (
        "https://s3.amazonaws.com/nxsglobal/cnyhomepage/closings/closings.html",
    )
    assert read("nexstar/wric-frame-20160304123244.html").follows == (
        "http://wx.wric.com/weather/WRIC_closings_delays.html",
    )


def test_koin_2021_row_shown_with_its_name_alone() -> None:
    listing = read("nexstar/koin-page-20210212084327.html")
    (agatha,) = [row for row in listing.rows if row.name == "St. Agatha Catholic School"]
    assert agatha.status == ""
    assert len(listing.rows) == 94


def test_tribune_era_pages_are_deferred_to_the_files_they_frame() -> None:
    expected = {
        "nexstar/kdvr-page-20190209174122.html": (
            "https://s3.amazonaws.com/kdvrclosings/kdvr.html",
        ),
        "nexstar/wjw-page-20190106225047.html": ("https://s3.amazonaws.com/wjwclosings/wjw.html",),
        "nexstar/wgn-page-20181126073811.html": ("https://s3.amazonaws.com/wgnclosings/wgn.html",),
        "nexstar/wreg-page-20200329031144.html": (
            "https://newcdn.tribtv.com/wreg/SchoolClosings/closings.html",
        ),
        "nexstar/wten-page-20181203100119.html": (
            "https://media.news10.com/nxs-wtentv-media-us-east-1/closings/school.html",
        ),
        "nexstar/wpri-page-20200325041737.html": (
            "https://media.wpri.com/nxs-wpritv-media-us-east-1/html/toolbox/closings/WPRI_closings.html",
        ),
        # WGN from 2020: the Emergency Closing Center application, not a list file.
        "nexstar/wgn-page-20210216155628.html": (),
    }
    for file, follows in expected.items():
        listing = read(file)
        assert (listing.variant, listing.state) == ("nexstar-page-frame", ListingState.DEFERRED)
        assert listing.follows == follows, file


def test_tribune_tab_pages_name_their_tab_files() -> None:
    assert read("nexstar/wjw-tabs-20200211230101.html").follows == (
        "wjw_schools.html",
        "wjw_biz.html",
        "wjw_dc.html",
        "wjw_other.html",
    )
    assert read("nexstar/wgn-tabs-20190301191746.html").follows[0] == "wgn_schools.html"


def test_wreg_school_information_and_wten_storm_tracker_files() -> None:
    (row,) = read("nexstar/wreg-schoolinfo-20200215171705.html").rows
    assert (row.name, row.status, row.updated_text, row.extra) == (
        "Lafayette Co Schools",
        "Closing 1 hour early",
        "11:17am on 2/15/2020",
        {"updated_scope": "page", "group": "Schools"},
    )
    wten = read("nexstar/wten-stormtracker-20200329220512.html")
    assert [row.name for row in wten.rows] == [
        "Albany Leadership Charter High",
        "Newmeadow at Clifton Park",
        "Pooh's Corner Child Care Ctr",
        "Southwest Vermont SU",
    ]
    assert (wten.rows[1].status, wten.rows[1].updated_text) == (
        "Closed until 4-15-20.",
        "Sunday, Mar 29, 2020 at 6:04 PM",
    )
    empty = read("nexstar/wten-stormtracker-20181203111455.html")
    assert (empty.variant, empty.state) == ("nexstar-storm-tracker", ListingState.EMPTY)


def test_kdvr_2020_frame_file_and_kmgh_2023_rendering() -> None:
    grid = read("nexstar/kdvr-grid-20200319032523.html")
    assert (grid.variant, len(grid.rows), grid.rows[0].name) == (
        "gray-file-grid",
        74,
        "Adams Co. Government Offices",
    )
    kmgh = read("scripps/kmgh-json-20230222133904.json")
    assert (kmgh.variant, len(kmgh.rows)) == ("scripps-closings-json", 33)


def test_script_filled_pages_name_their_xml_files() -> None:
    assert read("nexstar/wood-feedpage-20190330155239.html").follows == (
        "//media.woodtv.com/nxs-woodtv-media-us-east-1/closings/WOODclosings.xml",
    )
    assert read("nexstar/wood-feedpage-20241205143721.html").follows == (
        "//media.psg.nexstardigital.net/wood/closings/WOODclosings.xml",
    )
    assert read("nexstar/wowk-psgpage-20250213090134.html").follows == ("closings.xml",)


def test_wdaf_cgs_all_active_rows() -> None:
    listing = read("nexstar/wdaf-cgs-20181126143008.html")
    assert (listing.variant, len(listing.rows)) == ("nexstar-cgs-all-active", 263)
    first = listing.rows[0]
    assert (first.name, first.status, first.updated_text) == (
        "C.O.P.S.",
        "Closed",
        "11/26/2018 8:29:06 AM",
    )
    assert first.extra == {"updated_scope": "page", "category": "Activ.", "status2": ""}
    later = read("nexstar/wdaf-cgs-20191216111946.html").rows[3]
    assert (later.name, later.status, later.extra) == (
        "Independence Meals on Wheels",
        "No Meal Delivery",
        {"updated_scope": "page", "category": "Activ."},
    )


def test_wpri_2020_newsticker_table_rows_keep_town_and_group() -> None:
    listing = read("nexstar/wpri-newsticker-20201218214155.html")
    assert (listing.variant, len(listing.rows)) == ("nexstar-newsticker-table", 25)
    first = listing.rows[0]
    assert (first.name, first.status, first.updated_text) == (
        "Cumberland Public Schools",
        "Ashton, BF Norton, Community ; Cumb. Hill - DL Friday",
        "UPDATED FRIDAY, DEC 18 AT 4:40 PM",
    )
    assert first.extra == {
        "town": "Cumberland",
        "group": "RI PUBLIC SCHOOLS",
        "updated_scope": "page",
    }
    empty = read("nexstar/wpri-newsticker-20190327011336.html")
    assert (empty.variant, empty.state) == ("gray-file-newsticker", ListingState.EMPTY)


def test_ksn_psg_file_on_a_storm_day() -> None:
    listing = read("nexstar/ksnw-psg-20220204032844.html")
    assert (listing.variant, len(listing.rows)) == ("nexstar-psg-closings", 83)
    bee, andover = listing.rows[0], listing.rows[2]
    assert (bee.name, bee.extra) == (
        "Butler County Spelling Bee",
        {"expires": "2022-02-04 23:59:00"},
    )
    assert bee.status.startswith("Postponed; The event scheduled for Friday in El Dorado")
    assert (andover.name, andover.status) == ("Andover - USD 385", "Closed Tomorrow")
    assert andover.extra == {
        "group": "Schools",
        "link": "https://www.usd385.org/",
        "expires": "2022-02-04 16:30:00",
    }
    assert read("nexstar/ksnw-psg-20240301023647.html").state is ListingState.EMPTY


def test_wgn_ecc_file_populated() -> None:
    listing = read("nexstar/wgn-ecc-20240115172841.json")
    assert (listing.variant, len(listing.rows)) == ("nexstar-ecc-json", 75)
    first = listing.rows[0]
    assert first.name == "DIST #46 (GRAYSLAKE ELEMENTARY SCHOOLS)"
    assert first.extra["updated_scope"] == "page"
    assert first.updated_text is not None


def test_kolr_school_closings_network_report() -> None:
    listing = read("nexstar/kolr-scn-20191112033246.html")
    assert (listing.variant, len(listing.rows)) == ("schoolclosingsnet-table", 90)
    assert listing.rows[0].name == "Alpena School District"


# Scripps -----------------------------------------------------------------------------------


def test_kshb_2018_liferay_rows_keep_their_comments() -> None:
    listing = read("scripps/kshb-liferay-20181125094323.html")
    assert (listing.variant, len(listing.rows)) == ("scripps-closings-liferay", 22)
    (liberty,) = [row for row in listing.rows if row.name.startswith("Liberty Church")]
    assert (liberty.name, liberty.status, liberty.extra) == (
        "Liberty Church of Christ - CLAY",
        "Dismissing Early at 10:15 AM",
        {"comments": "No evening service"},
    )
    empty = read("scripps/wews-liferay-20181115094911.html")
    assert (empty.variant, empty.state) == ("scripps-closings-liferay", ListingState.EMPTY)


def test_the_html_page_and_its_json_rendering_read_alike() -> None:
    for page, rendering in [
        ("scripps/wxyz-page-20210216063113.html", "scripps/wxyz-json-20210216063131.json"),
        ("scripps/wews-page-20210215140710.html", "scripps/wews-json-20210215134235.json"),
        ("scripps/wtmj-page-20201230075200.html", "scripps/wtmj-json-20201230074408.json"),
    ]:
        html, data = read(page).rows, read(rendering).rows
        assert [(r.name, r.status) for r in html] == [(r.name, r.status) for r in data], page
        # The HTML's unlabelled time is the rendering's expiration.
        assert [r.extra.get("expiration") for r in html] == [r.extra["expiration"] for r in data]


def test_wews_names_keep_their_county_line_apart() -> None:
    first = read("scripps/wews-page-20210215140710.html").rows[0]
    assert (first.name, first.status) == ("Ashland Co-Wst Holmes JVSD", "Closed")
    assert first.extra == {"second_line": "Ashland County", "expiration": "2021-02-15T15:00:00Z"}
    rendered = read("scripps/wews-json-20210215134235.json").rows[0]
    assert rendered.extra == {
        "county": "Ashland",
        "expiration": "2021-02-15T15:00:00Z",
        "state": "other",
    }
    missing = read("scripps/wxmi-page-20260120035353.html").rows[0]
    assert (missing.name, missing.extra["second_line"]) == ("Adams Christian School", "null County")


def test_empty_json_rendering_and_empty_page_at_kmgh() -> None:
    assert read("scripps/kmgh-json-20241126184347.json").state is ListingState.EMPTY
    assert read("scripps/kmgh-page-20260303041207.html").state is ListingState.EMPTY


# Slicing -----------------------------------------------------------------------------------


@pytest.mark.parametrize("entry", ARCHIVED, ids=[entry.file for entry in ARCHIVED])
def test_v2_slices_are_stable(entry: FixtureEntry) -> None:
    body = (FOLDER / entry.file).read_bytes()
    assert group_fixtures.slice_body(entry.slice, body) == body


def test_v2_cuts_what_v1_cuts_to_the_same_bytes() -> None:
    live = [e for e in group_fixtures.load_entries(FOLDER) if e.mode is ReadMode.LIVE]
    pairs = {"nexstar-v1": nexstar.slice_body_v2, "tegna-v1": tegna.slice_body_v2}
    pairs["scripps-v1"] = scripps.slice_body_v2
    for entry in live:
        if entry.slice in pairs:
            body = (FOLDER / entry.file).read_bytes()
            assert pairs[entry.slice](body) == body, entry.file


def test_every_archived_url_is_an_address_its_station_registers() -> None:
    index = station_index(load_registry())
    for entry in ARCHIVED:
        assert index[url_key(entry.url)].id == entry.source_id, entry.file
