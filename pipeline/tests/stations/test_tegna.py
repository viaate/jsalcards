"""The TEGNA adapter against real live pages (fixtures/groups/tegna/) and error cases.

Fixtures are live responses read on 2026-09-26 with the pipeline's own client (see
fixtures/groups/README.md). The expected names were read from the fixtures with
``grep 'closings__title'``, independently of the adapter. Bodies edited in this file
are named ``synthetic_*``.
"""

from pathlib import Path

import pytest

from snowlight.sources.stations import tegna
from snowlight.sources.stations.model import ListingState, ShapeError

FIXTURES = Path(__file__).parent / "fixtures" / "groups" / "tegna"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_fox61_module_with_one_closing_and_its_count() -> None:
    listing = tegna.parse(body("wtic-page-20260926223946.html"))
    assert (listing.variant, listing.state) == ("tegna-closings-module", ListingState.POPULATED)
    (row,) = listing.rows
    assert (row.name, row.status, row.updated_text) == (
        "MDC All Recreational Facilities",
        "Closed Sat",
        None,
    )
    assert row.extra == {}
    assert listing.declared_count == 1


def test_wusa_empty_module_says_so_and_counts_zero() -> None:
    listing = tegna.parse(body("wusa-page-20260926224806.html"))
    assert (listing.state, listing.rows, listing.declared_count) == (ListingState.EMPTY, (), 0)


def test_kgw_page_is_deferred_to_its_flashalert_file() -> None:
    page = tegna.parse(body("kgw-page-20260926224809.html"))
    assert (page.variant, page.state) == ("tegna-frame", ListingState.DEFERRED)
    assert page.follows == ("https://content.kgw.com/station/flashalert/allclosures.html",)
    report = tegna.parse(body("kgw-flashalert-20260926224347.html"))
    assert (report.variant, report.state) == ("gray-file-flashalert", ListingState.EMPTY)


def _real() -> str:
    return body("wtic-page-20260926223946.html").decode()


def test_synthetic_module_with_more_fields_and_nameless_items() -> None:
    synthetic = _real().replace(
        '<span class="closings__body">Closed Sat</span>',
        '<span class="closings__body">Closed Sat</span><span class="closings__time">6:00 AM</span>',
    )
    synthetic = synthetic.replace(
        "</ul>",
        '<li class="closings__item"><span class="closings__title"> </span>'
        '<span class="closings__body">Closed</span></li></ul>',
    )
    listing = tegna.parse(synthetic.encode())
    (row,) = listing.rows
    assert row.extra == {"time": "6:00 AM"}
    assert listing.skipped_rows == 1


def test_synthetic_module_errors() -> None:
    no_status = _real().replace("closings__body", "closings__other")
    with pytest.raises(ShapeError, match="no closings__body"):
        tegna.parse(no_status.encode())
    nameless = _real().replace("closings__title", "closings__heading")
    with pytest.raises(ShapeError, match="missing its name"):
        tegna.parse(nameless.encode())
    both = _real().replace("</ul>", '</ul><p class="closings__error">No delays or closings.</p>')
    with pytest.raises(ShapeError, match="says there are none"):
        tegna.parse(both.encode())
    empty = body("wusa-page-20260926224806.html").decode()
    reworded = empty.replace("No delays or closings.", "Nothing today.")
    with pytest.raises(ShapeError, match="no no-closings sentence"):
        tegna.parse(reworded.encode())
    with pytest.raises(ShapeError, match="not a TEGNA closings body"):
        tegna.parse(b"<html><body><div class='raw-html'></div></body></html>")


def test_synthetic_page_without_the_all_alerts_count() -> None:
    synthetic = _real().replace("Closures/Delays (1)", "Closings")
    assert tegna.parse(synthetic.encode()).declared_count is None


@pytest.mark.parametrize(
    "name",
    [
        "wtic-page-20260926223946.html",
        "wusa-page-20260926224806.html",
        "kgw-page-20260926224809.html",
        "kgw-flashalert-20260926224347.html",
    ],
)
def test_slicing_is_stable(name: str) -> None:
    original = body(name)
    assert tegna.slice_body(original) == original


def test_slicing_refuses_a_page_in_no_known_shape() -> None:
    with pytest.raises(ShapeError, match="not a TEGNA closings body"):
        tegna.slice_body(b"<html><body>Hello</body></html>")


# The 2018-2020 grid template (archived) ------------------------------------------------------


def _grid() -> str:
    return body("wusa-grid-20181115063939.html").decode()


def test_synthetic_grid_shapes_that_are_errors() -> None:
    grid = _grid()
    twice = grid.replace(
        '<div class="closings">', '<div class="closings"></div><div class="closings">'
    )
    with pytest.raises(ShapeError, match="holds 2 closings modules"):
        tegna.parse(twice.encode())
    stray = grid.replace(
        '<ul class="closings__list closings__list-left">', '<ul class="other-list">', 1
    )
    with pytest.raises(ShapeError, match="outside a closings list"):
        tegna.parse(stray.encode())
    with pytest.raises(ShapeError, match="no closings grid module"):
        tegna.parse_grid("<html></html>")
    with pytest.raises(ShapeError, match="no closings module"):
        tegna.parse_module("<html></html>")


def test_grid_heading_changes_follow_the_page_order() -> None:
    synthetic = _grid().replace(
        '<ul class="closings__list closings__list-right">',
        '<div class="closings__heading">LATER</div>'
        '<ul class="closings__list closings__list-right">',
    )
    listing = tegna.parse(synthetic.encode())
    headings = [row.extra["heading"] for row in listing.rows]
    assert headings[0] == "DELAYS/CLOSINGS"
    assert headings[-1] == "LATER"


def test_v2_slice_keeps_an_archived_count_item_with_tracking_attributes() -> None:
    page = body("wusa-page-20210131223248.html")
    assert b"data-tracking-action" in page
    assert tegna.parse(page).declared_count == 33
    assert tegna.slice_body_v2(page) == page
    # tegna-v1 still cuts a frame page and refuses a body in no known shape.
    frame = body("kgw-page-20260926224809.html")
    assert tegna.slice_body_v2(frame) == frame
    with pytest.raises(ShapeError, match="not a TEGNA closings body"):
        tegna.slice_body_v2(b"<html><body>Hello</body></html>")
