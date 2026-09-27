"""The list files Gray station pages load today, read live (round 3).

Each fixture is a real live body `snowlight stations fetch` read on 2026-09-26 from
the data_url the station's page check recorded (see fixtures/README.md): the
NewsTicker files WFSB's and Western Mass News's closings pages frame on
webpubcontent.gray.tv (their S3 exports were last written in 2022), KAKE's NewsTicker
XML, and the files WAND, WJRT, WLFI, WLIO and WTHI frame.
"""

from pathlib import Path

import pytest

from snowlight.sources.stations import fixtures, gray
from snowlight.sources.stations.model import Listing, ListingState
from snowlight.sources.stations.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "gray"

WFSB_NAMES = (
    "First Church/Christ Cong-E Haddam",
    "First Congregational Ch-Plainfield",
    "First Spiritualist Ch-Willimantic",
    "MDC-All Recreational Facilities",
    "North Congregational Ch-New Htfd",
    "North Stonington Cong Ch",
    "Prince of Peace Lutheran Ch-Coventry",
    "Second Cong Ch-Stafford Sprgs",
    "St James Episcopal Ch-New London",
    "St Pio Faith Formation",
    "VFW Post 6851 - North Canaan",
)


def _read(name: str) -> Listing:
    return gray.parse((FIXTURES / name).read_bytes())


def test_wfsb_reads_the_file_its_page_frames_name_by_name() -> None:
    listing = _read("wfsb-file-live-20260926231420.html")
    assert (listing.variant, listing.state) == ("gray-file-newsticker", ListingState.POPULATED)
    assert tuple(row.name for row in listing.rows) == WFSB_NAMES
    first = listing.rows[0]
    assert first.status == "No Services Tomorrow; No Religious Ed."
    assert first.updated_text == "UPDATED SATURDAY, SEP 26 AT 7:12 PM"
    assert first.extra == {"updated_scope": "page"}
    assert listing.rows[3].status == "Closed Thru Tomorrow"


def test_wggb_reads_the_file_its_page_frames() -> None:
    listing = _read("wggb-file-live-20260926231424.html")
    assert [(row.name, row.status) for row in listing.rows] == [
        ("Hope United Methodist Church", "No AM Services; Closed Sunday")
    ]


@pytest.mark.parametrize(
    ("name", "variant"),
    [
        ("kake-newsticker-live-20260926230844.xml", "gray-file-newsticker-xml"),
        ("wand-file-live-20260926231244.html", "gray-file-grid"),
        ("wjrt-file-live-20260926231509.html", "gray-file-newsticker"),
        ("wlfi-file-live-20260926231515.html", "gray-file-newsticker"),
        ("wlio-file-live-20260926231520.html", "gray-file-newsticker"),
        ("wthi-file-live-20260926231635.html", "gray-file-newsticker"),
    ],
)
def test_empty_live_files_say_so_in_their_own_words(name: str, variant: str) -> None:
    listing = _read(name)
    assert (listing.variant, listing.state, listing.rows) == (variant, ListingState.EMPTY, ())


def test_kake_xml_declares_its_count() -> None:
    listing = _read("kake-newsticker-live-20260926230844.xml")
    assert listing.declared_count == 0


def test_each_fixture_is_its_stations_live_data_url() -> None:
    stations = load_registry().stations
    pairs = {
        "gray-wfsb": "wfsb-file-live-20260926231420.html",
        "gray-wggb": "wggb-file-live-20260926231424.html",
        "gray-kake": "kake-newsticker-live-20260926230844.xml",
        "gray-wand": "wand-file-live-20260926231244.html",
        "gray-wjrt": "wjrt-file-live-20260926231509.html",
        "gray-wlfi": "wlfi-file-live-20260926231515.html",
        "gray-wlio": "wlio-file-live-20260926231520.html",
        "gray-wthi": "wthi-file-live-20260926231635.html",
    }
    entries = {entry.file: entry for entry in fixtures.load_entries(FIXTURES.parent)}
    for station_id, name in pairs.items():
        entry = entries[f"gray/{name}"]
        assert entry.source_id == station_id
        assert entry.url == stations[station_id].data_url
