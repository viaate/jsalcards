"""The Hearst adapter against real archived pages (fixtures/hearst/) and error cases.

Fixtures are Wayback ``id_`` captures sliced with ``hearst-page-v1``; see
fixtures/README.md for each one's URL and capture time. The expected names below
were read from the fixtures with ``grep 'data-name='`` (and, for the Next.js page,
by counting its ``"name"`` keys), independently of the adapter. Bodies built in
this file from a real fixture and then edited are named ``synthetic_*``.
"""

import gzip
import json
from pathlib import Path

import pytest

from snowlight.sources.stations import hearst
from snowlight.sources.stations.model import ListingState, ShapeError

FIXTURES = Path(__file__).parent / "fixtures" / "hearst"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_kmbc_january_2024_rows_with_day_part_lists() -> None:
    listing = hearst.parse(body("kmbc-20240117203333.html"))
    assert listing.variant == "hearst-rows"
    assert listing.state is ListingState.POPULATED
    assert [row.name for row in listing.rows] == [
        "Bannister Road Baptist Church",
        "Christ United Methodist",
        "Full Gospel Assembly-Independence",
        "Southside First Baptist",
    ]
    first, second = listing.rows[:2]
    assert first.status == "Wednesday Evening: Closed"
    assert first.updated_text is None
    assert first.extra["location"] == "Jackson, kansas city, MO"
    assert second.status == "Thursday Morning: No Services | Thursday Afternoon: No Services"
    assert second.extra["data-count"] == "2"


def test_wgal_january_2025_rows() -> None:
    listing = hearst.parse(body("wgal-20250123204600.html"))
    assert [row.name for row in listing.rows] == [
        "Adams County Technical Institute",
        "Gettysburg Area School District",
        "New City School / Logos Academy",
        "Senior Life York",
        "St. Theresa of New Cumberland",
        "Susquehanna Area Senior Center",
        "Trinity Nursery School - Hanover",
        "Vida Charter School",
        "York City School District",
    ]
    district = listing.rows[1]
    # The page's double space is collapsed; the words are kept as written.
    assert district.status == "Thursday Afternoon: REMOTE Learning Day"
    assert district.extra["location"] == "Adams, Gettysburg, PA"


def test_kmbc_january_2025_rows_carry_update_times() -> None:
    listing = hearst.parse(body("kmbc-20250108112659.html"))
    assert len(listing.rows) == 170
    first = listing.rows[0]
    assert first.name == "Academie Lafayette"
    assert first.status == "Closed"
    assert first.updated_text == "1/7/2025 4:41:31 PM"
    assert first.extra["location"] == "Jackson, Kansas City, MO"
    # Rows posted through the newer form carry "Updated:"; day-part rows on the same
    # page do not.
    assert sum(row.updated_text is not None for row in listing.rows) == 141
    senior = next(row for row in listing.rows if row.name == "Belton Senior Center")
    assert senior.status == "Wednesday Morning: Opening At 10:00 AM"
    assert senior.updated_text is None


def test_kmbc_january_2026_single_row() -> None:
    listing = hearst.parse(body("kmbc-20260122213928.html"))
    assert [(row.name, row.status) for row in listing.rows] == [
        ("St. James Lutheran Church-KCMO", "Sunday Morning: No Sunday Services")
    ]


def test_wcvb_february_2026_next_payload() -> None:
    listing = hearst.parse(body("wcvb-20260223150125.html"))
    assert listing.variant == "hearst-next"
    assert len(listing.rows) == 492
    assert listing.declared_count == 492
    first = listing.rows[0]
    assert first.name == "Abby Kelley Charter"
    assert first.status == "Closed"
    assert first.updated_text == "2/22/2026 6:00:02 PM"
    assert first.extra["type"] == "Public School"
    assert json.loads(str(first.extra["locations"])) == [
        {"city": "Worcester", "county": "Worcester", "state": "MA"}
    ]
    assert json.loads(str(first.extra["closure.dayparts"])) == [
        {"status": "Closed", "time": "Monday Morning"}
    ]


def test_gzip_bodies_are_decoded() -> None:
    raw = body("kmbc-20260122213928.html")
    assert hearst.parse(gzip.compress(raw)) == hearst.parse(raw)


def test_unknown_page_is_a_shape_error() -> None:
    with pytest.raises(ShapeError, match="not a Hearst closings page"):
        hearst.parse(b"<html><body><p>Closings moved</p></body></html>")


def test_container_without_rows_or_notice_is_a_shape_error() -> None:
    synthetic_page = (
        b'<div class="weather-closings-data"><div class="weather-closings-data-noresults hidden">'
        b"x</div></div>"
    )
    with pytest.raises(ShapeError, match="no rows"):
        hearst.parse(synthetic_page)


def test_visible_no_closings_notice_is_empty() -> None:
    synthetic_page = (
        b'<div class="weather-closings-data-noclosings">There are currently no closings.</div>'
        b'<div class="weather-closings-data"></div>'
    )
    listing = hearst.parse(synthetic_page)
    assert listing.state is ListingState.EMPTY
    assert listing.rows == ()


def test_hidden_no_closings_notice_is_not_empty() -> None:
    synthetic_page = (
        b'<div class="weather-closings-data-noclosings hidden">none</div>'
        b'<div class="weather-closings-data"></div>'
    )
    with pytest.raises(ShapeError):
        hearst.parse(synthetic_page)


def test_empty_next_closings_list_is_empty() -> None:
    real = body("wcvb-20260223150125.html").decode("utf-8")
    start = real.index('\\"closings\\":[') + len('\\"closings\\":[')
    end = real.index('],\\"total\\":492')
    synthetic_page = (real[:start] + real[end:]).replace('\\"total\\":492', '\\"total\\":0')
    listing = hearst.parse(synthetic_page.encode("utf-8"))
    assert listing.state is ListingState.EMPTY
    assert listing.declared_count == 0


def test_truncated_next_payload_is_a_shape_error() -> None:
    real = body("wcvb-20260223150125.html")
    synthetic_page = real[: len(real) // 2] + b"</script></body></html>"
    with pytest.raises(ShapeError):
        hearst.parse(synthetic_page)


def test_failed_next_payload_is_a_shape_error() -> None:
    real = body("wcvb-20260223150125.html").decode("utf-8")
    synthetic_page = real.replace('\\"success\\":true', '\\"success\\":false', 1)
    with pytest.raises(ShapeError, match="failure"):
        hearst.parse(synthetic_page.encode("utf-8"))


def test_slice_keeps_what_the_parser_reads() -> None:
    for name in ("kmbc-20240117203333.html", "wcvb-20260223150125.html"):
        fixture = body(name)
        assert hearst.parse(hearst.slice_page(fixture)) == hearst.parse(fixture)


def test_slice_refuses_unknown_pages() -> None:
    with pytest.raises(ShapeError):
        hearst.slice_page(b"<html></html>")


def test_wbal_january_2026_rows_are_still_server_rendered() -> None:
    listing = hearst.parse(body("wbal-20260127211951.html"))
    assert listing.variant == "hearst-rows"
    assert len(listing.rows) == 59
    district = listing.rows[1]
    assert district.name == "Anne Arundel County Schools"
    assert district.status == "Wednesday Morning: Closed | Wednesday Afternoon: Closed"
    assert district.extra["location"] == "Anne Arundel, Annapolis, MD"


@pytest.mark.parametrize(
    ("name", "rows"),
    [
        ("wmur-20240213131436.html", 77),
        ("wisn-20240114054206.html", 37),
        ("wlwt-20250105142047.html", 58),
    ],
)
def test_populated_pages_read_every_row(name: str, rows: int) -> None:
    listing = hearst.parse(body(name))
    assert len(listing.rows) == rows
    assert listing.skipped_rows == 0


def test_html_entities_in_names_are_decoded() -> None:
    names = [row.name for row in hearst.parse(body("wisn-20240114054206.html")).rows]
    assert "Believers in Christ Christian Academy & H.S." in names


@pytest.mark.parametrize("name", ["wvtm-20250115042407.html", "wdsu-20170108053432.html"])
def test_visible_no_closings_notice_pages_are_empty(name: str) -> None:
    listing = hearst.parse(body(name))
    assert (listing.variant, listing.state, listing.rows) == ("hearst-rows", ListingState.EMPTY, ())


def test_several_locations_are_kept_apart() -> None:
    real = body("kmbc-20260122213928.html").decode("utf-8")
    marker = '<div class="weather-closings-data-location">'
    start = real.index(marker) + len(marker)
    end = real.index("</div>", start)
    synthetic_page = real[:start] + "Jackson, Kansas City, MO<br>Clay, Liberty, MO<br>" + real[end:]
    (row,) = hearst.parse(synthetic_page.encode("utf-8")).rows
    assert row.extra["location"] == "Jackson, Kansas City, MO | Clay, Liberty, MO"


def test_kcra_february_2026_next_payload_names() -> None:
    listing = hearst.parse(body("kcra-20260217060801.html"))
    assert listing.variant == "hearst-next"
    assert [row.name for row in listing.rows] == [
        "Camino Union School District",
        "El Dorado Union HS Dist: El Dorado HS",
        "El Dorado Union HS Dist: Independence HS",
        "Gold Oak Union School District",
        "Pacific Crest Academy",
        "Pioneer Union Elementary School District",
        "Pollock Pines Elementary School District",
        "Silver Fork School District",
        "Union Mine High School",
    ]


def test_wyff_february_2026_single_next_row() -> None:
    (row,) = hearst.parse(body("wyff-20260222213604.html")).rows
    assert row.name == "Madison County NC Schools"
    assert row.status == (
        "Tomorrow: E-Learning Day, Closed Optional Teacher Workday/ Remote Learning Day"
    )
    assert row.updated_text == "2/22/2026 3:10:36 PM"


def test_khbs_february_2026_next_payload_is_empty() -> None:
    listing = hearst.parse(body("khbs-20260223025120.html"))
    assert (listing.variant, listing.state, listing.declared_count) == (
        "hearst-next",
        ListingState.EMPTY,
        0,
    )


def test_koat_january_2025_rows() -> None:
    listing = hearst.parse(body("koat-20250123183122.html"))
    assert [(row.name, row.status, row.extra["location"]) for row in listing.rows] == [
        ("Grants-Cibola County Schools", "Friday Morning: 2 Hour Delay", "Cibola, Grants, NM"),
        ("Laguna Department of Education", "Friday Morning: 2 Hour Delay", "Cibola, Laguna, NM"),
        (
            "St. Bonaventure Indian Mission & School",
            "Thursday Afternoon: Closed",
            "McKinley, Thoreau, NM",
        ),
    ]
