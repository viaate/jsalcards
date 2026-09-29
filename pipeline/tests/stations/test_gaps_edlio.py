"""Part 4's Edlio adapter (district homepage alerts) on real fixtures, and its registry file.

Every fixture in fixtures/gaps/edlio/ is a real body (see the folder's README and
PROVENANCE.json): Mission CISD's, Hidalgo ISD's and Los Fresnos CISD's homepages
archived around the January 2025 snow, Sublette #9's live homepage with an alert up,
and two live homepages without one.
Bodies named ``SYNTHETIC_*`` are made up here, confined to these tests, and exercise
the edge cases and refusals.
"""

import pytest

from snowlight.sources.stations import edlio, gap_fixtures, notices
from snowlight.sources.stations.model import ListingState, ShapeError
from snowlight.sources.stations.registry import CountyBasis, load_registry

FOLDER = gap_fixtures.DEFAULT_FOLDER


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def test_missions_snow_day_alert_is_a_row() -> None:
    """The alert Mission CISD's homepage carried on 2025-01-21 (run 36383349206)."""
    listing = edlio.parse(_body("edlio/mission-20250121.html"))
    assert listing.variant == edlio.VARIANT
    assert listing.state is ListingState.POPULATED
    [row] = listing.rows
    assert row.name == "Weather Advisory"
    assert row.status == "No School - Jan 21, 2025 Delayed Start - Jan 22, 2025"
    assert row.updated_text is None
    assert row.extra == {
        "article_id": "2020301",
        "expires_text": "2025/01/23 01:00:00",
        "link": "/apps/news/article/2020301",
        "image_alt": None,
    }


def test_hidalgos_delayed_start_alert_is_a_row() -> None:
    """Hidalgo ISD's homepage on the eve of the January 2025 snow (run 36409494144)."""
    [row] = edlio.parse(_body("edlio/hidalgo-20250120.html")).rows
    assert row.name == "Delayed Start at Hidalgo ISD"
    assert row.status.startswith("Click on the link for more information regarding the delayed")
    assert notices.row_qualifies(row.name, row.status, edlio.VARIANT)


def test_los_fresnos_headline_only_alert_does_not_prove() -> None:
    """Los Fresnos CISD's snow-day alert: a headline over a picture, no summary."""
    [row] = edlio.parse(_body("edlio/los-fresnos-20250121.html")).rows
    assert (row.name, row.status) == ("Weather Notice - Monday, January, 20", "")
    assert row.extra["image_alt"] is None  # the alert has words (its headline)
    assert not notices.row_qualifies(row.name, row.status, edlio.VARIANT)


def test_sublette_9s_live_alert_with_a_picture_is_a_row() -> None:
    listing = edlio.parse(_body("edlio/sublette-9-live-20260928.html"))
    [row] = listing.rows
    assert row.name == "School Picture Days"
    assert row.status == "Information About School Picture Days"
    assert row.extra["article_id"] == "2234874"
    assert row.extra["expires_text"] == "2026/10/09 15:00:00"
    assert str(row.extra["link"]).startswith("https://www.sublette9.org/apps/pages/index.jsp")
    assert row.extra["image_alt"] is None  # the alert has words


@pytest.mark.parametrize(
    "name", ["edlio/natrona-live-20260928.html", "edlio/edinburg-live-20260928.html"]
)
def test_a_homepage_without_an_alert_is_an_empty_list(name: str) -> None:
    listing = edlio.parse(_body(name))
    assert listing.variant == edlio.VARIANT
    assert listing.state is ListingState.EMPTY
    assert listing.rows == ()


def test_the_gate_proves_mission_by_its_closing_and_not_sublette_by_picture_day() -> None:
    [closing] = edlio.parse(_body("edlio/mission-20250121.html")).rows
    [pictures] = edlio.parse(_body("edlio/sublette-9-live-20260928.html")).rows
    assert notices.row_qualifies(closing.name, closing.status, edlio.VARIANT)
    assert not notices.row_qualifies(pictures.name, pictures.status, edlio.VARIANT)
    assert "edlio" in notices.GENERAL_CHANNEL_ADAPTERS


SYNTHETIC_IMAGE_ONLY = b"""<html><head><meta name="generator" content="Edlio CMS"></head><body>
<article id="homepage_news_alert_modal" class="mfp-hide cf">
<div id="image-content" class="image-content"><img alt="Closed today, ice"></div>
<div id="article-content" class="article-content">
<header class="cf"><h2 class="title"> </h2></header></div>
</article></body></html>"""

SYNTHETIC_SUMMARY_ONLY = b"""<html><head><meta name="generator" content="Edlio CMS"></head><body>
<article id="homepage_news_alert_modal" class="mfp-hide cf">
<div class="summary cf"><style>.x{color:red}</style><p>Two-hour delay</p></div>
</article></body></html>"""

SYNTHETIC_WORDLESS = b"""<html><head><meta name="generator" content="Edlio CMS"></head><body>
<article id="homepage_news_alert_modal" class="mfp-hide cf"><h2 class="title"></h2></article>
</body></html>"""


def test_an_alert_with_only_a_picture_is_named_by_its_alt_text() -> None:
    [row] = edlio.parse(SYNTHETIC_IMAGE_ONLY).rows
    assert row.name == "Closed today, ice"
    assert row.status == ""
    assert row.extra["image_alt"] == "Closed today, ice"
    assert row.extra["article_id"] is None  # no script names it


def test_an_alert_with_only_a_summary_is_named_by_it() -> None:
    [row] = edlio.parse(SYNTHETIC_SUMMARY_ONLY).rows
    assert (row.name, row.status) == ("Two-hour delay", "")


def test_an_alert_with_no_words_is_skipped() -> None:
    listing = edlio.parse(SYNTHETIC_WORDLESS)
    assert listing.state is ListingState.EMPTY
    assert listing.skipped_rows == 1


def test_other_pages_are_refused() -> None:
    # A real page of another CMS (Corpus Christi ISD's Apptegy homepage) and a made-up one.
    with pytest.raises(ShapeError, match="not an Edlio homepage"):
        edlio.parse(_body("apptegy/corpus-christi-live-20260928.html"))
    with pytest.raises(ShapeError, match="not an Edlio homepage"):
        edlio.parse(b"<html><head><title>SYNTHETIC challenge</title></head></html>")


@pytest.mark.parametrize(
    "name",
    [
        "edlio/mission-20250121.html",
        "edlio/sublette-9-live-20260928.html",
        "edlio/natrona-live-20260928.html",
    ],
)
def test_a_slice_reads_as_its_page_and_slicing_it_again_changes_nothing(name: str) -> None:
    sliced = _body(name)
    assert edlio.slice_body(sliced) == sliced
    assert edlio.parse(edlio.slice_body(sliced)) == edlio.parse(sliced)


def test_every_edlio_station_is_a_district_source() -> None:
    registry = load_registry()
    stations = sorted(
        (s for s in registry.stations.values() if s.platform == "edlio"), key=lambda s: s.id
    )
    # 11 in South Texas, 5 in Wyoming, 3 in California, 1 each in Idaho and Montana
    assert len(stations) == 21
    for station in stations:
        assert 1 <= len(station.leaids) <= 2, station.id
        assert station.page_url in station.archive_urls
        assert station.data_url is None
        assert station.counties is not None
        assert station.counties.basis is CountyBasis.DISTRICT
        for leaid in station.leaids:
            assert leaid in station.counties.source
        assert station.robots
        assert all(check.allowed for check in station.robots)
    by_id = {s.id: s for s in stations}
    assert by_id["edlio-mission-tx"].leaids == ("4831040",)
    assert by_id["edlio-edinburg-tx"].counties is not None
    assert by_id["edlio-edinburg-tx"].counties.fips == ("48215",)
    assert by_id["edlio-natrona-wy"].leaids == ("5604510",)
    # Newcastle's district (Weston #1), which the LEA directory lists with wcsd1.org,
    # not Upton's (Weston #7).
    assert by_id["edlio-weston-1-wy"].leaids == ("5604830",)
    assert by_id["edlio-livingston-mt"].leaids == ("3016880", "3020100")
