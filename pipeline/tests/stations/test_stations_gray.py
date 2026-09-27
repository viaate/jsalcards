"""The Gray adapter against real archived station pages and exports (fixtures/gray/).

Fixtures are Wayback ``id_`` captures: station pages sliced with ``gray-page-v1``
(only the page's ``gsync-closings`` cache member is kept, byte for byte) and S3
exports kept whole; see fixtures/README.md for each one's URL and capture time.
The expected names and fields below were read from the fixtures with ``grep``,
independently of the adapter.
"""

from pathlib import Path

import pytest

from snowlight.sources.stations import gray
from snowlight.sources.stations.model import ListingState

FIXTURES = Path(__file__).parent / "fixtures" / "gray"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_kctv_january_2024_page_lists_every_organization() -> None:
    listing = gray.parse(body("kctv-20240115205330.html"))
    assert listing.variant == "gray-fusion-orgs"
    assert listing.state is ListingState.POPULATED
    assert listing.declared_count == 21
    assert [row.name for row in listing.rows] == [
        "Calhoun R-VIII Schools Calhoun MO",
        "Chillicothe R-II Sch. Chillicothe MO",
        "Crest Ridge R-7 School Centerview MO",
        "Guadalupe Centers Charter School",
        "Holden R-III School Holden MO",
        "Hume R-VIII School Hume MO",
        "Kansas City MO Public Schools",
        "Kingston School 42  Kingston MO",  # the page's double space is kept
        "Kingsville R-I School Kingsville MO",
        "Lakeview Woods State School LSMO",
        "Leeton R-X School Leeton MO",
        "Lexington R-V School Lexington MO",
        "North Nodaway Co. R-VI Sch. Hopkins MO",
        "Oak Grove R-VI Schools Oak Grove MO",
        "Odessa R-VII Schools Odessa MO",
        "Orrick R-XI Schools Orrick MO",
        "Prairie View USD 362",
        "Richmond R-XVI School Richmond MO",
        "Stanberry R-II School Stanberry MO",
        "SW Livingston Co. R-I School Ludlow MO",
        "Trinity United Church Lexington MO",
    ]
    kcps = listing.rows[6]
    assert kcps.status == "Virtual Learning Tuesday"
    assert kcps.updated_text == "2024-01-15"
    assert kcps.extra["id"] == "87760"
    assert kcps.extra["county"] == "Na"
    assert kcps.extra["address.zipcode"] == "64106"
    assert kcps.extra["comments"] == "[]"
    assert kcps.extra["category"] == "Schools"


def test_wctv_january_2025_single_district_with_no_update_date() -> None:
    listing = gray.parse(body("wctv-20250119222021.html"))
    (row,) = listing.rows
    assert row.name == "Leon County Schools"
    assert row.status == "Closed Wednesday"
    assert row.updated_text is None
    assert row.extra["category"] == "FL School Districts"
    assert row.extra["stateAabbreviation"] == "FL"


@pytest.mark.parametrize(
    ("name", "rows"), [("wmtv-20240116142131.html", 35), ("wlox-20250121184426.html", 42)]
)
def test_larger_pages_match_their_declared_totals(name: str, rows: int) -> None:
    listing = gray.parse(body(name))
    assert len(listing.rows) == rows
    assert listing.declared_count == rows


def test_weau_december_2023_page_is_explicitly_empty() -> None:
    listing = gray.parse(body("weau-20231211050919.html"))
    assert (listing.variant, listing.state, listing.declared_count) == (
        "gray-fusion-orgs",
        ListingState.EMPTY,
        0,
    )


def test_2026_pages_carry_only_a_count() -> None:
    wkyt = gray.parse(body("wkyt-20260127004608.html"))
    assert (wkyt.variant, wkyt.state, wkyt.declared_count) == (
        "gray-fusion-count",
        ListingState.COUNT_ONLY,
        318,
    )
    assert wkyt.rows == ()
    wlbt = gray.parse(body("wlbt-20260118062311.html"))
    assert (wlbt.state, wlbt.declared_count) == (ListingState.EMPTY, 0)


def test_kwch_march_2025_export_rows_keep_every_raw_field() -> None:
    listing = gray.parse(body("kwch-export-20250319101557.json"))
    assert listing.variant == "gray-s3-json"
    assert listing.declared_count == 7
    assert [row.name for row in listing.rows] == [
        "Finney County Friendship Meals",
        "Finney County Meals on Wheels",
        "Finney County Retired &amp; Senior",  # the export's own HTML escape, kept raw
        "Finney County Transit",
        "Rolling Hills Zoo - Salina",
        "Fort Hays State University",
        "USD 299 Sylvan Grove",
    ]
    first = listing.rows[0]
    assert first.status == "Closed Wednesday"
    assert first.updated_text == "2025-03-18"
    assert first.extra["county_name1"] == "Finney"
    assert first.extra["forced_county_name"] == "KANSAS"
    assert first.extra["expiration"] == "2025-03-19 10:00:00"
    assert first.extra["rec_id"] == "302510"
    assert first.extra["comments_line1"] is None


def test_wbtv_january_2024_export() -> None:
    listing = gray.parse(body("wbtv-export-20240108194907.json"))
    assert [row.name for row in listing.rows] == [
        "Anson County Schools",
        "Cabarrus County Schools",
        "Catawba County Schools",
        "Chesterfield County School District",
        "Valor Preparatory Academy",
        "Clover School District",
        "Fort Mill School District",
        "Lancaster County Schools",
        "York School District 1",
    ]
    assert [row.status for row in listing.rows[:3]] == [
        "Closed Tuesday",
        "Closed Tuesday",
        "Remote Learning Tuesday",
    ]


@pytest.mark.parametrize(
    ("name", "rows"),
    [
        ("kbjr-export-20251229015929.json", 1),
        ("wave-export-20250112214955.json", 12),
        ("wlbt-export-20250120191710.json", 20),
    ],
)
def test_exports_match_their_declared_counts(name: str, rows: int) -> None:
    listing = gray.parse(body(name))
    assert len(listing.rows) == rows
    assert listing.declared_count == rows


def test_empty_export_captured_in_january_2024() -> None:
    listing = gray.parse(body("kctv-export-20240128101402.json"))
    assert (listing.variant, listing.state, listing.declared_count) == (
        "gray-s3-json",
        ListingState.EMPTY,
        0,
    )


def test_wmbf_january_2025_page_lists_one_row_per_school_level() -> None:
    listing = gray.parse(body("wmbf-20250121113248.html"))
    assert listing.declared_count == 13
    assert [row.name for row in listing.rows][:4] == [
        "Darlington County School District",
        "Darlington County School District",
        "Darlington County School District",
        "FSD3",
    ]
    first = listing.rows[0]
    assert first.status == "Early Dismissal at 11:25AM Today"
    assert first.extra["comments"] == '["Elementary Schools"]'
    assert first.extra["county"] == "Darlington"


def test_kalb_january_2025_page_matches_its_total() -> None:
    listing = gray.parse(body("kalb-20250121135528.html"))
    assert len(listing.rows) == listing.declared_count == 32


def test_wbbj_2026_lazy_page_holds_no_list() -> None:
    listing = gray.parse(body("wbbj-20260505153048.html"))
    assert (listing.variant, listing.state, listing.rows) == (
        "gray-fusion-lazy",
        ListingState.DEFERRED,
        (),
    )
