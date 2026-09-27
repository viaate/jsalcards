"""The network-owned, ECC and FlashAlert adapters against their real fixtures.

Every fixture in fixtures/networks/ is a real body (a live read or a Wayback
capture) with its provenance in PROVENANCE.json; each is read here with its
adapter and must give exactly the recorded variant, state and row names.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

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
from snowlight.sources.stations.adapters import ADAPTERS
from snowlight.sources.stations.fixtures import FixtureEntry
from snowlight.sources.stations.model import ListingState, ReadMode

FOLDER = Path(__file__).parent / "fixtures" / "networks"
ENTRIES = network_fixtures.load_entries(FOLDER)
PLATFORMS = {"abc-owned", "nbc-owned", "fox-owned", "cbs-owned", "ecc", "flashalert"}


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def test_every_platform_has_live_fixtures() -> None:
    live = {entry.adapter for entry in ENTRIES if entry.mode is ReadMode.LIVE}
    assert live == PLATFORMS
    assert len(ENTRIES) == 174


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda entry: entry.file)
def test_fixture_reads_exactly_as_recorded(entry: FixtureEntry) -> None:
    body = _body(entry.file)
    assert hashlib.sha256(body).hexdigest() == entry.sha256
    assert len(body) == entry.bytes
    listing = ADAPTERS[entry.adapter](body)
    assert listing.variant == entry.expected.variant
    assert listing.state is entry.expected.state
    assert tuple(row.name for row in listing.rows) == entry.expected.names
    assert len(listing.rows) == entry.expected.rows
    # A slice is stable: slicing it again changes nothing.
    assert network_fixtures.SLICERS[entry.slice](body) == body
    if entry.mode is ReadMode.ARCHIVE:
        assert entry.archive_url is not None
        assert entry.archive_url.startswith("https://web.archive.org/web/")
    else:
        assert entry.archive_url is None


def test_readme_is_rendered_from_the_provenance() -> None:
    expected = network_fixtures.render_readme(ENTRIES)
    assert (FOLDER / network_fixtures.README_FILE).read_text(encoding="utf-8") == expected


# ABC ------------------------------------------------------------------------------------


def test_abc_pages_say_when_their_list_last_changed() -> None:
    new_york = abc_owned.parse(_body("abc-owned/wabc-page-live-20260927013716.html"))
    los_angeles = abc_owned.parse(_body("abc-owned/kabc-page-live-20260927013721.html"))
    assert (new_york.state, los_angeles.state) == (ListingState.EMPTY, ListingState.EMPTY)
    assert new_york.list_updated_at == datetime(2026, 9, 26, 1, 5, 16, tzinfo=UTC)
    # Los Angeles's list last changed in February 2019: stale for the live reader.
    assert los_angeles.list_updated_at == datetime(2019, 2, 12, 20, 39, 39, tzinfo=UTC)


def test_wls_frames_a_file_in_place_of_its_list() -> None:
    listing = abc_owned.parse(_body("abc-owned/wls-page-live-20260927013726.html"))
    assert listing.state is ListingState.DEFERRED
    assert listing.follows == ("https://wgnr-closings.s3.amazonaws.com/index.html",)


# NBC ------------------------------------------------------------------------------------


def test_nbc_route_rows_keep_their_fields() -> None:
    listing = nbc_owned.parse(_body("nbc-owned/wbts-route-live-20260927013737.json"))
    assert [(row.name, row.status, row.extra["state"]) for row in listing.rows] == [
        ("Bristol Community College", "Closed Saturday", "ma"),
        ("Quincy College, Plymouth Campus", "Closed", "ma"),
        ("Quincy College, Quincy Campus", "Closed", "ma"),
        ("St. James Episcopal New London", "No AM Services", "ct"),
        ("St. James Episcopal New London", "3 Hour Delay", "ct"),
    ]
    assert all(row.extra["category"] == "DUTCHESS" for row in listing.rows)
    assert all(row.updated_text is None for row in listing.rows)


def test_nbc_tabbed_page_reads_rows_from_the_state_panes() -> None:
    listing = nbc_owned.parse(_body("nbc-owned/wbts-page-live-20260927013752.html"))
    assert [(row.name, row.extra["state"]) for row in listing.rows] == [
        ("Bristol Community College", "Massachusetts"),
        ("Quincy College, Plymouth Campus", "Massachusetts"),
        ("Quincy College, Quincy Campus", "Massachusetts"),
        ("St. James Episcopal New London", "Connecticut"),
        ("St. James Episcopal New London", "Connecticut"),
    ]
    assert {row.updated_text for row in listing.rows} == {"09/26/2026 09:12:42 PM EDT"}


def test_nbc_empty_pages() -> None:
    inactive = nbc_owned.parse(_body("nbc-owned/kxas-page-live-20260927013759.html"))
    blank = nbc_owned.parse(_body("nbc-owned/wtvj-page-live-20260927013804.html"))
    assert (inactive.state, inactive.skipped_rows) == (ListingState.EMPTY, 0)
    assert (blank.state, blank.skipped_rows) == (ListingState.EMPTY, 1)


# FOX ------------------------------------------------------------------------------------


def test_fox_pages_are_followed_to_their_files() -> None:
    detroit = fox_owned.parse(_body("fox-owned/wjbk-page-live-20260927013834.html"))
    dc = fox_owned.parse(_body("fox-owned/wttg-page-live-20260927013840.html"))
    assert detroit.follows == ("https://media.foxtv.com/wjbk/closings/closings.html",)
    assert dc.follows == ("https://media.foxtv.com/wttg/closings/closings.html",)


def test_fox_file_formats_read_empty_and_populated() -> None:
    county = fox_owned.parse(_body("fox-owned/kmsp-file-live-20260927013814.html"))
    table = fox_owned.parse(_body("fox-owned/wttg-file-live-20260927013824.html"))
    newsticker = fox_owned.parse(_body("fox-owned/wjrt-newsticker-20251210020212.html"))
    para = fox_owned.parse(_body("fox-owned/wlfi-sc-para-20220201164300.htm"))
    assert (county.variant, county.state) == ("fox-newsticker-county", ListingState.EMPTY)
    assert (table.variant, table.state) == ("fox-closings-table", ListingState.EMPTY)
    first = newsticker.rows[0]
    assert (first.name, first.status, first.updated_text) == (
        "Akron/Fairgrove Schools",
        "Closed Tomorrow; Closed",
        "UPDATED TUESDAY, DEC 9 AT 9:02 PM",
    )
    assert [(row.name, row.status, row.extra["group"]) for row in para.rows] == [
        (
            "Leggett & Platt",
            "Closed Wendesday - Friday C Shift Resumes Production Saturday",
            "Small Business",
        ),
        ("West Lafayette Public Library", "Closed Wednesday and Thursday", "Government"),
    ]


# CBS ------------------------------------------------------------------------------------


def test_cbs_pages_name_their_feed_or_frame() -> None:
    boston = cbs_owned.parse(_body("cbs-owned/wbz-page-live-20260927013911.html"))
    colorado = cbs_owned.parse(_body("cbs-owned/kcnc-page-live-20260927013916.html"))
    assert (boston.variant, boston.follows) == (
        "cbs-widget-page",
        (
            "https://assets1.cbsnewsstatic.com/Integrations/SchoolClosings/PRODUCTION/CBS/"
            "wbz/NEWSROOM/chyron/closings.xml",
        ),
    )
    assert (colorado.variant, colorado.follows) == (
        "cbs-frame-page",
        (
            "https://static.cbslocal.com/Integrations/SchoolClosings/PRODUCTION/CBS/"
            "kcnc/NEWSROOM/closings.html",
        ),
    )


def test_cbs_feed_rows() -> None:
    boston = cbs_owned.parse(_body("cbs-owned/wbz-feed-live-20260927013850.xml"))
    worcester = boston.rows[0]
    assert (worcester.name, worcester.status, worcester.updated_text) == (
        "Worcester Public Schools",
        "Early Release Day",
        "2026-06-11 20:20:41",
    )
    assert worcester.extra["zipcode"] == "01609"
    kyw_format = cbs_owned.parse(_body("cbs-owned/wnem-sc-20201210023135.xml"))
    assert [(row.name, row.status) for row in kyw_format.rows] == [
        ("SS.Francis & Clare Birch Run", "Masses Canceled due to Covid")
    ]


# ECC and FlashAlert -------------------------------------------------------------------------


def test_ecc_file_and_application_page() -> None:
    data = ecc.parse(_body("ecc/chicago-json-live-20260927013921.json"))
    app = ecc.parse(_body("ecc/chicago-app-live-20260927013926.html"))
    assert (data.variant, data.state) == ("ecc-json", ListingState.EMPTY)
    assert (app.variant, app.state, app.follows) == ("ecc-app", ListingState.DEFERRED, ())


def test_flashalert_region_report_during_the_2024_ice_storm() -> None:
    listing = flashalert.parse(_body("flashalert/kptv-copy-20240115042338.html"))
    first = listing.rows[0]
    assert first.name == "Chemeketa Community College"
    assert first.extra["category"] == "Colleges & Universities - Public"
    assert first.updated_text == "Portland/Vanc/Salem School Closures for Sun. Jan. 14 - 8:20 pm"
    xml = flashalert.parse(_body("flashalert/portland-xml-live-20260927013936.xml"))
    assert (xml.variant, xml.state) == ("flashalert-emergency-xml", ListingState.EMPTY)


def test_flashalert_address_with_no_region_answers_region_1_s_report() -> None:
    by_file = {entry.file: entry for entry in ENTRIES}
    bare = by_file["flashalert/portland-bare-live-20260927194337.html"]
    region = by_file["flashalert/portland-report-live-20260927194342.html"]
    assert bare.url == "https://www.flashalertnewswire.net/IIN/reportsX/cwc-closures.php"
    assert region.url == flashalert.REPORT_URL.format(1)
    assert bare.source_id == region.source_id == "flashalert-portland"
    # Read 5 s apart, the two addresses answered the same bytes.
    assert bare.original_sha256 == region.original_sha256
    assert _body(bare.file) == _body(region.file)
    listing = flashalert.parse(_body(bare.file))
    assert [(row.name, row.extra["category"]) for row in listing.rows] == [
        ("ODOT: PDX, Mt. Hood", "Transportation")
    ]
    assert listing.rows[0].updated_text == (
        "Portland/Vanc/Salem Emergency Info for Sun. Sep. 27 - 12:43 pm"
    )
    assert b"participants.html?RegionID=1" in _body(bare.file)
