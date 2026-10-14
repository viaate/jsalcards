"""KENS' closings page of 2022-2023, which linked to an article, and the articles it linked to.

Every fixture named here is a real archived body (fixtures/gate/lists/, provenance in
that folder's PROVENANCE.json, cut with ``tegna-v3``): KENS' ``/closings`` of
2023-01-28, whose only content is a raw-HTML module linking to its closings article;
that article on 2022-02-02 (six closures for Thursday, February 3) and on 2022-02-23
(every entry "No current report."); and the article the page linked to in January 2022
(closures for January 20). The small documents built in the last tests are synthetic
and say so.
"""

from datetime import UTC, datetime

import pytest

from snowlight.sources.stations import gate_fixtures, group_fixtures, tegna
from snowlight.sources.stations.fixtures import FixtureEntry
from snowlight.sources.stations.markup import minimal_document
from snowlight.sources.stations.model import ListingState, ShapeError
from snowlight.sources.stations.registry import load_registry

FOLDER = gate_fixtures.DEFAULT_FOLDER / "lists"
ARTICLE = (
    "https://www.kens5.com/article/weather/closings/"
    "san-antonio-south-texas-school-closings-delays-openings-list-updates/"
    "273-6b164c07-c1ad-44ac-b1a9-9fcb273e0ca0"
)
WINTER_ARTICLE = (
    "https://www.kens5.com/article/news/education/school-district-closures-due-to-winter-weather/"
    "273-dc6b21f3-f42c-4e23-b704-785205cf7143"
)


def _read(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def test_the_closings_page_that_links_to_its_list_defers_to_the_article() -> None:
    listing = tegna.parse(_read("kens-20230128.html"))
    assert listing.variant == "tegna-closings-link"
    assert listing.state is ListingState.DEFERRED
    assert listing.rows == ()
    assert listing.follows == (ARTICLE,)


def test_the_article_on_the_eve_of_the_february_2022_freeze_lists_its_closures() -> None:
    listing = tegna.parse(_read("kens-article-20220202.html"))
    assert listing.variant == "tegna-closings-article"
    assert listing.state is ListingState.POPULATED
    assert listing.typed
    assert [row.name for row in listing.rows] == [
        "Blanco ISD",
        "Boerne ISD",
        "Kerrville ISD",
        "Luling ISD",
        "San Marcos CISD",
        "Texas A&M-San Antonio",
    ]
    kerrville = listing.rows[2]
    assert kerrville.status == "Kerrville ISD will be closed on Thursday, Feb. 3."
    assert kerrville.extra["heading"] == "SCHOOL CLOSINGS FOR THURSDAY, FEBRUARY 3, 2022"
    assert kerrville.updated_text == "2:03 PM CST February 2, 2022"
    assert listing.list_updated_at == datetime(2022, 2, 2, 20, 3, tzinfo=UTC)
    # The entries that said "No report." (Alamo Heights ISD, Bandera ISD, ...) are not rows.
    assert all(row.status != "No report." for row in listing.rows)


def test_the_article_whose_entries_all_say_no_current_report_is_empty() -> None:
    listing = tegna.parse(_read("kens-article-20220223.html"))
    assert listing.variant == "tegna-closings-article"
    assert listing.state is ListingState.EMPTY
    assert listing.rows == ()
    assert listing.list_updated_at == datetime(2022, 2, 23, 16, 55, tzinfo=UTC)


def test_the_january_2022_article_lists_the_districts_statements() -> None:
    listing = tegna.parse(_read("kens-winter-article-20220120.html"))
    assert listing.state is ListingState.POPULATED
    assert len(listing.rows) == 23
    names = [row.name for row in listing.rows]
    assert names[:5] == [
        "Brooks Academy",
        "San Antonio ISD",
        "Northside ISD",
        "North East ISD",
        "Southside ISD",
    ]
    northside = listing.rows[2]
    assert northside.status.startswith('"Northside ISD will close all schools and offices Thursday')
    # The line after the statement is kept with the row, not read as another row.
    assert northside.extra["more"] == "See the full Twitter post here."
    assert listing.list_updated_at == datetime(2022, 1, 20, 3, 27, tzinfo=UTC)


def test_kens_names_both_articles_as_former_addresses_of_its_list() -> None:
    station = load_registry().stations["tegna-kens"]
    former = [item.url for item in station.former_urls]
    assert former == [ARTICLE, WINTER_ARTICLE]
    assert all(url in station.archive_urls for url in former)


@pytest.mark.parametrize(
    "entry",
    [
        entry
        for entry in group_fixtures.load_entries(group_fixtures.DEFAULT_FOLDER)
        if entry.slice.startswith("tegna-")
    ],
    ids=lambda entry: entry.file,
)
def test_tegna_v3_leaves_every_earlier_slice_as_it_was(entry: FixtureEntry) -> None:
    body = (group_fixtures.DEFAULT_FOLDER / entry.file).read_bytes()
    assert tegna.slice_body_v3(body) == tegna.slice_body_v2(body)


def _article(title: str, sections: list[str]) -> bytes:
    """A synthetic article in the template of KENS' (not a real page)."""
    cells = "".join(
        f'<div class="article__section article__section_type_text utility__text">{html}</div>'
        for html in sections
    )
    return minimal_document(
        [
            f"<title>{title}</title>",
            '<div class="article__updated"><span class="article__meta-label">Updated:'
            "</span> 6:05 AM CDT October 4, 2026</div>",
            f'<div class="article__body">{cells}</div>',
        ]
    )


def test_a_heading_before_another_heading_heads_the_rows_after_it() -> None:
    body = _article(
        "Synthetic school closings",
        [
            "<h3>STATUS FOR MONDAY</h3>",
            "<h3>Example ISD</h3>",
            "<p>Closed Monday.</p>",
            '<p><a href="https://example.org/">District website</a> | '
            '<a href="https://example.org/f">Facebook</a></p>',
            "<h3>Other ISD</h3>",
            "<p>No report.</p>",
        ],
    )
    listing = tegna.parse(body)
    assert [(row.name, row.status) for row in listing.rows] == [("Example ISD", "Closed Monday.")]
    assert listing.rows[0].extra == {"heading": "STATUS FOR MONDAY"}
    assert listing.list_updated_at == datetime(2026, 10, 4, 11, 5, tzinfo=UTC)
    assert tegna.parse(tegna.slice_body_v3(body)) == listing


def test_an_article_with_no_entry_or_about_something_else_is_refused() -> None:
    with pytest.raises(ShapeError, match="no entry"):
        tegna.parse(_article("Synthetic school closings", ["<p>Nothing typed here yet.</p>"]))
    with pytest.raises(ShapeError, match="title"):
        tegna.parse(_article("Synthetic weather story", ["<h3>A</h3>", "<p>B</p>"]))


def test_a_raw_html_link_that_does_not_lead_to_the_list_is_not_one() -> None:
    body = minimal_document(
        ['<div class="raw-html"><p><a href="/weather">See the forecast.</a></p></div>']
    )
    with pytest.raises(ShapeError):
        tegna.parse(body)
