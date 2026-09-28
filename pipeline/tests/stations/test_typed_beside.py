"""Closings typed beside a Nexstar closings article (and a Scripps closings module), and WHNT's
Tribune-era typed page.

Some stations type closings into their closings page next to the closings article
while the article itself stays empty (snowlight.sources.stations.typed.entries_beside).
Only the stations the registry files under ``nexstar-typed`` have such entries read as
their list; for every other Nexstar station a page with entries typed beside its
article is an error, never the article's empty list.

Fixtures are real bodies (fixtures/groups/README.md records each one's URL, capture
time and SHA-256): KIAH's closings page archived on 2025-01-25 and 2026-01-11 (eight
districts typed below the empty article), WIVB's REST page read live on 2026-09-28 (a
school's closing typed above the empty article), KXRM's and KSNF's REST pages read live
the same day and kept whole (a blurb with links and a link to a story beside the empty
article: notes, not entries), and WHNT's page archived on 2018-12-11 (the Tribune-era
template). The expected names were read from the fixtures by eye, and the typed list
items are also read a second way, with a regular expression over the markup. Bodies
built here from real fixtures, with entries added, are named ``synthetic_*``.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path

import httpx
import pytest

from snowlight.sources.stations import (
    fetch,
    group_fixtures,
    nexstar,
    nexstar_typed,
    scripps,
    scripps_typed,
    typed,
)
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.markup import parse_html
from snowlight.sources.stations.model import HealthStatus, ListingState, ReadMode, ShapeError
from snowlight.sources.stations.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "groups"
REGISTRY = load_registry()
KIAH_2025 = "nexstar-typed/kiah-page-20250125183900.html"
KIAH_2026 = "nexstar-typed/kiah-page-20260111124431.html"
WIVB = "nexstar-typed/wivb-wp-20260928092311.json"
KXRM = "nexstar/kxrm-wp-20260928092342.json"
KSNF = "nexstar/ksnf-wp-20260928092347.json"
KOIN = "nexstar/koin-page-20260926224830.json"
WTNH = "nexstar/wtnh-page-20260926224825.json"
WNCT = "nexstar/wnct-page-20250122103636.html"
WHNT_2018 = "nexstar-typed/whnt-page-20181211023820.html"

KIAH_ROWS = [
    ("Cleveland ISD", "2-hour delay on Thursday"),
    ("Crosby ISD", "Closed Thursday"),
    ("Dayton ISD", "Closed Thursday"),
    ("Devers ISD", "Closed Thursday"),
    ("High Island ISD", "Closed Thursday"),
    ("Huffman ISD", "Closed Thursday"),
    ("Hull-Daisetta ISD", "Closed Thursday"),
    ("Liberty ISD", "Closed Thursday"),
]
"""The eight entries below KIAH's empty closings article, read by eye from the capture."""

WHNT_2018_SCHOOLS = [
    "Albertville City Schools",
    "Arab City Schools",
    "Big Cove Christian Academy",
    "Boaz City Schools",
    "Cornerstone Christian Academy",
    "Country Day School",
    "Cullman County Schools",
    "DeKalb County Schools",
    "Fort Payne City Schools",
    "Guntersville City Schools",
    "Grace Lutheran School",
    "Huntsville City Schools",
    "Jackson County Schools",
    "Limestone County Schools",
    "Lincoln Academy",
    "Madison City Schools",
    "Madison County Schools",
    "Marshall County Schools",
    "Morgan County Schools",
    "North East Alabama Community College",
    "Riverside Christian Academy",
    "St. John Paul II High School",
    "Valley Fellowship Christian Academy",
    "Westminster Christian Academy",
]
"""The 24 schools under "Schools:" on WHNT's page of 2018-12-11, read by eye."""


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _items_after_article(markup: str) -> list[str]:
    """A second reading: the text of each non-empty item of the list after the article."""
    after = markup.split("</article>", 1)[1]
    first_list = re.split(r"<ul(?: class=\"wp-block-list\")?>", after, maxsplit=1)[1]
    first_list = first_list.split("</ul>", 1)[0]
    found = (m.group(1) for m in re.finditer(r"<li>(.*?)</li>", first_list, re.DOTALL))
    return [text for text in (" ".join(unescape(t).split()) for t in found) if text]


@pytest.mark.parametrize("name", [KIAH_2025, KIAH_2026])
def test_kiah_storm_page_reads_the_districts_typed_below_its_empty_article(name: str) -> None:
    listing = nexstar_typed.parse(body(name))
    assert (listing.variant, listing.state, listing.typed) == (
        "nexstar-page-typed-beside",
        ListingState.POPULATED,
        True,
    )
    assert [(row.name, row.status) for row in listing.rows] == KIAH_ROWS
    # A second reading of the same markup: each typed item is "<name>: <status>".
    items = _items_after_article(body(name).decode("utf-8"))
    assert items == [f"{name_}: {status}" for name_, status in KIAH_ROWS]
    # The page's time (article:modified_time, 2025-01-22T21:49:30Z) stamps every row: the
    # capture of 2026-01-11 shows the same list, a year old.
    assert listing.list_updated_at == datetime(2025, 1, 22, 21, 49, 30, tzinfo=UTC)
    for row in listing.rows:
        assert row.updated_text == "2025-01-22T21:49:30Z"
        assert (row.extra["split"], row.extra["updated_scope"]) == ("colon", "page")
    captured = datetime(2026, 1, 11, 12, 44, 31, tzinfo=UTC)
    assert fetch.typed_not_current(listing, captured)
    assert not fetch.typed_not_current(listing, datetime(2025, 1, 23, 12, 0, tzinfo=UTC))


@pytest.mark.parametrize("name", [KIAH_2025, KIAH_2026, WIVB])
def test_the_plain_adapter_refuses_a_page_with_entries_typed_beside_its_article(
    name: str,
) -> None:
    with pytest.raises(ShapeError, match="typed beside its closings article"):
        nexstar.parse(body(name))


def test_wivb_live_page_reads_its_typed_item_and_the_note_is_no_entry() -> None:
    listing = nexstar_typed.parse(body(WIVB))
    assert (listing.variant, listing.state) == ("nexstar-wp-typed-beside", ListingState.POPULATED)
    (row,) = listing.rows
    # Split before its verb; "Administrators: To submit a closing, click here." holds a link.
    assert (row.name, row.status, row.extra["split"]) == (
        "Charter School for Applied Technologies, middle school only,",
        "will be closed Friday, Sept. 4",
        "verb",
    )
    assert listing.list_updated_at == datetime(2026, 9, 4, 3, 40, 28, tzinfo=UTC)


def test_kiah_and_wivb_are_filed_as_typing_closings_beside_their_articles() -> None:
    for sid in ("nexstar-typed-kiah", "nexstar-typed-wivb"):
        station = REGISTRY.stations[sid]
        assert REGISTRY.platform_of(station).adapter == "nexstar-typed"
        assert "Typed beside the closings article" in station.evidence
    for sid in ("nexstar-kiah", "nexstar-wivb"):
        assert sid not in REGISTRY.stations
    entries = {e.file: e for e in group_fixtures.load_entries(FIXTURES)}
    assert entries[KIAH_2025].source_id == "nexstar-typed-kiah"
    assert entries[KIAH_2025].mode is ReadMode.ARCHIVE
    assert entries[WIVB].source_id == "nexstar-typed-wivb"


class Ticker:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.mono = 0.0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


def test_the_live_reader_keeps_no_row_of_wivb_weeks_old_typed_item(tmp_path: Path) -> None:
    station = REGISTRY.stations["nexstar-typed-wivb"]
    assert station.data_url == "https://www.wivb.com/wp-json/wp/v2/pages/1344717"
    now = datetime(2026, 9, 28, 9, 23, 11, tzinfo=UTC)

    def serve(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == USER_AGENT
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nDisallow: /wp-admin/\n")
        assert str(request.url) == station.data_url
        return httpx.Response(200, content=body(WIVB))

    ticker = Ticker(now)
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(serve), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )
    result = fetch.read_station(REGISTRY, station, client, now)
    (health,) = result.health
    assert (health.status, health.rows, health.variant) == (
        HealthStatus.EMPTY,
        0,
        "nexstar-wp-typed-beside",
    )
    assert health.reason is not None
    assert "last changed 2026-09-04T03:40:28Z" in health.reason
    assert result.rows == []


@pytest.mark.parametrize("name", [KXRM, KSNF])
def test_notes_beside_an_empty_article_are_not_entries(name: str) -> None:
    # KXRM: "(SOUTHERN COLORADO) — FOX21 News is committed ..." with links to its app;
    # KSNF: "LIST: Additional Northeast Oklahoma closings", wholly a link to a story.
    for adapter in (nexstar.parse, nexstar_typed.parse):
        listing = adapter(body(name))
        assert (listing.variant, listing.state, listing.rows) == (
            "nexstar-wp-closings",
            ListingState.EMPTY,
            (),
        )
    (page,) = [json.loads(body(name))]
    tree = parse_html(page["content"]["rendered"])
    article = tree.css_first("article.closings-page")
    assert article is not None
    article.decompose()
    assert tree.body is not None
    text = tree.body.text()
    assert "SOUTHERN COLORADO" in text or "Additional Northeast Oklahoma closings" in text
    assert typed.entries_beside(tree.body) == ()


def _with_content(name: str, before: str, after: str, inside: str = "") -> bytes:
    """A real REST fixture's page with markup added before and after its closings article
    (and inside it, before its list)."""
    data = json.loads(body(name))
    page = data[0] if isinstance(data, list) else data
    content = page["content"]["rendered"]
    marker = '<div class="closings-list">'
    assert content.count(marker) == 1
    content = content.replace(marker, inside + marker)
    page["content"] = {"rendered": before + content + after}
    return json.dumps(data).encode()


ENTRIES = (
    ('<ul class="wp-block-list"><li>Synthetic ISD: Closed Thursday</li></ul>', "colon"),
    ("<p>Synthetic ISD &#8211; Closed Thursday</p>", "dash"),
    ("<p><strong>Synthetic ISD</strong> Closed Thursday</p>", "bold"),
    ("<table><tr><td>Synthetic ISD</td><td>Closed Thursday</td></tr></table>", "table"),
    ("<p>&#8211; Synthetic ISD: Closed Thursday</p>", "colon"),
    ('<p><a href="https://example.org/">Synthetic ISD</a>: Closed Thursday</p>', "colon"),
    ("<p><strong>Synthetic ISD:</strong><br>Closed Thursday</p>", "name-line"),
)


@pytest.mark.parametrize(("markup", "split"), ENTRIES)
@pytest.mark.parametrize("where", ["before", "after", "inside"])
def test_entries_typed_beside_an_empty_article_are_never_its_empty_list(
    markup: str, split: str, where: str
) -> None:
    # KOIN's live REST page (its article empty) with one entry typed beside the article.
    if where == "before":
        synthetic = _with_content(KOIN, markup, "")
    elif where == "after":
        synthetic = _with_content(KOIN, "", markup)
    else:
        synthetic = _with_content(KOIN, "", "", inside=markup)
    with pytest.raises(ShapeError, match="typed beside its closings article"):
        nexstar.parse(synthetic)
    listing = nexstar_typed.parse(synthetic)
    assert (listing.variant, listing.state) == ("nexstar-wp-typed-beside", ListingState.POPULATED)
    (row,) = listing.rows
    assert (row.name, row.status, row.extra["split"]) == ("Synthetic ISD", "Closed Thursday", split)


NOTES = (
    "<p>Thanks for signing up!</p><p>Watch for us in your inbox.</p><h1>Daily News</h1>",
    '<p><strong>Administrators</strong>: To submit a closing, <a href="/x">click here</a>.</p>',
    '<p><a href="/story"><strong>LIST:</strong> Additional closings</a></p>',
    '<h2><a href="/radar">LIVE radar</a></h2><h2>CHECK YOUR SCHOOL DISTRICT</h2>',
    "<p>If your school would like to notify the public of a closing, please email us.</p>",
    '<div class="nlp-ignore-block"><ul><li><a href="/s">A story: its headline</a></li></ul></div>',
    "<ul><li></li></ul>",
    # A contact's name over a mailto link (WTNH's page archived 2023-02-27).
    "<p><strong>Ken Margolfo</strong><br>Closing System Coordinator<br>203-784-8801<br>"
    '<a href="mailto:x@example.org">x@example.org</a></p>',
)


@pytest.mark.parametrize("markup", NOTES)
def test_notes_widgets_and_empty_items_beside_an_empty_article_leave_it_empty(markup: str) -> None:
    synthetic = _with_content(KOIN, markup, markup)
    for adapter in (nexstar.parse, nexstar_typed.parse):
        listing = adapter(synthetic)
        assert (listing.variant, listing.state) == ("nexstar-wp-closings", ListingState.EMPTY)


def test_an_article_with_rows_and_entries_typed_beside_it_is_an_error() -> None:
    assert nexstar.parse(body(WTNH)).state is ListingState.POPULATED
    synthetic = _with_content(WTNH, "", "<ul><li>Synthetic ISD: Closed Thursday</li></ul>")
    with pytest.raises(ShapeError, match="typed beside"):
        nexstar.parse(synthetic)
    with pytest.raises(ShapeError, match="lists 3 rows and the page 1 entries typed beside it"):
        nexstar_typed.parse(synthetic)


def test_an_html_page_whose_article_holds_typed_entries_outside_its_list_is_an_error() -> None:
    # WNCT's archived page (the older template: the closings article is the page's own).
    markup = body(WNCT).decode("utf-8")
    assert nexstar.parse(body(WNCT)).state is ListingState.POPULATED
    synthetic = markup.replace(
        '<div class="closings-list">',
        '<ul><li>Synthetic ISD: Closed Thursday</li></ul><div class="closings-list">',
        1,
    ).encode()
    with pytest.raises(ShapeError, match="typed beside"):
        nexstar.parse(synthetic)


def test_whnt_2018_tribune_template_reads_every_item_under_its_headings() -> None:
    fixture = body(WHNT_2018)
    with pytest.raises(ShapeError):
        nexstar.parse(fixture)
    listing = nexstar_typed.parse(fixture)
    assert (listing.variant, listing.state, listing.typed) == (
        "nexstar-typed-entry-content",
        ListingState.POPULATED,
        True,
    )
    names = [row.name for row in listing.rows]
    assert names == [*WHNT_2018_SCHOOLS, "Marshall Space Flight Center"]
    # A second reading: every <li> of the block, in order.
    items = [
        " ".join(unescape(m.group(1)).split())
        for m in re.finditer(r"<li>(.*?)</li>", fixture.decode("utf-8"), re.DOTALL)
    ]
    assert len(items) == len(names)
    for row, item in zip(listing.rows, items, strict=True):
        assert item.startswith(row.name), (row.name, item)
    assert {row.extra["section"] for row in listing.rows[:24]} == {"Schools"}
    assert listing.rows[-1].extra["section"] == "Businesses"
    assert listing.rows[-1].status.startswith("has announced the unscheduled/Liberal Leave")
    marshall = listing.rows[names.index("Marshall County Schools")]
    assert (marshall.status, marshall.extra["split"]) == ("Delayed 3 hours Tuesday.", "dash")
    assert listing.list_updated_at == datetime(2018, 12, 11, 2, 35, 3, tzinfo=UTC)


def test_v4_slices_read_as_their_fixtures_and_cut_what_v3_cuts_to_the_same_bytes() -> None:
    entries = group_fixtures.load_entries(FIXTURES)
    v4 = [e for e in entries if e.slice == "nexstar-v4"]
    assert {e.file for e in v4} == {KIAH_2025, KIAH_2026, WHNT_2018, WIVB}
    for entry in v4:
        fixture = body(entry.file)
        assert nexstar.slice_body_v4(fixture) == fixture, entry.file
    for entry in entries:
        if entry.slice in {"nexstar-v1", "nexstar-v2", "nexstar-v3"}:
            fixture = body(entry.file)
            assert nexstar.slice_body_v4(fixture) == nexstar.slice_body_v3(fixture) == fixture
    # The v3 cut of KIAH's page kept only the article, and so read it as empty: v4 keeps the
    # rich-text block around it with the typed entries.
    kept = body(KIAH_2025).decode("utf-8")
    assert kept.count('<div class="article-content rich-text">') == 2  # the block, the article's
    assert len(_items_after_article(kept)) == len(KIAH_ROWS)


# Scripps: list items typed in a rich-text module beside the closings module ----------------

KSHB = "scripps/kshb-page-20260926224811.html"


def _scripps_with(markup: str) -> bytes:
    """KSHB's live page (its closings module empty) with a rich-text module added after it."""
    page = body(KSHB).decode("utf-8")
    return page.replace("</body>", f'<div class="RichTextModule">{markup}</div></body>', 1).encode()


@pytest.mark.parametrize(
    "markup",
    [
        "<ul><li>Synthetic School District: Closed Thursday</li></ul>",
        "<table><tr><td>Synthetic School District</td><td>Closed</td></tr></table>",
    ],
)
def test_a_scripps_page_with_items_typed_beside_its_module_is_an_error(markup: str) -> None:
    assert scripps.parse(body(KSHB)).state is ListingState.EMPTY
    synthetic = _scripps_with(markup)
    with pytest.raises(ShapeError, match="beside its closings module"):
        scripps.parse(synthetic)
    with pytest.raises(ShapeError):
        scripps_typed.parse(synthetic)


@pytest.mark.parametrize(
    "markup",
    [
        # The notes Scripps pages keep beside the module (WCPO's and KMTV's, 2026).
        "<p>Need an ID code and password? Call (513) 852-4966 *</p><p>*Leave a message on our "
        "hotline and provide the requested information.</p>",
        "<p><b>Contact the Newsroom</b><br>To report a closing, send an email.</p>",
        "",
    ],
)
def test_scripps_notes_beside_the_module_leave_it_as_it_is(markup: str) -> None:
    listing = scripps.parse(_scripps_with(markup))
    assert (listing.variant, listing.state) == ("scripps-closings-module", ListingState.EMPTY)
