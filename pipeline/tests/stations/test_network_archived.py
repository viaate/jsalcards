"""The ABC, NBC, Emergency Closing Center and FlashAlert adapters on archived storm-day captures.

Every body here is a real Wayback ``id_`` capture of the station's own page or file
(provenance in fixtures/networks/PROVENANCE.json). The expected rows do not come
from the adapter: short lists are written out by hand from the raw file, and long
ones are taken from the raw bytes with a plain pattern (and, on abcotv pages, from
the page state's JSON), so a reading mistake in an adapter cannot also sit in its
expectation.
"""

import json
import re
from collections import Counter
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from xml.etree import ElementTree

import pytest

from snowlight.sources.stations import (
    abc_owned,
    cbs_owned,
    ecc,
    flashalert,
    fox_owned,
    nbc_owned,
    network_fixtures,
)
from snowlight.sources.stations.fixtures import FixtureEntry
from snowlight.sources.stations.model import ListingState, ReadMode

FOLDER = Path(__file__).parent / "fixtures" / "networks"
ENTRIES = network_fixtures.load_entries(FOLDER)
ARCHIVED = [entry for entry in ENTRIES if entry.mode is ReadMode.ARCHIVE]
_NAME = re.compile(r'<span class="school-closing-name">(.*?)</span>', re.DOTALL)
_BLOCK = re.compile(
    r'(?:<div class="section-header">([^<]*)</div>)?\s*<ul class="school-closings-list">(.*?)</ul>',
    re.DOTALL,
)
_STATE = re.compile(r'"schoolclosings":(?=\{"time")')
_SPACE = re.compile(r"\s+")
_NBC_LISTING = re.compile(
    r'<h4 class="listing__org">(.*?)</h4>\s*<p class="listing__notice">(.*?)</p>', re.DOTALL
)
_ORGNAME = re.compile(r'<FONT CLASS="orgname">(.*?)</FONT>', re.DOTALL | re.IGNORECASE)
_WEB = re.compile(r"\[<a [^>]*>WEB</A>\]", re.IGNORECASE)
_TABLE_ROW = re.compile(
    r"<tr><td [^>]*><font [^>]*>(.*?)</font></td><td [^>]*><font [^>]*>(.*?)</font></td></tr>",
    re.DOTALL,
)
_SC_NAME = re.compile(r"<P><b>([^<]*)</b><br>", re.IGNORECASE)
_FLASH_REPORT = re.compile(r"<div class='cwcReport'>(.*?)</div>", re.DOTALL)
_FLASH_NAME = re.compile(r"^\s*<strong>(.*?)</strong>", re.DOTALL)
_NBC_LEGACY_ITEM = re.compile(r'<p class="closing_item">([^<]*)<br/><span>([^<]*)</span></p>')


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def _text(fragment: str) -> str:
    return _SPACE.sub(" ", unescape(fragment.replace("<!-- -->", ""))).strip()


def _own(adapter: str) -> list[FixtureEntry]:
    """The archived fixtures of this platform's own stations (not another station's file)."""
    prefix = adapter.split("-", maxsplit=1)[0]
    return [
        entry
        for entry in ARCHIVED
        if entry.adapter == adapter and entry.source_id.startswith(f"{prefix}-")
    ]


def test_every_archived_abc_ecc_and_flashalert_fixture_is_the_station_s_own() -> None:
    hosts = {
        "abc-owned": (
            "abc7ny.com",
            "6abc.com",
            "abc11.com",
            "abc13.com",
            "abc7.com",
            "abc30.com",
            "abc7news.com",
            "abc7chicago.com",
            "wgnr-closings.s3.amazonaws.com",
        ),
        "ecc": (
            "media.psg.nexstardigital.net/WGNR/closings/closings.json",
            "emergencyclosingcenter.com/complete.html",
        ),
        "flashalert": (
            "flashalertnewswire.net/IIN/reportsX/cwc-closures.php",
            *(
                f"flashalert{site}.net"
                for site in ("portland", "eugene", "medford", "bend", "boise", "seattle")
            ),
            "flashalertspokane.net",
            "flashalertcolumbia.net",
        ),
        "fox-owned": (
            "media.foxtv.com",
            "fox6now.com",
            "fox5ny.com",
            "fox9.com",
            "fox2detroit.com",
            "fox5dc.org",
            "wagaradio2.com",
            "s3.amazonaws.com/witiclosings/",
        ),
        "cbs-owned": ("cbsnewsstatic.com", "static.cbslocal.com", "cbsnews.com"),
        "nbc-owned": (
            "nbcconnecticut.com",
            "nbcnewyork.com",
            "nbcphiladelphia.com",
            "nbcwashington.com",
            "nbcboston.com",
            "nbcdfw.com",
            "nbclosangeles.com",
            "nbcsandiego.com",
            "nbcbayarea.com",
            "nbcmiami.com",
        ),
    }
    for adapter, own in hosts.items():
        entries = _own(adapter)
        assert entries, adapter
        for entry in entries:
            assert any(host in entry.url for host in own), entry.file
            assert entry.archive_url is not None
            assert entry.archive_url.startswith(
                f"https://web.archive.org/web/{entry.captured_at:%Y%m%d%H%M%S}id_/"
            )
    populated = Counter(
        entry.adapter
        for adapter in hosts
        for entry in _own(adapter)
        if entry.expected.state is ListingState.POPULATED
    )
    assert populated["abc-owned"] >= 12
    assert populated["ecc"] >= 6
    assert populated["flashalert"] >= 3
    assert populated["nbc-owned"] >= 11
    assert populated["fox-owned"] >= 10
    assert populated["cbs-owned"] >= 8


# ABC ------------------------------------------------------------------------------------

ABC_ARCHIVED = _own("abc-owned")


@pytest.mark.parametrize("entry", ABC_ARCHIVED, ids=lambda entry: entry.file)
def test_abc_rows_are_the_names_in_the_markup(entry: FixtureEntry) -> None:
    raw = _body(entry.file).decode("utf-8")
    expected: list[tuple[str, str | None]] = []
    for match in _BLOCK.finditer(raw):
        heading = _text(match.group(1)) if match.group(1) is not None else None
        for name in _NAME.findall(match.group(2)):
            if _text(name) != abc_owned.EMPTY_NAME:
                expected.append((_text(name), heading or None))
    listing = abc_owned.parse(_body(entry.file))
    assert [(row.name, row.extra.get("state")) for row in listing.rows] == expected
    assert listing.state is entry.expected.state
    assert (listing.state is ListingState.POPULATED) == bool(expected)


@pytest.mark.parametrize(
    "entry",
    [entry for entry in ABC_ARCHIVED if entry.expected.variant == "abc-otv-list"],
    ids=lambda entry: entry.file,
)
def test_abc_application_rows_are_the_page_state_s_schools(entry: FixtureEntry) -> None:
    raw = _body(entry.file).decode("utf-8")
    match = _STATE.search(raw)
    assert match is not None
    state, _end = json.JSONDecoder().raw_decode(raw, match.end())
    schools = [
        (" ".join(school["name"].split()), group["name"], school["county"] or None, school["text"])
        for group in state["states"]
        for school in group["schools"]
    ]
    listing = abc_owned.parse(_body(entry.file))
    assert [
        (row.name, row.extra.get("state"), row.extra.get("county"), row.status)
        for row in listing.rows
    ] == [(name, group, county, " ".join(text.split())) for name, group, county, text in schools]
    assert listing.list_updated_at == datetime.fromtimestamp(state["time"], UTC)


def test_abc_legacy_new_york_page_of_the_february_2017_storm() -> None:
    listing = abc_owned.parse(_body("abc-owned/wabc-page-20170209214652.html"))
    assert listing.variant == "abc-legacy-list"
    assert listing.list_updated_at is None
    assert [
        (row.name, row.status, row.extra["state"], row.extra["county"], row.updated_text)
        for row in listing.rows
    ] == [
        ("New Greater Bethel Bible", "CLOSED", "New York", "Queens", "02/09/2017 04:38pm"),
        ("Roslyn UFSD", "CLOSED", "New York", "Nassau", "02/09/2017 04:38pm"),
        ("St Albans Christian Acad", "CLOSED", "New York", "Queens", "02/09/2017 04:38pm"),
        ("Wood Tobe-Coburn School", "CLOSED", "New York", "New York", "02/09/2017 04:38pm"),
    ]


def test_abc_legacy_philadelphia_page_with_three_states() -> None:
    listing = abc_owned.parse(_body("abc-owned/wpvi-page-20190219235902.html"))
    assert listing.variant == "abc-legacy-list"
    assert Counter(row.extra["state"] for row in listing.rows) == {
        "Pennsylvania": 142,
        "New Jersey": 37,
        "Delaware": 8,
    }
    first, last = listing.rows[0], listing.rows[-1]
    assert (first.name, first.status, first.extra["county"]) == (
        "A Child's Nest",
        "Closing at 11:00 AM. No Afternoon School Activities",
        "Delaware",
    )
    assert (last.name, last.status, last.extra["state"], last.extra["county"]) == (
        "Red Clay Consolidated School District",
        "Closed",
        "Delaware",
        "New Castle",
    )
    assert {row.updated_text for row in listing.rows} == {"02/19/2019 06:53pm"}


def test_abc_legacy_pages_without_state_headings() -> None:
    houston = abc_owned.parse(_body("abc-owned/ktrk-page-20180109085112.html"))
    assert [(row.name, row.status, row.updated_text, row.extra) for row in houston.rows] == [
        ("Episcopal HS Houston", "Opening at 10 a.m.", None, {}),
        ("HISD", "Experiencing bus delays", None, {}),
    ]
    chicago = abc_owned.parse(_body("abc-owned/wls-page-20180209024114.html"))
    assert (chicago.variant, len(chicago.rows)) == ("abc-legacy-list", 1062)
    assert [(row.name, row.status, row.extra.get("county")) for row in chicago.rows[:3]] == [
        ("ACE TECH CHARTER HIGH SCHOOL", "TOMORROW: CLOSED", None),
        ("GOWER MIDDLE SCHOOL", "TOMORROW: CLOSED", "DUPAGE COUNTY"),
        ("NORTH BOONE SCHOOL DISTRICT 200", "TOMORROW: CLOSED", "BOONE COUNTY"),
    ]
    last = chicago.rows[-1]
    assert (last.name, last.status, last.extra["county"]) == (
        "AMAZON FULFILLMENT CENTER - MDW7",
        "TOMORROW: OPENING DELAYED 2 HOURS",
        "",
    )
    assert all("state" not in row.extra and row.updated_text is None for row in chicago.rows)


def test_abc_legacy_empty_pages() -> None:
    philadelphia = abc_owned.parse(_body("abc-owned/wpvi-page-20170216040805.html"))
    raleigh = abc_owned.parse(_body("abc-owned/wtvd-page-20180121222911.html"))
    for listing in (philadelphia, raleigh):
        assert (listing.variant, listing.state, listing.skipped_rows) == (
            "abc-legacy-list",
            ListingState.EMPTY,
            0,
        )
    # WTVD's "More Closings & Delays" link is not a closing.
    assert abc_owned.MORE_HEADING in _body("abc-owned/wtvd-page-20180121222911.html").decode()


def test_abc_new_york_page_of_23_february_2026() -> None:
    listing = abc_owned.parse(_body("abc-owned/wabc-page-20260223174946.html"))
    assert [(row.name, row.status, row.extra["county"]) for row in listing.rows] == [
        ("Baldwin UFSD", "CLOSED", "Nassau"),
        ("Bellmore UFSD", "CLOSED Tuesday February 24", "Nassau"),
        ("Hewlett-Woodmere UFSD", "CLOSED", "Nassau"),
        ("Island Park UFSD", "CLOSED", "Nassau"),
        ("Northport-East Northport", "CLOSED", "Suffolk"),
        (
            "Valley Stream CHSD",
            "CLOSED CHSD & Elementary Districts. Tuesday: February 24th",
            "Nassau",
        ),
        ("Valley Stream UFSD Thirty", "CLOSED", "Nassau"),
        ("Barnegat Twnsp SD", "CLOSED. Tuesday, February 24", "Ocean"),
        ("Freehold Bor. SD", "No After-School or PM Programs", "Monmouth"),
        ("Howell Twnsp SD", "CLOSED - 2/24", "Monmouth"),
        ("Marlboro Twnsp SD", "CLOSED", "Monmouth"),
        ("New Brunswick SD", "CLOSED Tuesday, February 24, 2026", "Middlesex"),
        ("Red Bank SD", "CLOSED - Tuesday, February 24", "Monmouth"),
        ("Secaucus SD", "CLOSED. School Closed Tuesday, February 24, 2026", "Hudson"),
    ]
    assert [row.extra["state"] for row in listing.rows] == ["New York"] * 7 + ["New Jersey"] * 7
    assert {row.updated_text for row in listing.rows} == {"02/23/2026 05:45pm"}
    assert listing.list_updated_at == datetime(2026, 2, 23, 17, 45, 18, tzinfo=UTC)


def test_abc_state_without_a_name() -> None:
    listing = abc_owned.parse(_body("abc-owned/wpvi-page-20240119112718.html"))
    assert Counter(row.extra.get("state") for row in listing.rows) == {
        "Pennsylvania": 199,
        "Delaware": 9,
        None: 1,
        "New Jersey": 107,
    }
    (nameless,) = [row for row in listing.rows if "state" not in row.extra]
    assert (nameless.name, nameless.status, nameless.extra["county"]) == (
        "New Hope Academy - Yardley",
        "Closed. All Virtual",
        "Bucks",
    )


def test_abc_california_lists_last_changed_in_february_2019() -> None:
    stale = datetime(2019, 2, 12, 20, 39, 39, tzinfo=UTC)
    for name in (
        "abc-owned/kabc-page-20190506191048.html",
        "abc-owned/kgo-page-20230923204353.html",
        "abc-owned/kfsn-page-20250617201253.html",
    ):
        listing = abc_owned.parse(_body(name))
        assert (listing.state, listing.list_updated_at) == (ListingState.EMPTY, stale), name


def test_abc_chicago_frames_the_closing_center_copy() -> None:
    listing = abc_owned.parse(_body("abc-owned/wls-page-20260101210212.html"))
    assert (listing.variant, listing.follows) == (
        "abc-otv-frame",
        ("https://wgnr-closings.s3.amazonaws.com/index.html",),
    )
    framed = abc_owned.parse(_body("abc-owned/wls-frame-20210216023514.html"))
    assert (framed.variant, framed.state, framed.follows) == (
        "abc-framed-ecc-app",
        ListingState.DEFERRED,
        (),
    )


# NBC ------------------------------------------------------------------------------------

NBC_PAGES = [entry for entry in _own("nbc-owned") if entry.file.endswith(".html")]


@pytest.mark.parametrize("entry", NBC_PAGES, ids=lambda entry: entry.file)
def test_nbc_page_rows_are_the_listings_in_the_markup(entry: FixtureEntry) -> None:
    raw = _body(entry.file).decode("utf-8")
    listing = nbc_owned.parse(_body(entry.file))
    if entry.expected.variant == "nbc-legacy-page":
        expected = [(_text(name), _text(status)) for name, status in _NBC_LEGACY_ITEM.findall(raw)]
        assert raw.count('class="closing_item"') == len(expected)
    else:
        assert "tab-pane" not in raw  # no state tabs in these captures: one list
        listed = [(_text(name), _text(status)) for name, status in _NBC_LISTING.findall(raw)]
        assert raw.count('class="listing"') == len(listed)
        # A blank listing (no name, no notice: NBC 6 Miami's empty block) is not a row.
        expected = [pair for pair in listed if pair != ("", "")]
        assert listing.skipped_rows == len(listed) - len(expected)
    assert [(row.name, row.status) for row in listing.rows] == expected
    assert (listing.state is ListingState.POPULATED) == bool(expected)
    assert listing.variant == entry.expected.variant


def test_nbc_page_before_the_wordpress_platform() -> None:
    listing = nbc_owned.parse(_body("nbc-owned/wcau-page-20190220201954.html"))
    assert (listing.variant, len(listing.rows), listing.declared_count) == (
        "nbc-legacy-page",
        47,
        47,
    )
    assert [(row.name, row.status) for row in listing.rows[:6]] == [
        ("ABC Learning Station", "Closed"),
        ("Al-Aqsa Islamic School", "Closed"),
        ("Alvernia University - Berks", "Closed"),
        ("Alvernia University - Philadelphia", "Closed"),
        ("ARC of Camden County", "Closed"),
        ("Aviation Institute of Maintenance", "No Evening Classes"),
    ]
    assert {row.updated_text for row in listing.rows} == {"02/20/19 03:12:30 PM EST"}
    for name in (
        "nbc-owned/wbts-page-20170204125739.html",
        "nbc-owned/wrc-page-20190322192121.html",
        "nbc-owned/knsd-page-20171029180138.html",
    ):
        empty = nbc_owned.parse(_body(name))
        assert (empty.variant, empty.state) == ("nbc-legacy-page", ListingState.EMPTY), name


def test_nbc_washington_page_of_18_february_2021() -> None:
    listing = nbc_owned.parse(_body("nbc-owned/wrc-page-20210218204752.html"))
    assert [(row.name, row.status) for row in listing.rows] == [
        ("Christ Chapel Academy", "Virtual Learning Only"),
        ("City of Winchester", "Open at 10am"),
        ("YMCA-Anthony Bowen", "Closes at 5pm Thurs more info at www.ymcadc.org"),
        ("YMCA-Arlington", "Closes at 5pm Thurs more info at www.ymcadc.org"),
        ("YMCA-Arlington Tennis Center", "Closes at 5pm Thurs more info at www.ymcadc.org"),
        ("YMCA-Bethesda Chevy Chase", "Closes at 5pm Thurs more info at www.ymcadc.org"),
        ("YMCA-Silver Spring", "Closes at 5pm Thurs more info at www.ymcadc.org"),
        ("YMCA Alexandria", "Closes at 5pm Thurs more info at www.ymcadc.org"),
        ("YMCA Fairfax County Reston", "Closes at 5pm Thurs more info at www.ymcadc.org"),
    ]
    assert {row.updated_text for row in listing.rows} == {"02/18/2021 03:46:12 PM EST"}


def test_nbc_new_york_route_of_22_february_2026() -> None:
    listing = nbc_owned.parse(_body("nbc-owned/wnbc-route-20260222153725.json"))
    assert [(row.name, row.status, row.extra["category"]) for row in listing.rows] == [
        ("Adelphi University Garden City", "CLOSED", "DUTCHESS"),
        ("Adelphi University Poughkeepsie Center", "CLOSED", "DUTCHESS"),
        ("Adelphi University Suffolk County Centers", "CLOSED", "DUTCHESS"),
        ("Hudson Co. Community College", "REMOTE ONLY", "DUTCHESS"),
        ("SUNY Old Westbury", "REMOTE ONLY", "DUTCHESS"),
        ("The Masters School", "CLOSED", "DUTCHESS"),
    ]
    assert all(row.updated_text is None for row in listing.rows)


NBC_ROUTES = [entry for entry in _own("nbc-owned") if entry.file.endswith(".json")]


@pytest.mark.parametrize("entry", NBC_ROUTES, ids=lambda entry: entry.file)
def test_nbc_route_rows_are_the_organizations_in_the_array(entry: FixtureEntry) -> None:
    items = json.loads(_body(entry.file))
    listing = nbc_owned.parse(_body(entry.file))
    assert [(row.name, row.status) for row in listing.rows] == [
        (" ".join(item["organization"].split()), " ".join(item["status"].split()))
        for item in items
        if item["organization"].strip()
    ]


def test_nbc_routes_of_the_march_2020_closures() -> None:
    philadelphia = nbc_owned.parse(_body("nbc-owned/wcau-route-20200316122302.json"))
    new_york = nbc_owned.parse(_body("nbc-owned/wnbc-route-20200313141145.json"))
    assert (len(philadelphia.rows), len(new_york.rows)) == (22, 27)
    assert (philadelphia.rows[0].name, philadelphia.rows[0].status) == (
        "All Delaware Schools",
        "Closed for 2 weeks",
    )
    assert (new_york.rows[0].name, new_york.rows[0].extra["category"]) == (
        "Croton-Harmon USFD",
        "DUTCHESS",
    )
    # NBC New York listed one district twice that day; both rows are kept.
    names = [row.name for row in new_york.rows]
    assert names.count("Englewood Cliffs School District") == 2


def test_nbc_california_and_miami_captures_are_all_empty() -> None:
    # Storm, fire and hurricane days included: the Los Angeles fires (9 January 2025),
    # the North Bay fires (October 2017), Eta (November 2020) and Milton (October 2024).
    for name in (
        "nbc-owned/knbc-page-20260210235627.html",
        "nbc-owned/knbc-page-20250109221051.html",
        "nbc-owned/knbc-route-20251218203605.json",
        "nbc-owned/knsd-page-20240206235932.html",
        "nbc-owned/knsd-page-20250121210850.html",
        "nbc-owned/kntv-page-20230225023108.html",
        "nbc-owned/kntv-page-20250110211815.html",
        "nbc-owned/kntv-page-20171012055347.html",
        "nbc-owned/wtvj-page-20201108015449.html",
        "nbc-owned/wtvj-page-20241009002117.html",
    ):
        listing = nbc_owned.parse(_body(name))
        assert (listing.state, listing.rows) == (ListingState.EMPTY, ()), name
    # Milton's eve: an active block whose one listing is blank.
    milton = nbc_owned.parse(_body("nbc-owned/wtvj-page-20241009002117.html"))
    assert milton.skipped_rows == 1


# FOX ------------------------------------------------------------------------------------

FOX_FILES = [entry for entry in _own("fox-owned") if "-file-" in entry.file]


@pytest.mark.parametrize("entry", FOX_FILES, ids=lambda entry: entry.file)
def test_fox_file_rows_are_the_names_in_the_markup(entry: FixtureEntry) -> None:
    body = _body(entry.file)
    try:  # the newer exports are UTF-8, the older ones Latin-1
        raw = body.decode("utf-8")
    except UnicodeDecodeError:
        raw = body.decode("latin-1")
    listing = fox_owned.parse(_body(entry.file))
    if entry.expected.variant == "fox-closings-table":
        expected = [_text(name) for name, _status in _TABLE_ROW.findall(raw)]
    elif entry.expected.variant == "gray-file-sc-para":
        expected = [_text(name) for name in _SC_NAME.findall(raw)]
    else:
        expected = [_text(_WEB.sub("", name)) for name in _ORGNAME.findall(raw)]
    assert [row.name for row in listing.rows] == expected
    assert (listing.state is ListingState.POPULATED) == bool(expected)
    assert listing.variant == entry.expected.variant


def test_fox_county_menu_file_with_rows() -> None:
    listing = fox_owned.parse(_body("fox-owned/kmsp-file-20240324220544.html"))
    assert listing.variant == "fox-newsticker-county"
    assert [(row.name, row.status) for row in listing.rows[:4]] == [
        ("Chetek-Weyerhaeuser Area School District", "Closed"),
        ("Comm. of Peace Academy", "Closed ; Closed Monday 3/25"),
        ("Edina District", "Delayed 2 hours"),
        ("Fergus Falls Public Schools", "Closed"),
    ]
    assert len(listing.rows) == 17
    assert {row.updated_text for row in listing.rows} == {"UPDATED SUNDAY, MAR 24 AT 5:05 PM"}
    assert all("county" not in row.extra for row in listing.rows)  # its one heading is blank


def test_fox_single_cell_export() -> None:
    dallas = fox_owned.parse(_body("fox-owned/kdfw-file-20250109195953.html"))
    assert (dallas.variant, len(dallas.rows)) == ("fox-newsticker-cell", 348)
    first = dallas.rows[0]
    assert (first.name, first.status, first.extra["category"], first.updated_text) == (
        "Aledo ISD",
        "Closed Tomorrow",
        "Aledo",
        "UPDATED THURSDAY, JAN 9 AT 1:57 PM",
    )
    mckinney = next(row for row in dallas.rows if row.name == "McKinney ISD")
    assert mckinney.extra["homepage"] == "http://www.mckinneyisd.net"
    seattle = fox_owned.parse(_body("fox-owned/kcpq-file-20260314152206.html"))
    (row,) = seattle.rows
    assert (row.name, "category" in row.extra) == ("UW Tacoma", False)
    assert row.status.startswith("Closed, but mission-essential staff report.")
    quiet = fox_owned.parse(_body("fox-owned/kcpq-file-20240101031234.html"))
    assert (quiet.variant, quiet.state) == ("fox-newsticker-cell", ListingState.EMPTY)


def test_fox_closings_table_with_rows() -> None:
    listing = fox_owned.parse(_body("fox-owned/wttg-file-20221215074338.html"))
    assert (listing.variant, len(listing.rows)) == ("fox-closings-table", 62)
    assert [(row.name, row.status) for row in listing.rows[:3]] == [
        ("Achievement Prep.Acad.", "2 hours delayed arrival"),
        ("Alexandria City Public Schools", "Delayed 2 hours"),
        ("Arlington County Public Schools", "Delayed 2 hours"),
    ]
    assert {row.updated_text for row in listing.rows} == {"December 15, 2022 2:40 am EST"}
    (single,) = fox_owned.parse(_body("fox-owned/wttg-file-20250104184041.html")).rows
    assert (single.name, single.status) == ("Culpeper County Public Schools", "Closed Monday")


def test_fox_6_tabbed_shell_names_its_list_files() -> None:
    raw = _body("fox-owned/witi-shell-20200127113059.html").decode("latin-1")
    shell = fox_owned.parse(_body("fox-owned/witi-shell-20200127113059.html"))
    loads = re.findall(r'\.load\( "([a-z_]+\.html)"', raw)
    assert (shell.variant, shell.state) == ("fox-tab-shell", ListingState.DEFERRED)
    assert shell.follows == tuple(dict.fromkeys(loads))
    assert shell.follows[:2] == ("witi_schools.html", "witi_biz.html")
    assert len(shell.follows) == 7


def test_fox_6_tab_list_rows_are_its_places() -> None:
    raw = _body("fox-owned/witi-tablist-20200417063108.html").decode("utf-8")
    listing = fox_owned.parse(_body("fox-owned/witi-tablist-20200417063108.html"))
    places = re.findall(
        r'<li class="ln-[^"]*"><span class="place">([^<]*) \| <span class="pstatus">([^<]*)</span>',
        raw,
    )
    assert raw.count("<li ") == len(places) == 42
    assert [(row.name, row.status) for row in listing.rows] == [
        (_text(name), _text(status)) for name, status in places
    ]
    assert (listing.variant, listing.rows[0].updated_text) == (
        "fox-tab-list",
        "Fri Apr 17 01:30:02 CDT 2020",
    )
    assert listing.rows[0].extra["category"] == "School Closings"


def test_fox_pages_before_their_current_design() -> None:
    protected = fox_owned.parse(_body("fox-owned/witi-page-20161011140953.html"))
    assert (protected.variant, protected.follows) == (
        "fox-page-protected-frame",
        ("http://s3.amazonaws.com/witiclosings/witi.html",),
    )
    quiet = fox_owned.parse(_body("fox-owned/witi-page-20200730224123.html"))
    assert (quiet.variant, quiet.state) == ("fox-page-no-closings", ListingState.EMPTY)
    new_york = fox_owned.parse(_body("fox-owned/wnyw-page-20170216035831.html"))
    assert new_york.follows == ("http://media2.fox5ny.com/closings/closing.htm",)
    minneapolis = fox_owned.parse(_body("fox-owned/kmsp-page-20240324220543.html"))
    assert minneapolis.follows == ("https://media.foxtv.com/kmsp/closings/closings.html",)


# CBS ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry",
    [
        entry
        for entry in _own("cbs-owned")
        if entry.expected.variant in {"gray-file-newsticker-xml", "cbs-newsticker-xml-short"}
    ],
    ids=lambda entry: entry.file,
)
def test_cbs_feed_rows_are_the_records_in_the_feed(entry: FixtureEntry) -> None:
    root = ElementTree.fromstring(_body(entry.file))  # noqa: S314 - a committed, real fixture
    expected = [
        _text(
            record.findtext("FORCED_ORGANIZATION_NAME")
            or record.findtext("ORGANIZATION_NAME1")
            or ""
        )
        for record in root.iter("RECORD")
    ]
    assert int(root.findtext("NUM_CLOSINGS") or "-1") == len(expected)
    listing = cbs_owned.parse(_body(entry.file))
    assert [row.name for row in listing.rows] == expected


def test_cbs_pittsburgh_feed_of_16_january_2024() -> None:
    listing = cbs_owned.parse(_body("cbs-owned/kdka-feed-20240116165448.xml"))
    assert len(listing.rows) == 24
    first = listing.rows[0]
    assert (first.name, first.status, first.updated_text) == (
        "Boys & Girls Clubs of Western PA",
        "Closed Tuesday",
        "2024-01-16 11:40:31",
    )


def test_cbs_detroit_feed_in_the_shorter_export() -> None:
    listing = cbs_owned.parse(_body("cbs-owned/wwj-feed-20260119143100.xml"))
    assert (listing.variant, listing.declared_count) == ("cbs-newsticker-xml-short", 7)
    assert [(row.name, row.status, row.extra["county_name1"]) for row in listing.rows] == [
        ("Boys and Girls Club - Dauch", "Closed", "WAYNE"),
        ("DK's Childcare Academy", "Closed", "WAYNE"),
        ("East China School District", "Closed", "ST. CLAIR"),
        ("Mary's Children Family Center", "Closed", "OAKLAND"),
        ("Freedom Work Oakland Co", "Closed", "OAKLAND"),
        ("Oakdale Academy", "Closed", "OAKLAND"),
        ("St. Thomas-Ann Arbor", "Closed", "WASHTENAW"),
    ]
    assert listing.rows[2].updated_text == "2026-01-19 05:00:38"
    philadelphia = cbs_owned.parse(_body("cbs-owned/kyw-feed-20260131112619.xml"))
    assert (philadelphia.variant, philadelphia.state) == ("gray-file-sc-xml", ListingState.EMPTY)


def test_cbs_colorado_file_and_older_pages() -> None:
    november = cbs_owned.parse(_body("cbs-owned/kcnc-file-20221119175006.html"))
    january = cbs_owned.parse(_body("cbs-owned/kcnc-file-20240117182845.html"))
    assert [(row.name, row.status) for row in november.rows] == [("CITC", "Closed Thursday")]
    assert [(row.name, row.status) for row in january.rows] == [("FIREFLY AUTISM", "Closed Monday")]
    pittsburgh = cbs_owned.parse(_body("cbs-owned/kdka-page-20220420165543.html"))
    assert pittsburgh.follows == (
        "https://static.cbslocal.com/Integrations/SchoolClosings/PRODUCTION/CBS/kdka/NEWSROOM/"
        "KDKAclosings.xml",
    )
    philadelphia = cbs_owned.parse(_body("cbs-owned/kyw-page-20240106034957.html"))
    assert philadelphia.follows == (
        "https://assets1.cbsnewsstatic.com/Integrations/SchoolClosings/PRODUCTION/CBS/kyw/"
        "NEWSROOM/BTI/KYW-closingsC.xml",
    )


# Emergency Closing Center ---------------------------------------------------------------

ECC_ARCHIVED = [entry for entry in _own("ecc") if entry.file.endswith(".json")]
_ECC_LEGACY_ROW = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>&nbsp;</td>\s*<td><p class=text>(.*?)</p></td>\s*<td>&nbsp;</td>"
    r"\s*<td><p class=text>(.*?)</p></td>\s*<td>&nbsp;</td>\s*<td><p class=text>(.*?)</p></td>"
    r"\s*</tr>",
    re.DOTALL,
)


@pytest.mark.parametrize("entry", ECC_ARCHIVED, ids=lambda entry: entry.file)
def test_ecc_rows_are_the_file_s_closings(entry: FixtureEntry) -> None:
    data = json.loads(_body(entry.file))
    listing = ecc.parse(_body(entry.file))
    closings = data.get("Closing", [])
    assert [row.name for row in listing.rows] == [
        " ".join(item["Name1"][0].split()) for item in closings
    ]
    assert [row.status for row in listing.rows] == [
        " | ".join(
            " ".join(text.split()) for text in item["Status1"] + item["Status2"] if text.strip()
        )
        for item in closings
    ]
    assert {row.updated_text for row in listing.rows} <= {data["$"]["Time"]}
    for row, item in zip(listing.rows, closings, strict=True):
        for key in ("City", "County", "State", "EntityType", "UpdateTime", "ID", "StatusCode"):
            assert row.extra[key] == item[key][0]


def test_ecc_legacy_page_of_6_january_2014() -> None:
    raw = _body("ecc/chicago-legacy-20140106060437.html").decode("utf-8")
    listing = ecc.parse(_body("ecc/chicago-legacy-20140106060437.html"))
    lines = [tuple(_text(cell) for cell in row) for row in _ECC_LEGACY_ROW.findall(raw)]
    assert raw.count("<tr") == len(lines) + 1  # every row but the heading row
    # A line with no name and no city is a second status of the facility above it.
    expected: list[tuple[str, str, list[str]]] = []
    for name, city, status in lines:
        if name:
            expected.append((name, city, [status]))
        else:
            assert city == ""
            expected[-1][2].append(status)
    assert len(expected) == 3274
    assert sum(len(statuses) == 2 for _n, _c, statuses in expected) == 243
    assert [(row.name, row.extra["City"], row.status) for row in listing.rows] == [
        (name, city, " | ".join(statuses)) for name, city, statuses in expected
    ]
    assert (listing.variant, listing.state) == ("ecc-legacy-page", ListingState.POPULATED)
    assert {row.updated_text for row in listing.rows} == {"11:50 PM, CST"}
    assert [(row.name, row.status) for row in listing.rows[:3]] == [
        ("21ST CENTURY PREPARATORY CENTER", "(TOMORROW) CLOSED"),
        ("A CHILDS SPACE", "(TODAY) CLOSED | (TOMORROW) CLOSED"),
        ("A PLUS DAY SCHOOL", "(TOMORROW) CLOSED"),
    ]
    assert listing.rows[-1].name == "ZION LUTHERAN SCHOOL (ON W. 216TH ST.)"


def test_ecc_file_of_20_january_2025() -> None:
    listing = ecc.parse(_body("ecc/chicago-json-20250121040204.json"))
    assert len(listing.rows) == 203
    assert [(row.name, row.status, row.extra["County"]) for row in listing.rows[:4]] == [
        ("CHICAGO COMMONS CHILD DEVELOPMENT-ALL LOCATIONS", "Closed Tomorrow", "COOK"),
        ("DIST #46 (COMMUNITY CONSOLIDATED SCHOOL)", "E-Learning", "LAKE (IL)"),
        (
            "DIST #365(VALLEY VIEW DIST/ROMEOVILLE/BOLINGBROOK)",
            "Closed Tomorrow | E-Learning",
            "WILL",
        ),
        ("NOTRE DAME HIGH SCHOOL (BOYS)", "Closed Tomorrow | E-Learning", "COOK"),
    ]
    assert Counter(row.extra["EntityType"] for row in listing.rows) == {
        "01 - Public School": 103,
        "02 - Private School": 71,
        "03 - College/University": 3,
        "04 - Day Care Facility": 15,
        "05 - Religious": 7,
        "06 - Government": 2,
        "07 - Business/Organization": 2,
    }
    assert {row.updated_text for row in listing.rows} == {"01/20/2025 10:00:31 PM"}


def test_ecc_small_files_row_by_row() -> None:
    august = ecc.parse(_body("ecc/chicago-json-20260811211402.json"))
    assert [
        (row.name, row.status, row.extra["City"], row.extra["State"]) for row in august.rows
    ] == [
        ("DIST #206 (BLOOM HIGH SCHOOLS)", "Closed Tomorrow | E-Learning", "CHICAGO", "IL"),
        ("CITY OF HOBART SCHOOLS", "Closed Tomorrow", "HOBART", "IN"),
        ("CROWN POINT COMMUNITY SCHOOL CORP", "Closed Tomorrow", "CROWN POINT ", "IN"),
        ("VALPARAISO COMMUNITY SCHOOLS", "Closed Tomorrow", "VALPARAISO", "IN"),
        ("VALPARAISO UNIVERSITY", "Closed Today", "VALPARAISO", "IN"),
    ]
    january = ecc.parse(_body("ecc/chicago-json-20260122024138.json"))
    assert [(row.name, row.status, row.extra["EntityType"]) for row in january.rows] == [
        ("ASHBURN CHRISTIAN ACADEMY", "Closed Friday", "02 - Private School"),
        ("GRACE LUTHERAN SCHOOL", "Closed Friday", "02 - Private School"),
        ("ST. JOHN THE BAPTIST CATHOLIC SCHOOL", "Closed Friday", "02 - Private School"),
        ("ELEMENT GLENDALE HEIGHTS", "Work at Home", "07 - Business/Organization"),
    ]
    christmas = ecc.parse(_body("ecc/chicago-json-20231226001930.json"))
    assert (christmas.state, christmas.rows) == (ListingState.EMPTY, ())


# FlashAlert ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry",
    [entry for entry in _own("flashalert") if "-site-" not in entry.file],
    ids=lambda entry: entry.file,
)
def test_flashalert_rows_are_the_bold_names_in_the_report(entry: FixtureEntry) -> None:
    raw = _body(entry.file).decode("latin-1")
    reports = _FLASH_REPORT.findall(raw)
    expected = [_text(match.group(1)) for item in reports if (match := _FLASH_NAME.match(item))]
    listing = flashalert.parse(_body(entry.file))
    assert [row.name for row in listing.rows] == expected
    if not expected:
        assert [_text(item) for item in reports] == ["No information reported."]


def test_flashalert_columbia_report_of_14_february_2019() -> None:
    listing = flashalert.parse(_body("flashalert/columbia-report-20190215030813.html"))
    assert [(row.name, row.extra["category"]) for row in listing.rows] == [
        ("ESD 123", "Tri-Cities-area School Districts"),
        ("Kiona-Benton City Sch. Dist.", "Tri-Cities-area School Districts"),
        ("Prosser Sch. Dist.", "Tri-Cities-area School Districts"),
        ("Grandview Sch. Dist.", "Yakima-area School Districts"),
        ("Mabton School District", "Yakima-area School Districts"),
        ("Wahluke Sch. Dist.", "Yakima-area School Districts"),
        ("Ellensburg Sch. Dist.", "Central Wash. School Districts"),
        ("Calvary Christian School", "Private Schools"),
        ("West Side Church - Richland", "Churches"),
        ("Benton Franklin Head Start", "Organizations"),
        ("Childrens Developmental Center", "Organizations"),
    ]
    wahluke = listing.rows[5]
    assert wahluke.status == "Closed (For Fri. Feb 15th)"
    assert wahluke.updated_text == (
        "Columbia (Tri-Cities/Yakima/Pendleton) Emergency Info for Thu. Feb. 14 - 7:08 pm"
    )


def test_flashalert_address_with_no_region_is_region_1_s_report() -> None:
    bare = [
        entry
        for entry in _own("flashalert")
        if entry.url.endswith("/IIN/reportsX/cwc-closures.php")
    ]
    assert len(bare) == 4
    for entry in bare:
        assert entry.source_id == "flashalert-portland"
        header = re.search(
            r"<div id='cwcReportHeader'>(.*?)</div>", _body(entry.file).decode("latin-1"), re.S
        )
        assert header is not None
        assert _text(header.group(1)).startswith("Portland/Vanc/Salem Emergency Info for ")
    february = flashalert.parse(_body("flashalert/portland-bare-20250215044644.html"))
    assert len(february.rows) == 26
    schools = [
        (row.extra["category"], row.name)
        for row in february.rows
        if str(row.extra["category"]).endswith("Schools")
    ]
    assert schools == [
        ("Multnomah Co. Schools", "Centennial Sch. Dist."),
        ("Washington Co. Schools", "Gaston Sch. Dist."),
        ("Washington Co. Schools", "Tigard-Tualatin Sch. Dist."),
        ("Columbia Co. Schools", "Rainier (OR) Sch. Dist."),
        ("Columbia Co. Schools", "Scappoose Sch. Dist."),
        ("Clark Co. Schools", "Evergreen Sch. Dist."),
        ("Clark Co. Schools", "La Center Sch. Dist."),
        ("Cowlitz Co. & Lower Columbia (WA) Schools", "Kelso Sch. Dist."),
        ("Columbia Gorge Schools", "Klickitat Sch. Dist."),
    ]
    assert february.rows[0].updated_text == (
        "Portland/Vanc/Salem Emergency Info for Fri. Feb. 14 - 8:46 pm"
    )
    fifth = flashalert.parse(_body("flashalert/portland-bare-20250206025348.html"))
    assert [row.name for row in fifth.rows] == [
        "State Building Closures - Medford/Klamath Falls, Ore.",
        "Tillamook Co. Circuit Court",
        "Northwest Regional ESD",
        "Tillamook Sch. Dist.",
        "Northwest Senior & Disability Services",
        "St. Vincent de Paul, Portland Council",
    ]
    sherman = flashalert.parse(_body("flashalert/portland-bare-20241211185820.html"))
    assert [row.name for row in sherman.rows] == ["Sherman Co. Sch. Dist."]


_SITE_ROW = re.compile(r"<div class=[\"']cwcReport(?:LR)?[\"']", re.IGNORECASE)
_SITE_GROUP = re.compile(r"<span class=[\"']GroupCount[\"']>\((\d+)\)")
SITE_PAGES = [entry for entry in _own("flashalert") if "-site-" in entry.file]


@pytest.mark.parametrize("entry", SITE_PAGES, ids=lambda entry: entry.file)
def test_flashalert_site_rows_are_the_reports_on_the_page(entry: FixtureEntry) -> None:
    raw = _body(entry.file).decode("latin-1")
    listing = flashalert.parse(_body(entry.file))
    assert listing.variant == "flashalert-site-page"
    reports = len(_SITE_ROW.findall(raw))
    if flashalert.SITE_EMPTY in raw:
        assert (reports, listing.state, listing.rows) == (1, ListingState.EMPTY, ())
        return
    assert len(listing.rows) == reports
    counts = [int(n) for n in _SITE_GROUP.findall(raw)]
    kept = {row.extra["category_count"] for row in listing.rows if "category_count" in row.extra}
    assert kept == set(counts)
    header = re.search(r"<div id=[\"']cwcReportHeader[\"']>(.*?)</div>", raw, re.S)
    assert header is not None
    assert {row.updated_text for row in listing.rows} == {_text(header.group(1))}


def test_flashalert_eugene_site_of_28_february_2019() -> None:
    listing = flashalert.parse(_body("flashalert/eugene-site-20190228093207.html"))
    by_time = flashalert.parse(_body("flashalert/eugene-site-20190228093212.html"))
    assert len(listing.rows) == len(by_time.rows) == 43
    assert sorted(row.name for row in listing.rows) == sorted(row.name for row in by_time.rows)
    lane = [
        (row.name, row.status)
        for row in listing.rows
        if row.extra["category"] == "Lane Co. Schools"
    ]
    assert [name for name, _status in lane] == [
        "Bethel Sch. Dist. (OR)",
        "Blachly Sch. Dist.",
        "Creswell Sch. Dist.",
        "Crow-Applegate-Lorane Sch. Dist.",
        "Eugene School District 4J",
        "Fern Ridge Sch. Dist.",
        "Head Start of Lane Co.",
        "Junction City Sch. Dist.",
        "Lane ESD",
        "Lowell Sch. Dist.",
        "McKenzie Sch. Dist.",
        "Oakridge Sch. Dist.",
        "Pleasant Hill Sch. Dist.",
        "South Lane Sch. Dist.",
        "Springfield Sch. Dist.",
        "Twin Rivers Charter School",
    ]
    assert lane[1] == ("Blachly Sch. Dist.", "Closed")
    assert lane[12] == ("Pleasant Hill Sch. Dist.", "Closed UPDATE")
    slocum = listing.rows[0]
    assert (slocum.name, slocum.status, slocum.extra["name_linked"]) == (
        "Slocum Orthopedics",
        "Office Opening at 8:30",
        False,
    )
    assert slocum.extra["posted"] == "Posted: Wed. 27th, 03:59 PM"
    assert (
        slocum.updated_text
        == "Eugene/Spring/Rose/Alb/Corv Emerg. Reports for Thu. Feb. 28 - 1:32 am"
    )


def test_flashalert_site_pages_in_message_order_and_other_regions() -> None:
    eugene = flashalert.parse(_body("flashalert/eugene-site-20180226132826.html"))
    assert [(row.extra["category"], row.name, row.status) for row in eugene.rows] == [
        ("2 Hours Late", "Junction City Sch. Dist.", "2 Hours Late, AM/PM Buses on snow routes"),
        ("2 Hours Late", "Oakridge Sch. Dist.", "2 Hours Late"),
        (
            "Custom Report",
            "ODOT: SW Oregon",
            "Drivers should expect winter driving conditions this morning in southwest Oregon."
            " State highways are clear in the western valleys but chains are required over I-5"
            " Siskiyou Summit, except 4x4s. Cascade mountain passes have packed snow. Watch for"
            " slick, slushy conditions. Leave extra time for your commute and drive defensively."
            " Monitor Tripcheck for conditions.",
        ),
        ("Custom Report", "McKenzie Sch. Dist.", "AM/PM Buses on snow routes"),
    ]
    bend = flashalert.parse(_body("flashalert/bend-site-20170109085732.html"))
    assert [row.name for row in bend.rows] == ["Mid-Columbia Children's Council", "State of Oregon"]
    assert all("category" not in row.extra for row in bend.rows)
    medford_cats = flashalert.parse(_body("flashalert/medford-site-20170105163147.html"))
    assert [(row.extra["category"], row.name) for row in medford_cats.rows] == [
        ("State", "State of Oregon"),
        ("Southern Ore. Schools", "Jackson County EI/ECSE"),
        ("Southern Ore. Schools", "Port Orford/Langlois Sch. Dist."),
        ("Private & Charter Schools", "St. Mary's School"),
        ("Douglas Co. Schools", "South Umpqua Sch. Dist."),
        ("Douglas Co. Schools", "Sutherlin Sch. Dist."),
        ("Courts/District Attorneys", "U.S. District Court - Medford"),
        ("Organizations", "Oregon Child Development Coalition"),
    ]
    assert medford_cats.rows[5].status == "2 Hours Late, Buses on snow routes UPDATE"
    medford = flashalert.parse(_body("flashalert/medford-site-20170106124728.html"))
    assert [(row.extra["category"], row.name, row.status) for row in medford.rows] == [
        (
            "Douglas Co. Schools",
            "South Umpqua Sch. Dist.",
            "Buses on snow routes. On regular schedule UPDATE",
        ),
        ("Private & Charter Schools", "St. Mary's School", "Closed"),
        ("Southern Ore. Schools", "Jackson County EI/ECSE", "Closed"),
        ("Courts/District Attorneys", "U.S. District Court - Medford", "Opening at 10 am"),
    ]
    bandon = flashalert.parse(_body("flashalert/eugene-site-20200318051145.html"))
    assert [(row.name, row.status) for row in bandon.rows] == [
        ("Bandon Sch. Dist.", "Closed. March 18 through April 28 UPDATE")
    ]
    seattle = flashalert.parse(_body("flashalert/seattle-site-20170206144203.html"))
    assert len(seattle.rows) == 232
    storm = flashalert.parse(_body("flashalert/portland-site-20230223230724.html"))
    assert len(storm.rows) == 296
    # The page's own category count leaves some postings out; it is kept, not checked.
    transport = [row for row in storm.rows if row.extra["category"] == "Transportation"]
    assert (len(transport), transport[0].extra["category_count"]) == (3, 2)
    portland = flashalert.parse(_body("flashalert/portland-site-live-20260927212834.html"))
    assert [(row.name, row.extra["category"]) for row in portland.rows] == [
        ("ODOT: PDX, Mt. Hood", "Transportation")
    ]


def test_flashalert_region_reports_in_other_years() -> None:
    march = flashalert.parse(_body("flashalert/columbia-report-20200317034110.html"))
    assert [(row.name, row.extra["category"]) for row in march.rows] == [
        ("Bethlehem Lutheran School", "Private Schools"),
        ("Benton Franklin Head Start", "Organizations"),
    ]
    for name in (
        "flashalert/colorado-springs-report-20111208041507.html",
        "flashalert/bend-report-20251010210220.html",
    ):
        listing = flashalert.parse(_body(name))
        assert (listing.state, listing.rows) == (ListingState.EMPTY, ()), name
