"""The county offices' lists (part 3b): Santa Cruz's closures sheet and Humboldt's alerts.

The fixtures are real live and archived bodies (fixtures/regional/santacruzcoe and
hcoe, with their provenance in PROVENANCE.json). Santa Cruz's sheet has not been
seen with a row, so the row-reading tests put SYNTHETIC rows into the real sheet's
table (built from the real header row, and named synthetic here); they, and the
edits of Humboldt's real page, are confined to this file.
"""

from pathlib import Path

import pytest

from snowlight.sources.stations import hcoe, regional_fixtures, santacruzcoe
from snowlight.sources.stations.model import ListingState, ShapeError
from snowlight.sources.stations.registry import load_registry

FOLDER = regional_fixtures.DEFAULT_FOLDER
SHEET_KEY = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRTTn-nz1kHVAdHbBrAQSgMaLB0FbiNrO7cWaFDIxZxvGzGXnHnF2jv5LiRcui_Tz0JTpGAt2DidUYo"
)


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def test_santa_cruz_page_widget_and_sheet_chain() -> None:
    page = santacruzcoe.parse(_body("santacruzcoe/page-live-20260927.html"))
    assert page.variant == santacruzcoe.PAGE
    assert page.state is ListingState.DEFERRED
    widget_url = f"{SHEET_KEY}/pubhtml?gid=1755311565&single=true&widget=true&headers=false"
    assert page.follows == (widget_url,)
    widget = santacruzcoe.parse(_body("santacruzcoe/widget-live-20260927.html"))
    assert widget.variant == santacruzcoe.WIDGET
    assert widget.follows == (f"{SHEET_KEY}/pubhtml/sheet?headers=false&gid=1755311565",)
    sheet = santacruzcoe.parse(_body("santacruzcoe/sheet-live-20260927.html"))
    assert (sheet.variant, sheet.state, sheet.rows) == (
        santacruzcoe.SHEET,
        ListingState.EMPTY,
        (),
    )


def test_registry_reads_the_tab_page_the_widget_names() -> None:
    station = load_registry().stations["santacruzcoe-closures"]
    widget = santacruzcoe.parse(_body("santacruzcoe/widget-live-20260927.html"))
    assert station.data_url == widget.follows[0]
    assert station.leaids
    assert station.counties is not None
    assert station.counties.basis.value == "district"


def _synthetic_sheet(cells: list[list[str]]) -> bytes:
    """SYNTHETIC: the real sheet's header row, with the given rows under it."""
    rows = "".join(
        "<tr><th><div>n</div></th>"
        + "".join(f"<td>{cell}</td>" for cell in row[:4])
        + f'<td colspan="2">{row[4]}</td></tr>'
        for row in cells
    )
    header = (
        "<tr><th><div>1</div></th><td>CLOSURE DATE</td><td>DISTRICT</td>"
        '<td>SCHOOLS CLOSED</td><td>REASON</td><td colspan="2">CONTACT</td></tr>'
    )
    table = f'<table class="waffle"><tbody>{header}{rows}</tbody></table>'
    return f"<html><body>{table}</body></html>".encode()


def test_santa_cruz_sheet_rows_are_read_by_their_headings() -> None:
    body = _synthetic_sheet(
        [
            [
                "SYNTHETIC 1/1/2099",
                "SYNTHETIC USD",
                "SYNTHETIC ELEMENTARY",
                "SYNTHETIC REASON",
                "x",
            ],
            ["", "", "", "", ""],
            ["SYNTHETIC 1/2/2099", "SYNTHETIC USD", "", "no school named", ""],
        ]
    )
    listing = santacruzcoe.parse(body)
    assert listing.state is ListingState.POPULATED
    assert listing.skipped_rows == 1
    (only,) = listing.rows
    assert (only.name, only.status, only.updated_text) == (
        "SYNTHETIC ELEMENTARY",
        "SCHOOLS CLOSED",
        None,
    )
    assert only.extra == {
        "status_from": "column heading",
        "closure_date": "SYNTHETIC 1/1/2099",
        "district": "SYNTHETIC USD",
        "reason": "SYNTHETIC REASON",
        "contact": "x",
    }
    assert santacruzcoe.parse(santacruzcoe.slice_body(body)) == listing


def test_santa_cruz_sheet_with_other_columns_is_refused() -> None:
    body = _body("santacruzcoe/sheet-live-20260927.html").replace(b"REASON", b"STATUS")
    with pytest.raises(ShapeError, match="header row"):
        santacruzcoe.parse(body)
    with pytest.raises(ShapeError):
        santacruzcoe.parse(b"<html><body><p>School closures</p></body></html>")


def _page_rows(name: str) -> list[tuple[str, str | None]]:
    page = hcoe.parse(_body(name))
    assert (page.variant, page.state) == (hcoe.POSTS, ListingState.POPULATED)
    return [(row.name, row.updated_text) for row in page.rows]


def test_humboldt_page_lists_its_posts() -> None:
    assert _page_rows("hcoe/alerts-page-live-20260927.html") == [
        ("Klamath-Trinity Schools Closed Wednesday, March 11", "Mar 11, 2026"),
        ("UPDATE: Reopening Thursday | Maple Creek School Closed Jan. 20-21", "Jan 20, 2026"),
        ("Trinidad School Closed Monday Due to Water Issue", "Jan 5, 2026"),
        ("Local Schools\u2019 2026-2027 Enrollment Has Begun", "Dec 1, 2025"),
        (
            "Superintendent\u2019s Statement on Department of Education Executive Order",
            "Mar 20, 2025",
        ),
        ("Law Enforcement Statements Regarding Phone Threats to Schools", "Mar 19, 2025"),
        (
            "School Status List after December 5, 2024 Earthquake and Tsunami Warning",
            "Dec 5, 2024",
        ),
        ("Local Schools\u2019 2025-2026 Enrollment Has Begun", "Dec 4, 2024"),
        ("School Status List after November 20, 2024 Severe Weather", "Nov 19, 2024"),
        ("School Closures \u2013 March 4, 2024", "Mar 4, 2024"),
    ]
    first = hcoe.parse(_body("hcoe/alerts-page-live-20260927.html")).rows[0]
    assert first.status == (
        "All schools in the Klamath-Trinity Joint Unified School District are closed today, "
        "Wednesday, March 11, 2026."
    )
    assert first.extra == {
        "link": "https://hcoe.org/2026/03/klamath-trinity-schools-closed-wednesday-march-11/",
        "post_id": "post-42397",
        "categories": "Alerts",
        "updated_scope": "row",
    }


def test_humboldt_archived_pages_hold_weather_closure_posts() -> None:
    assert _page_rows("hcoe/alerts-page-20230330.html")[:6] == [
        ("March 8, 2023 \u2013 Weather Related Closures", "Mar 8, 2023"),
        (
            "March 8, 2023 \u2013 Southern Humboldt Unified School District \u2013 Delay in "
            "School Start Time",
            "Mar 7, 2023",
        ),
        ("March 7, 2023 \u2013 Weather Related Closures", "Mar 7, 2023"),
        ("March 6, 2023 \u2013 Weather Related Closures", "Mar 6, 2023"),
        ("March 1, 2023 \u2013 Weather Related Closures", "Mar 1, 2023"),
        ("February 28, 2023 \u2013 Weather Related Closures", "Feb 27, 2023"),
    ]
    march_8 = hcoe.parse(_body("hcoe/alerts-page-20230330.html")).rows[0]
    assert march_8.status == (
        "The following schools/districts are closed for weather related reasons on "
        "Wednesday, March 8,..."
    )
    assert _page_rows("hcoe/alerts-page-20260217.html")[-1] == (
        "Green Point School Closed \u2013 January 17, 2024",
        "Jan 17, 2024",
    )
    assert _page_rows("hcoe/alerts-page-20190918.html") == [
        ("5/16/2019 \u2013 Bridgeville School Will Be Closed Thursday and Friday", "May 15, 2019"),
        ("5/14/2019 \u2013 Cuddeback School Closed Today", "May 14, 2019"),
        ("5/3/2019 \u2013 McKinleyville High School Closed Today", "May 3, 2019"),
        ("4/15/2019 \u2013 Peninsula School Closed Today", "Apr 15, 2019"),
        ("2/28/2019 \u2013 Loleta School Closed", "Feb 28, 2019"),
    ]


def test_humboldt_page_without_its_post_list() -> None:
    # SYNTHETIC edits of the real live page, confined to this test.
    page = _body("hcoe/alerts-page-live-20260927.html")
    head, _, rest = page.partition(b"<article")
    tail = rest.rsplit(b"</article>", 1)[1]
    with pytest.raises(ShapeError, match="holds no post"):
        hcoe.parse(head + tail)
    feed_link = (
        b'<link rel="alternate" type="application/rss+xml" title="Humboldt County Office of '
        b'Education &raquo; Alerts Category Feed" href="https://hcoe.org/news/alerts/feed/" />'
    )
    deferred = hcoe.parse(b"<html><head>" + feed_link + b"</head><body></body></html>")
    assert (deferred.variant, deferred.state, deferred.follows) == (
        hcoe.PAGE,
        ListingState.DEFERRED,
        ("https://hcoe.org/news/alerts/feed/",),
    )
    station = load_registry().stations["hcoe-alerts"]
    assert station.data_url == deferred.follows[0]
    untitled = page.replace(b'<h2 class="post-title entry-title">', b"<h3>", 1)
    with pytest.raises(ShapeError, match="no title or no excerpt"):
        hcoe.parse(untitled)


def test_humboldt_feed_rows() -> None:
    feed = hcoe.parse(_body("hcoe/alerts-feed-live-20260927.xml"))
    assert feed.variant == hcoe.FEED
    assert feed.state is ListingState.POPULATED
    assert [row.name for row in feed.rows] == [
        "Klamath-Trinity Schools Closed Wednesday, March 11",
        "UPDATE: Reopening Thursday | Maple Creek School Closed Jan. 20-21",
        "Trinidad School Closed Monday Due to Water Issue",
        "Local Schools\u2019 2026-2027 Enrollment Has Begun",
        "Superintendent\u2019s Statement on Department of Education Executive Order",
    ]
    first = feed.rows[0]
    assert first.status == (
        "All schools in the Klamath-Trinity Joint Unified School District are closed today, "
        "Wednesday, March 11, 2026. For more information, visit the district website or call "
        "the district office at (530) 625-5600."
    )
    assert first.updated_text == "Wed, 11 Mar 2026 14:27:10 +0000"
    assert first.extra == {
        "link": "https://hcoe.org/2026/03/klamath-trinity-schools-closed-wednesday-march-11/"
        "?utm_source=rss&utm_medium=rss&utm_campaign=klamath-trinity-schools-closed-wednesday-march-11",
        "guid": "https://hcoe.org/?p=42397",
        "categories": "Alerts",
        "excerpt": "All schools in the Klamath-Trinity Joint Unified School District are closed "
        "today, Wednesday, March 11, 2026.",
        "updated_scope": "row",
    }
    trinidad = feed.rows[2]
    assert trinidad.status.startswith("UPDATE Tuesday, Jan. 6: Trinidad School is OPEN today.")


def test_humboldt_feed_without_items_is_empty_and_other_feeds_are_refused() -> None:
    feed = _body("hcoe/alerts-feed-live-20260927.xml")
    head, _, rest = feed.partition(b"<item>")
    tail = rest.rsplit(b"</item>", 1)[1]
    empty = hcoe.parse(head + tail)
    assert (empty.state, empty.rows) == (ListingState.EMPTY, ())
    other = feed.replace(b"<title>Alerts | Humboldt", b"<title>News | Humboldt", 1)
    with pytest.raises(ShapeError, match="not the Humboldt COE alerts feed"):
        hcoe.parse(other)
    with pytest.raises(ShapeError):
        hcoe.parse(b"<?xml version='1.0'?><rss><channel>")
    with pytest.raises(ShapeError):
        hcoe.parse(b"<html><head></head><body>Alerts</body></html>")


def test_fixture_folders_exist() -> None:
    assert Path(FOLDER / "santacruzcoe").is_dir()
    assert Path(FOLDER / "hcoe").is_dir()
