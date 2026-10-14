"""Earlier forms of district homepages the Apptegy adapter reads: Elementor and Finalsite.

The fixtures are real captures (provenance in ``fixtures/gate/PROVENANCE.json``):
Alpine School District's WordPress homepage built with Elementor, of 2023-02-27
(Alert widgets, the first announcing the online learning day of the Utah snow day
of 22 February 2023) and of 2024-02-08 (none), and Davis School District's
Finalsite homepage of 2024-02-02 (a deferred page that loads its page pops). Before
round 2 of the coverage gate the Apptegy adapter refused every one of them.
"""

from pathlib import Path

import pytest

from snowlight.sources.stations import apptegy, elementor, notices
from snowlight.sources.stations.model import ListingState, ShapeError

GATE = Path(__file__).parent / "fixtures" / "gate"


def _body(name: str) -> bytes:
    return (GATE / name).read_bytes()


def test_alpines_alert_widgets_are_its_notices() -> None:
    listing = apptegy.parse(_body("elementor/alpine-20230227.html"))
    assert (listing.variant, listing.state) == (elementor.VARIANT, ListingState.POPULATED)
    names = [row.name for row in listing.rows]
    assert names == [
        "ONLINE/DISTANCE LEARNING DAY \u2013 WEDNESDAY, FEBRUARY 22, 2023",
        "Winter Weather",
        "SCHOOLS OPEN ON REGULAR SCHEDULE FRIDAY, FEBRUARY 24, 2023",
        "DRESS WARM FOR THE WEATHER!",
        "SCHOOLS OPEN - FRIDAY, DECEMBER 2, 2022",
    ]
    first = listing.rows[0]
    assert first.status.startswith("Due to extreme weather conditions")
    assert first.extra == {"kind": "info"}
    # The remote day and the weather advisory announce what a closings channel is for.
    assert notices.row_qualifies(first.name, first.status, listing.variant)
    assert notices.row_qualifies(listing.rows[1].name, listing.rows[1].status, listing.variant)


def test_an_elementor_page_with_no_alert_widget_is_an_empty_list() -> None:
    listing = apptegy.parse(_body("elementor/alpine-20240208.html"))
    assert (listing.variant, listing.state, listing.rows) == (
        elementor.VARIANT,
        ListingState.EMPTY,
        (),
    )


def test_a_page_that_is_not_built_with_elementor_is_refused() -> None:
    page = b'<html><head><meta name="generator" content="WordPress 6.1"></head><body></body></html>'
    assert not elementor.holds_alert_widgets(page.decode())
    with pytest.raises(ShapeError):
        elementor.parse_text(page.decode())


def test_the_elementor_slice_reads_as_its_original() -> None:
    body = _body("elementor/alpine-20230227.html")
    assert elementor.slice_body(body) == body
    assert elementor.slice_body(b"<html><body>not elementor</body></html>").startswith(
        b"<!DOCTYPE html>"
    )


def test_a_widget_with_only_a_description_is_named_by_it() -> None:
    page = (
        '<html><head><meta name="generator" content="Elementor 3.11.0"></head>'
        '<body class="home elementor-page elementor-page-1">'
        '<div class="elementor-alert elementor-alert-warning" role="alert">'
        '<span class="elementor-alert-description">Schools closed today</span></div>'
        '<div class="elementor-alert" role="alert"></div>'
        "</body></html>"
    )
    listing = elementor.parse_text(page)
    assert [(row.name, row.status, row.extra) for row in listing.rows] == [
        ("Schools closed today", "", {"kind": "warning"})
    ]
    assert listing.skipped_rows == 1


def test_davis_finalsite_homepage_is_a_deferred_page() -> None:
    listing = apptegy.parse(_body("finalsite/davis-20240202.html"))
    assert (listing.variant, listing.state) == ("finalsite-homepage", ListingState.DEFERRED)
    assert listing.follows == ("/fs/pages/2/page-pops",)
