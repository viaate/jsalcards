"""The Scripps adapter against real live pages (fixtures/groups/scripps/) and error cases.

Fixtures are live responses read on 2026-09-26 with the pipeline's own client (see
fixtures/groups/README.md). The expected names were read from the fixtures with
``grep 'text--primary'``, independently of the adapter. Bodies edited in this file are
named ``synthetic_*``.
"""

import json
from pathlib import Path

import pytest

from snowlight.sources.stations import scripps
from snowlight.sources.stations.model import ListingState, ShapeError

FIXTURES = Path(__file__).parent / "fixtures" / "groups" / "scripps"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_wtkr_module_with_four_closings() -> None:
    listing = scripps.parse(body("wtkr-page-20260926223948.html"))
    assert (listing.variant, listing.state) == ("scripps-closings-module", ListingState.POPULATED)
    assert [row.name for row in listing.rows] == [
        "Poquoson Public Schools",
        "The Williams School",
        "VPCC - Historic Triangle Campus",
        "YWCA of South Hampton Roads",
    ]
    assert [row.status for row in listing.rows] == [
        "Virtual Learning",
        "2 Hour Delay Thursday",
        "Closed Wednesday due to power outage",
        "All Events Canceled",
    ]
    for row in listing.rows:
        # The unlabelled time is the row's expiration (as the page's JSON rendering names
        # it), kept as text, not as an update time.
        assert row.extra == {"expiration": "2026-09-27T03:59:59.999999Z"}
        assert row.updated_text is None


def test_kshb_empty_module_says_so() -> None:
    listing = scripps.parse(body("kshb-page-20260926224811.html"))
    assert (listing.variant, listing.state, listing.rows) == (
        "scripps-closings-module",
        ListingState.EMPTY,
        (),
    )


def test_wtvq_page_is_deferred_to_its_snowatch_file() -> None:
    page = scripps.parse(body("wtvq-page-20260926224813.html"))
    assert (page.variant, page.state) == ("scripps-frame", ListingState.DEFERRED)
    assert page.follows == ("https://www.wtvq.com/content/uploads/weather-images/SnoWatch.html",)
    snowatch = scripps.parse(body("wtvq-snowatch-20260926224349.html"))
    assert (snowatch.variant, snowatch.state) == ("gray-file-grid", ListingState.EMPTY)


def _real() -> str:
    return body("wtkr-page-20260926223948.html").decode()


def test_synthetic_rows_inside_filter_groups_and_extra_paragraphs() -> None:
    synthetic = _real().replace(
        '<div class="js-a-f cls">\n                </div>',
        '<div class="js-a-f cls"><article class="closing js-block">'
        '<p class="text--primary js-sort-value">Accomack Schools</p>'
        '<p class="text--secondary">Closed</p><p class="text--secondary">T</p>'
        '<p class="text--secondary">Note</p></article>'
        '<article class="closing js-block"><p class="text--primary js-sort-value"> </p>'
        '<p class="text--secondary">Closed</p></article></div>',
    )
    listing = scripps.parse(synthetic.encode())
    first = listing.rows[0]
    assert first.name == "Accomack Schools"
    assert first.extra == {"expiration": "T", "text3": "Note", "group": "js-a-f"}
    assert listing.skipped_rows == 1
    assert len(listing.rows) == 5


def test_synthetic_module_errors() -> None:
    no_status = _real().replace("text--secondary", "text--other")
    with pytest.raises(ShapeError, match="name and status"):
        scripps.parse(no_status.encode())
    nameless = _real().replace('js-sort-value">', 'js-sort-value"> ')
    nameless = nameless.replace("Poquoson Public Schools", "").replace("The Williams School", "")
    nameless = nameless.replace("VPCC - Historic Triangle Campus", "")
    nameless = nameless.replace("YWCA of South Hampton Roads", "")
    with pytest.raises(ShapeError, match="missing its name"):
        scripps.parse(nameless.encode())
    empty = body("kshb-page-20260926224811.html").decode()
    reworded = empty.replace("There are currently no active", "No")
    with pytest.raises(ShapeError, match="no empty sentence"):
        scripps.parse(reworded.encode())
    with pytest.raises(ShapeError, match="not a Scripps closings body"):
        scripps.parse(b'<html><body><iframe src="https://www.youtube.com/embed/x"></iframe>')


@pytest.mark.parametrize(
    "name",
    [
        "wtkr-page-20260926223948.html",
        "kshb-page-20260926224811.html",
        "wtvq-page-20260926224813.html",
        "wtvq-snowatch-20260926224349.html",
    ],
)
def test_slicing_is_stable(name: str) -> None:
    original = body(name)
    assert scripps.slice_body(original) == original


def test_slicing_refuses_a_page_in_no_known_shape() -> None:
    with pytest.raises(ShapeError, match="not a Scripps closings body"):
        scripps.slice_body(b"<html><body>Hello</body></html>")


# The JSON rendering (?_renderer=json) and the 2018 Liferay module --------------------------


def _rendering(*modules: object) -> bytes:
    return json.dumps({"main": list(modules)}).encode()


def _closings(results: object) -> dict[str, object]:
    return {
        "_template": "/thirdParty/ThirdPartyModule.hbs",
        "_styledTemplate": scripps.CLOSINGS_TEMPLATE,
        "data": {"resultsArray": results, "singleValues": []},
    }


def test_synthetic_json_renderings() -> None:
    real = json.loads(body("wews-json-20210215134235.json"))
    (module,) = real["closings"]
    rows = module["data"]["resultsArray"]
    # The same module twice reads once; a nameless row is skipped.
    twice = scripps.parse(_rendering(module, module))
    assert [row.name for row in twice.rows] == [row["name"] for row in rows]
    nameless = scripps.parse(_rendering(_closings([*rows, {"name": " ", "status": "Closed"}])))
    assert nameless.skipped_rows == 1
    assert scripps.parse(_rendering(_closings([]))).state is ListingState.EMPTY
    errors = [
        (_rendering({"_template": "/core/promo/Promo.hbs"}), "no closings module"),
        (_rendering(module, _closings(rows[:1])), "differ"),
        (_rendering(_closings({"a": 1})), "resultsArray list"),
        (_rendering(_closings([{"name": "A"}])), "not a closing object"),
        (_rendering(_closings([{"name": 1, "status": "Closed"}])), "not text"),
        (_rendering(_closings([{"name": "", "status": "Closed"}])), "missing its name"),
    ]
    for synthetic, message in errors:
        with pytest.raises(ShapeError, match=message):
            scripps.parse(synthetic)
    with pytest.raises(ShapeError, match="no closings module"):
        scripps.slice_body_v2(_rendering({"_template": "x"}))


def test_synthetic_liferay_module_rows() -> None:
    real = body("wkbw-liferay-20181124154614.html").decode()
    listing = scripps.parse(real.encode())
    (row,) = listing.rows
    assert (row.name, row.status, row.extra) == (
        "Great Valley Town Court",
        "Night Court Cancelled",
        {},
    )
    synthetic = real.replace(
        '<p class="text--secondary">Night Court Cancelled</p>',
        '<p class="text--secondary">Night Court Cancelled</p><p class="text--secondary">Call</p>'
        '<p class="text--secondary">x</p>',
    )
    assert scripps.parse(synthetic.encode()).rows[0].extra == {"comments": "Call", "text3": "x"}
