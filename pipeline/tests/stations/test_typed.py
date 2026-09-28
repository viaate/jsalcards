"""Closings typed by hand into station pages (snowlight.sources.stations.typed), read only
for the stations the registry files under a typed platform (nexstar-typed, scripps-typed),
and the live reader's rule for their age.

Fixtures are real bodies (fixtures/groups/README.md records each one's URL, capture time
and SHA-256): WHNT's, WDHN's and WRBL's typed closings pages archived on storm days and
read live through the WordPress REST API, and KSTU's Brightspot page archived and read
live. The expected names were read from the fixtures by eye (each list item's, table
row's or paragraph entry's organization), and every list-typed page is also checked
against its own top-level list items, read here a second way. Bodies built in this file
are named ``synthetic_*``.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path

import httpx
import pytest
from selectolax.parser import HTMLParser

from snowlight.sources.stations import fetch, nexstar, nexstar_typed, scripps, scripps_typed, typed
from snowlight.sources.stations.adapters import ADAPTERS
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import (
    HealthStatus,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)
from snowlight.sources.stations.registry import StationStatus, load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "groups"
REGISTRY = load_registry()


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def top_level_items(markup: bytes) -> list[str]:
    """The text of every list item not inside another item (a second reading, with no rules)."""
    tree = HTMLParser(markup.decode("utf-8"))
    found = []
    for item in tree.css("li"):
        parent, nested = item.parent, False
        while parent is not None:
            nested = nested or parent.tag == "li"
            parent = parent.parent
        text = " ".join((item.text(separator=" ") or "").split())
        if not nested and text:
            found.append(text)
    return found


def assert_rows_are_the_items(listing: Listing, markup: bytes) -> None:
    """Every top-level item is one row, in order, whose name opens the item's text."""
    items = [text for text in top_level_items(markup) if not text.endswith(":")]
    assert len(listing.rows) == len(items)
    for row, text in zip(listing.rows, items, strict=True):
        assert text.lstrip(" \u2013-").startswith(row.name.rstrip("\u2026")), (row.name, text)


WHNT_2021 = [
    "Athens-Limestone Hospital",
    "Colbert County Health Department",
    "Crestwood Vaccine Clinic",
    "Cullman County Health Department",
    "Franklin County Health Department (Alabama)",
    "Huntsville Hospital\N{RIGHT SINGLE QUOTATION MARK}s Community Vaccination Clinic in John Hunt "
    "Park",
    "Jackson County Health Department",
    "Lauderdale County Health Department",
    "Lawrence County Health Department",
    "Limestone County Health Department",
    "Madison County Health Department",
    "Marshall County Health Department",
    "Morgan County Health Department",
    "Valley Internal Medicine Athens",
    "Athens State University",
    "Calhoun Community College",
    "Cullman County Schools",
    "Heritage Christian University",
    "Kilby School",
    "Northeast Alabama Community College",
    "Northwest-Shoals Community College",
    "Scottsboro City Schools",
    "Snead State Community College",
    "The University of Alabama in Huntsville",
    "The University of North Alabama",
    "Wallace State Community College",
    "American Book Wholesale",
    "Downtown Express YMCA in Huntsville",
    "Greater Ardmore Chamber of Commerce Office",
    "Heart of the Valley YMCA Association Office",
    "Hogan Family YMCA in Madison",
    "Johnson Controls CPVC",
    "Southeast Family YMCA in Huntsville",
    "Sunshine Mills All Plants",
    "U.S Space and Rocket Center",
    "Wayne Farms LLC Decatur Fresh",
    "YMCA Downtown Early Childhood Education Center",
    "YMCA Northwest Early Childhood Education Center",
    "YMCA Southeast Early Childhood Education Center",
]


def test_whnt_storm_day_page_reads_every_list_item_under_its_heading() -> None:
    fixture = body("nexstar-typed/whnt-page-20210215043159.html")
    listing = nexstar_typed.parse(fixture)
    assert (listing.variant, listing.state, listing.typed) == (
        "nexstar-typed-page",
        ListingState.POPULATED,
        True,
    )
    # All 39 list items, whatever they say: "Crestwood Vaccine Clinic" has no status typed.
    assert [row.name for row in listing.rows] == WHNT_2021
    assert_rows_are_the_items(listing, fixture)
    crestwood = listing.rows[2]
    assert (crestwood.status, crestwood.extra["split"]) == ("", "none")
    assert listing.list_updated_at == datetime(2021, 2, 15, 3, 13, 33, tzinfo=UTC)
    first = listing.rows[0]
    assert first.status == "Closed Monday, Tuesday"
    assert first.updated_text == "2021-02-15T03:13:33Z"
    assert first.extra["split"] == "dash"
    assert first.extra["section"] == "COVID-19 Vaccine Clinic Closings and Delays"
    assert first.extra["updated_scope"] == "page"
    note = first.extra["note"]
    assert isinstance(note, str)
    assert note.startswith("The following information is pertaining to Monday, February 15, 2021")
    cullman = listing.rows[WHNT_2021.index("Cullman County Schools")]
    assert cullman.status == "Virtual Learning Day/ Campuses Closed Monday"
    assert cullman.extra["section"] == "School Closings and Delays"
    wayne = listing.rows[-4]
    assert wayne.status == "No 3rd Shift Sunday night, No 1st and 2nd Shift Monday"


def test_bold_names_and_their_sentences_split_at_the_bold_text() -> None:
    fixture = body("nexstar-typed/whnt-page-20250108205534.html")
    listing = nexstar_typed.parse(fixture)
    assert [row.name for row in listing.rows] == [
        "Cullman County Schools",
        "Fort Payne City Schools",
        "DeKalb County Schools",
        "Redstone Arsenal",
        "Huntsville College Preparatory School",
    ]
    assert_rows_are_the_items(listing, fixture)
    assert listing.rows[0].status == "will be closed on Friday, Jan. 10 for inclement weather."
    assert [row.extra["section"] for row in listing.rows] == [
        "Cullman County",
        "DeKalb County",
        "DeKalb County",
        "Madison County",
        "Madison County",
    ]
    assert {row.extra["split"] for row in listing.rows} == {"bold"}


WDHN_2025 = [
    "The Social Security Office in Dothan",
    "Houston County administration buildings, the Houston County Courthouse, the Probate and "
    "Revenue Commission buildings, and all other county owned buildings",
    "City of Dothan offices",
    "Dothan Municipal Court",
    "Omussee Park and boat ramp",
    "Dothan City Schools",
    "Houston County Schools",
    "Wallace Community College in Dothan and Eufaula",
    "All Troy campuses",
    "Providence Christian School and Providence Early Childhood",
    "Emmanuel Christian School",
    "Northside Methodist",
    "Houston Academy",
    "A+ Academic Services and Test Center",
    "The medical offices of Pulmonary Associates",
    "Southern Clinic PC",
    "Fairview Clinic",
    "Digestive Health Specialists",
    "Southern Alabama Regional Council on Aging (SARCOA)",
    "Henry County Schools",
    "Henry County government buildings",
    "Abbeville Christian School",
    "City of Headland",
    "Geneva County Schools",
    "Geneva City Schools",
    "Ozark City Schools",
    "Dale County",
    "Daleville City Schools",
    "Vivian B. Adams School",
    "Level Plains",
    "Dale County government offices",
    "Coffee County government offices",
    "Enterprise City School",
    "Coffee County Schools",
    "Elba City Schools",
    "Wiregrass Christian Academy",
    "Coffee County courtrooms",
    "Enterprise State Community College",
    "Enterprise City Council",
    "Professional Medical Associates",
    "Troy University",
]


def test_sentences_split_before_their_verb_and_county_headings_carry_over() -> None:
    fixture = body("nexstar-typed/wdhn-page-20250201215557.html")
    listing = nexstar_typed.parse(fixture)
    assert [row.name for row in listing.rows] == WDHN_2025
    # Every list item but the empty one and "Pike County:", typed as an item, which heads
    # the last list.
    assert_rows_are_the_items(listing, fixture)
    dothan = listing.rows[WDHN_2025.index("Dothan City Schools")]
    assert (dothan.status, dothan.extra["split"]) == ("are closed on Tuesday and Wednesday", "verb")
    # "<p><strong>Henry County</strong>:</p>" heads the next list. "Enterprise City Council
    # will convene in Work Session ..." is on the list, so it is a row like the others.
    assert listing.rows[WDHN_2025.index("Henry County Schools")].extra["section"] == "Henry County"
    council = listing.rows[WDHN_2025.index("Enterprise City Council")]
    assert council.status.startswith("will convene in Work Session at 11am Tuesday")
    assert listing.rows[-1].extra["section"] == "Pike County"
    assert listing.list_updated_at == datetime(2025, 1, 22, 2, 39, 32, tzinfo=UTC)


def test_an_item_with_nothing_after_its_name_takes_its_nested_items_as_its_status() -> None:
    fixture = body("nexstar-typed/wdhn-page-20241109012642.html")
    listing = nexstar_typed.parse(fixture)
    assert (listing.state, len(listing.rows)) == (ListingState.POPULATED, 26)
    assert_rows_are_the_items(listing, fixture)
    troy = listing.rows[0]
    assert (troy.name, troy.extra["split"], troy.extra["section"]) == (
        "Troy University",
        "none",
        "Schools",
    )
    assert troy.status == troy.extra["details"]
    assert troy.status.startswith(
        "Dothan Campus is closed, and classes are canceled on Thursday | Phenix City Campus"
    )
    dothan = listing.rows[19]
    assert (dothan.name, dothan.extra["section"]) == ("Dothan City", "Municipalities")
    assert dothan.status.startswith("City offices will close at 1:00 p.m. on Thursday.")
    assert listing.rows[-1].name == "Digestive Health Specialists in Enterprise"


def test_name_lines_take_the_status_lines_after_them() -> None:
    listing = nexstar_typed.parse(body("nexstar-typed/wrbl-page-20240926023920.html"))
    names = [row.name for row in listing.rows]
    assert len(names) == 43
    assert names[:6] == [
        "South Georgia Technical College",
        "Russell County School District",
        "Phenix City Schools",
        "Chattahoochee County Schools",
        "Harris County Schools",
        "Muscogee County School District",
    ]
    assert names[-3:] == [
        "Fourth Street Missionary Baptist Church",
        "Greater Peace Child Development Center",
        "Feeding the Valley Food Bank",
    ]
    phenix = listing.rows[2]
    assert (phenix.status, phenix.extra["split"], phenix.extra["section"]) == (
        "Remote days on Thursday and Friday",
        "name-line",
        "Schools",
    )
    # A quoted line with a dash inside it stays part of its entry's status.
    anne = listing.rows[6]
    assert anne.name == "St. Anne-Pacelli Catholic School"
    assert anne.status.startswith("Closed for Thursday and Friday \N{LEFT DOUBLE QUOTATION MARK}")
    assert "Open Door Community House" in names
    assert listing.rows[names.index("Open Door Community House")].extra["section"] == (
        "Other Closings"
    )
    # The shelter note in italics and "Fill out the form below ..." are notes, not entries.
    assert not any("SafeHouse" in name or "Fill out" in name for name in names)


def _table_names(markup: str) -> list[str]:
    """Each table row's first cell, read with a regular expression (header rows left out)."""
    names = []
    for row in re.findall(r"<tr>(.*?)</tr>", markup, re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        name = " ".join(unescape(re.sub(r"<[^>]+>", " ", cells[0])).split()) if cells else ""
        if name and name != "ENTITY":
            names.append(name)
    return names


def test_a_typed_table_reads_every_entry_under_its_heading() -> None:
    fixture = "nexstar-typed/wntz-article-20240116202750.html"
    listing = nexstar_typed.parse(body(fixture))
    names = [row.name for row in listing.rows]
    assert names == _table_names(body(fixture).decode("utf-8"))
    assert len(names) == 62
    assert listing.list_updated_at == datetime(2017, 12, 8, 17, 10, 47, tzinfo=UTC)
    lsu = listing.rows[1]
    assert (lsu.name, lsu.extra["split"], lsu.extra["section"]) == (
        "LSU \N{EN DASH} Alexandria",
        "table",
        "SCHOOL CLOSURES",
    )
    assert lsu.status == "Opening at 10 a.m. Friday Finals at 8:00 a.m. rescheduled to 1 p.m."
    # An entry with nothing typed beside it is kept, with the empty status.
    assert (listing.rows[0].name, listing.rows[0].status) == ("Northwestern State University", "")


def test_rest_pages_typed_by_hand_carry_the_page_time() -> None:
    whnt = nexstar_typed.parse(body("nexstar-typed/whnt-wp-20260928000457.json"))
    assert (whnt.variant, whnt.state) == ("nexstar-wp-typed", ListingState.POPULATED)
    # Typed as paragraphs: the bold-led entry is the row; "While traditional classes are
    # not currently in session ..." after it is prose.
    (row,) = whnt.rows
    assert row.name == "Madison County Schools"
    assert row.status.startswith("will operate on a two-hour delay on Monday")
    assert row.updated_text == "2026-06-07T23:29:23Z"
    assert row.extra["note"] == (
        "This is a list of early dismissals and the cancellation of extracurricular and "
        "after-school activities that have been issued for Monday, June 8, 2026:"
    )
    assert whnt.list_updated_at == datetime(2026, 6, 7, 23, 29, 23, tzinfo=UTC)
    wrbl = nexstar_typed.parse(body("nexstar-typed/wrbl-wp-20260928000508.json"))
    assert [(r.name, r.status) for r in wrbl.rows] == [
        ("Harris County Schools", "2-hour delay, Thursday, May 7, 2026")
    ]
    wdhn = nexstar_typed.parse(body("nexstar-typed/wdhn-wp-20260928000502.json"))
    (line,) = wdhn.rows
    # "There is a lightning delay ..." names nobody before its verb: the whole line is the name.
    assert (line.extra["split"], line.status) == ("none", "")
    assert line.name.startswith("There is a lightning delay at the Wicksburg V. Elba game")


def test_brightspot_rich_text_is_read_with_its_nested_details() -> None:
    listing = scripps_typed.parse(body("scripps-typed/kstu-page-20260928000513.html"))
    assert (listing.variant, listing.state) == ("scripps-typed-page", ListingState.POPULATED)
    (row,) = listing.rows
    assert row.name == "Provo City School District"
    assert row.status.startswith("will operate on a Two Hour Late Start schedule on Tuesday.")
    assert row.extra["split"] == "bold"
    details = row.extra["details"]
    assert isinstance(details, str)
    assert details.endswith("There will be NO AM-only half-day kindergarten or preschool.")
    # The page states no time for its text.
    assert (row.updated_text, listing.list_updated_at) == (None, None)


KSTU_2023 = [
    "Salt Lake City Schools",
    "Utah State University",
    "Alpine School District",
    "Salt Lake Community College",
    "Murray School District",
    "Tooele County School District",
    "Jordan School District schools and offices",
    "Granite School District",
    "Canyons School District",
    "Box Elder School District",
    "Provo City schools",
    "The Juab School District",
    "Utah Valley University",
    "NUAMES Early College High School (campuses in Layton and Ogden)",
    "North Star Academy in Bluffdale",
    "Blessed Sacrament Catholic School in Sandy",
    "Our Lady of Lourdes School in Salt Lake City",
    "Paradigm Charter Schools in South Jordan",
    "The University of Utah",
]


def test_kstu_storm_day_page_reads_every_list_item_under_its_day_headings() -> None:
    fixture = body("scripps-typed/kstu-page-20230222072846.html")
    listing = scripps_typed.parse(fixture)
    assert (listing.variant, listing.state) == ("scripps-typed-page", ListingState.POPULATED)
    assert [row.name for row in listing.rows] == KSTU_2023
    assert_rows_are_the_items(listing, fixture)
    # Granite School District's "distance learning day" is a row, whatever its words.
    granite = listing.rows[KSTU_2023.index("Granite School District")]
    assert granite.status == "to hold distance learning day on Wednesday."
    assert granite.extra["details"] == "Full details on district's website."
    alpine = listing.rows[2]
    assert (alpine.status, alpine.extra["split"]) == ("announces an online learning day.", "verb")
    assert alpine.extra["section"] == "WEDNESDAY, FEB. 22"
    sandy = listing.rows[KSTU_2023.index("Blessed Sacrament Catholic School in Sandy")]
    assert (sandy.status, sandy.extra["split"]) == ("Closed Wednesday", "colon")
    assert listing.rows[-1].extra["section"] == "TUESDAY, FEB. 21"
    # Brightspot states no time for the page's text.
    assert listing.list_updated_at is None


def test_kstu_four_days_later_reads_all_41_list_items() -> None:
    fixture = body("scripps-typed/kstu-page-20230226220604.html")
    listing = scripps_typed.parse(fixture)
    assert len(listing.rows) == 41
    assert_rows_are_the_items(listing, fixture)
    names = [row.name for row in listing.rows]
    assert names.count("Granite School District") == 2  # Thursday's and Wednesday's items
    assert listing.rows[0].extra["section"] == "THURSDAY, FEB. 23"
    assert listing.rows[-1].extra["section"] == "TUESDAY, FEB. 21"


def test_a_page_typed_as_paragraphs_under_headings_reads_each_paragraph() -> None:
    listing = scripps_typed.parse(body("scripps-typed/kstu-page-20221213030846.html"))
    (row,) = listing.rows
    assert row.name == "ALL Uintah School District schools"
    assert row.status.startswith("will delay opening by two hours. Half-day kindergarten")
    assert (row.extra["split"], row.extra["section"]) == ("verb", "DELAYS")


@pytest.mark.parametrize(
    ("fixture", "adapter"),
    [
        # "There are no current delays or closings at this time", over empty bullets.
        ("nexstar-typed/whnt-page-20200323124213.html", nexstar_typed.parse),
        # The page's standing note alone: "This page will update school, municipality, and
        # business closings during severe weather."
        ("nexstar-typed/wdhn-page-20231103133724.html", nexstar_typed.parse),
        # "There are currently no closings and delays due to severe weather"
        ("nexstar-typed/wdhn-page-20251123104109.html", nexstar_typed.parse),
        # "There are currently no school closings"
        ("scripps-typed/kstu-page-20250211130945.html", scripps_typed.parse),
        # The rich-text module with nothing in it: the typed list cleared.
        ("scripps-typed/kstu-page-20230220165100.html", scripps_typed.parse),
    ],
)
def test_a_typed_page_is_empty_only_when_it_says_so(fixture: str, adapter: object) -> None:
    assert callable(adapter)
    listing = adapter(body(fixture))
    assert isinstance(listing, Listing)
    assert (listing.state, listing.rows, listing.typed) == (ListingState.EMPTY, (), True)


@pytest.mark.parametrize(
    ("fixture", "adapter", "reason"),
    [
        # Only injected widgets in the typed block.
        ("errors/wrbl-page-20230207213448.html", nexstar_typed.parse, "no entry"),
        # "Test Block per Support"
        ("errors/wntz-alerts-20250911033628.html", nexstar_typed.parse, "Test Block per Support"),
        # An empty left column, no module at all.
        ("errors/ktvq-page-20260118082038.html", scripps_typed.parse, "an empty left column"),
        ("errors/krtv-page-20260928000518.html", scripps_typed.parse, "an empty left column"),
    ],
)
def test_a_typed_page_that_does_not_say_it_is_empty_is_an_error(
    fixture: str, adapter: object, reason: str
) -> None:
    assert callable(adapter)
    with pytest.raises(ShapeError, match=reason):
        adapter(body(fixture))


def test_the_plain_adapters_never_read_a_typed_page() -> None:
    for name, plain in (
        ("nexstar-typed/whnt-page-20210215043159.html", nexstar.parse),
        ("nexstar-typed/whnt-wp-20260928000457.json", nexstar.parse),
        ("nexstar-typed/wdhn-page-20231103133724.html", nexstar.parse),
        ("scripps-typed/kstu-page-20230222072846.html", scripps.parse),
        ("scripps-typed/kstu-page-20250211130945.html", scripps.parse),
        ("scripps-typed/kstu-page-20230220165100.html", scripps.parse),
    ):
        with pytest.raises(ShapeError):
            plain(body(name))
    # WJMN's leftover tab page (a storm day, 2023-02-23) and a KXAN news article with
    # closings typed into it are refused too: neither station is filed as a typed one.
    for name in ("errors/wjmn-page-20230223004907.html", "errors/kxan-article-20210219084809.html"):
        with pytest.raises(ShapeError):
            nexstar.parse(body(name))


def test_only_the_typed_platforms_read_typed_pages() -> None:
    typed_ids = {
        sid for sid, station in REGISTRY.stations.items() if station.platform.endswith("-typed")
    }
    assert typed_ids == {
        "nexstar-typed-kiah",
        "nexstar-typed-wdhn",
        "nexstar-typed-whnt",
        "nexstar-typed-wivb",
        "nexstar-typed-wntz",
        "nexstar-typed-wrbl",
        "scripps-typed-krtv",
        "scripps-typed-kstu",
        "scripps-typed-ktvh",
        "scripps-typed-ktvq",
        "scripps-typed-kxlf",
        "scripps-typed-kxlh",
    }
    assert ADAPTERS["nexstar-typed"] is nexstar_typed.parse
    assert ADAPTERS["scripps-typed"] is scripps_typed.parse
    for station in REGISTRY.stations.values():
        adapter = REGISTRY.platform_of(station).adapter
        if station.platform in {"nexstar", "scripps"}:
            assert adapter == station.platform, station.id


def _synthetic_rest(page: dict[str, object], content: str) -> bytes:
    return json.dumps({**page, "content": {"rendered": content}}).encode()


SYNTHETIC_CONTENTS = (
    "",
    "<p>Page moved</p>",
    '<div id="closings-root"></div><script src="/closings.js"></script>',
)


@pytest.mark.parametrize("content", SYNTHETIC_CONTENTS)
def test_a_module_page_without_its_list_is_an_error_not_an_empty_list(content: str) -> None:
    # KOIN's live REST page object (a closings-article station, read empty on 2026-09-26)
    # with its content replaced: blank, a note, a script's mount point.
    real = json.loads(body("nexstar/koin-page-20260926224830.json"))
    koin = dict(real[0] if isinstance(real, list) else real)
    assert nexstar.parse(body("nexstar/koin-page-20260926224830.json")).state is ListingState.EMPTY
    koin["title"] = {"rendered": "Closings"}
    synthetic = _synthetic_rest(koin, content)
    with pytest.raises(ShapeError):
        nexstar.parse(synthetic)
    # A station filed as typing its closings (WRBL's REST page object, content replaced):
    # still no list, and nothing says it is empty.
    typed_real = json.loads(body("nexstar-typed/wrbl-wp-20260928000508.json"))
    wrbl = dict(typed_real[0] if isinstance(typed_real, list) else typed_real)
    with pytest.raises(ShapeError):
        nexstar_typed.parse(_synthetic_rest(wrbl, content))


def test_a_registered_typed_page_that_says_it_is_empty_is_empty() -> None:
    real = json.loads(body("nexstar-typed/wrbl-wp-20260928000508.json"))
    page = dict(real[0] if isinstance(real, list) else real)
    synthetic = _synthetic_rest(page, "<p>There are currently no closings or delays.</p>")
    listing = nexstar_typed.parse(synthetic)
    assert (listing.variant, listing.state) == ("nexstar-wp-typed", ListingState.EMPTY)
    with pytest.raises(ShapeError):
        nexstar.parse(synthetic)


def test_a_typed_item_saying_the_list_is_empty_is_no_row() -> None:
    real = json.loads(body("nexstar-typed/wrbl-wp-20260928000508.json"))
    page = dict(real[0] if isinstance(real, list) else real)
    empty = _synthetic_rest(page, "<ul><li>There are no closings at this time.</li></ul>")
    listing = nexstar_typed.parse(empty)
    assert (listing.state, listing.rows) == (ListingState.EMPTY, ())
    # An organization's item that mentions closings is a row like any other.
    one = _synthetic_rest(
        page, "<ul><li>Synthetic ISD &#8211; No school closings, 2-hour delay</li></ul>"
    )
    (row,) = nexstar_typed.parse(one).rows
    assert (row.name, row.status) == ("Synthetic ISD", "No school closings, 2-hour delay")


@pytest.mark.parametrize("column", ["", '<div id="closings"></div><script>load()</script>'])
def test_a_scripps_module_page_without_its_module_is_an_error(column: str) -> None:
    synthetic = (
        '<html><body><h1 class="Page-pageHeading">School Closings &amp; Delays</h1>'
        f'<div class="left-column">{column}</div></body></html>'
    ).encode()
    with pytest.raises(ShapeError):
        scripps.parse(synthetic)
    with pytest.raises(ShapeError):
        scripps_typed.parse(synthetic)


def test_every_typed_slice_reads_as_its_fixture_and_slicing_again_changes_nothing() -> None:
    for name, adapter, slicer in (
        ("nexstar-typed/whnt-page-20210215043159.html", nexstar_typed.parse, nexstar.slice_body_v3),
        ("nexstar-typed/whnt-wp-20260928000457.json", nexstar_typed.parse, nexstar.slice_body_v3),
        ("scripps-typed/kstu-page-20260928000513.html", scripps_typed.parse, scripps.slice_body_v3),
        ("scripps-typed/kstu-page-20230220165100.html", scripps_typed.parse, scripps.slice_body_v3),
    ):
        fixture = body(name)
        assert slicer(fixture) == fixture, name
        assert adapter(slicer(fixture)) == adapter(fixture), name


SYNTHETIC_ARTICLE = (
    '<html><head><meta property="og:title" content="{title}" /></head><body>'
    '<div class="article-content rich-text"><ul><li>Some School District &#8211; Closed Monday'
    "</li></ul></div></body></html>"
)


def test_an_article_whose_title_is_not_a_closings_page_is_refused() -> None:
    synthetic_trial = SYNTHETIC_ARTICLE.format(title="Closing arguments set in trial").encode()
    with pytest.raises(ShapeError):
        nexstar_typed.parse(synthetic_trial)
    synthetic_page = SYNTHETIC_ARTICLE.format(title="School Closings and Delays").encode()
    with pytest.raises(ShapeError):
        nexstar.parse(synthetic_page)
    listing = nexstar_typed.parse(synthetic_page)
    assert [(row.name, row.status) for row in listing.rows] == [
        ("Some School District", "Closed Monday")
    ]
    # A page that states no time: no row carries one.
    assert listing.list_updated_at is None


def test_a_login_form_for_organizations_is_not_a_list() -> None:
    synthetic_form = (
        b'<html><head><title>Closings and Delays</title></head><body><div class="article-content '
        b'rich-text"><form><input type="password" name="password"></form><p>Status: Closed</p>'
        b"</div></body></html>"
    )
    with pytest.raises(ShapeError):
        nexstar_typed.parse(synthetic_form)


def test_labels_and_datelines_are_not_rows() -> None:
    synthetic = (
        b'<html><head><title>Weather delays</title></head><body><div class="article-content '
        b'rich-text"><p>AUSTIN (KXAN) &#8212; KXAN is keeping track of delays and closings.</p>'
        b"<p>NOTE: closings are listed below.</p><p><strong>Austin ISD:</strong> All classes "
        b"canceled Thursday.</p></div></body></html>"
    )
    listing = nexstar_typed.parse(synthetic)
    assert [(row.name, row.status) for row in listing.rows] == [
        ("Austin ISD", "All classes canceled Thursday.")
    ]


def test_page_times_are_read_as_utc() -> None:
    assert typed.parse_time("2021-02-15T03:13:33+00:00") == datetime(
        2021, 2, 15, 3, 13, 33, tzinfo=UTC
    )
    assert typed.parse_time("2026-06-07T23:29:23") == datetime(2026, 6, 7, 23, 29, 23, tzinfo=UTC)
    assert typed.parse_time("2025-01-21T18:00:00-06:00") == datetime(2025, 1, 22, 0, 0, tzinfo=UTC)
    assert typed.parse_time("Tuesday") is None


# The live reader's rule for typed lists ---------------------------------------------------

READ_AT = datetime(2026, 9, 28, 0, 5, tzinfo=UTC)
SYNTHETIC_ROW = ParsedRow(name="Synthetic School District", status="Closed")


def synthetic_typed(updated: datetime | None) -> Listing:
    return Listing(
        variant="nexstar-wp-typed",
        state=ListingState.POPULATED,
        rows=(SYNTHETIC_ROW,),
        list_updated_at=updated,
        typed=True,
    )


def test_typed_rows_are_current_only_within_the_window() -> None:
    fresh = READ_AT - fetch.TYPED_CURRENT + timedelta(minutes=1)
    old = READ_AT - fetch.TYPED_CURRENT - timedelta(minutes=1)
    assert not fetch.typed_not_current(synthetic_typed(fresh), READ_AT)
    assert fetch.typed_not_current(synthetic_typed(old), READ_AT)
    assert fetch.typed_not_current(synthetic_typed(None), READ_AT)
    untyped = synthetic_typed(None).model_copy(update={"typed": False})
    assert not fetch.typed_not_current(untyped, READ_AT)
    empty = Listing(variant="nexstar-wp-typed", state=ListingState.EMPTY, rows=(), typed=True)
    assert not fetch.typed_not_current(empty, READ_AT)


def test_an_undated_typed_page_is_current_only_when_its_words_name_a_near_day() -> None:
    kstu = scripps_typed.parse(body("scripps-typed/kstu-page-20230222072846.html"))
    # Its headings say "WEDNESDAY, FEB. 22" and "TUESDAY, FEB. 21" (2023).
    for day, current in (
        (datetime(2023, 2, 22, 13, 0, tzinfo=UTC), True),
        (datetime(2023, 2, 20, 23, 0, tzinfo=UTC), True),
        (datetime(2023, 2, 25, 13, 0, tzinfo=UTC), False),
        # A year on, 22 February is a Thursday: the heading dates nothing.
        (datetime(2024, 2, 22, 13, 0, tzinfo=UTC), False),
    ):
        assert fetch.typed_not_current(kstu, day) is not current, day
    # "on Tuesday" pins down no day.
    provo = scripps_typed.parse(body("scripps-typed/kstu-page-20260928000513.html"))
    assert fetch.typed_not_current(provo, datetime(2026, 9, 28, 13, 0, tzinfo=UTC))


def test_named_days_need_a_year_or_their_weekday() -> None:
    on = datetime(2025, 1, 9, tzinfo=UTC).date()
    text = "Monday, June 8, 2026; WEDNESDAY, FEB. 22; Jan. 10; Friday, Jan. 10; Feb. 30, 2025"
    assert typed.named_days(text, on) == [
        datetime(2026, 6, 8, tzinfo=UTC).date(),
        datetime(2025, 1, 10, tzinfo=UTC).date(),
    ]


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


def _client(tmp_path: Path, url: str, fixture: str, now: datetime) -> PoliteClient:
    def serve(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == USER_AGENT
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nDisallow: /wp-admin/\n")
        assert str(request.url) == url
        return httpx.Response(200, content=body(fixture))

    ticker = Ticker(now)
    return PoliteClient(
        httpx.Client(transport=httpx.MockTransport(serve), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )


WHNT_REST = "https://whnt.com/wp-json/wp/v2/pages/528267"


def test_a_typed_page_last_changed_months_ago_reads_as_empty(tmp_path: Path) -> None:
    station = REGISTRY.stations["nexstar-typed-whnt"].model_copy(
        update={
            "data_url": WHNT_REST,
            "page_url": "https://whnt.com/weather-closings/",
            "status": StationStatus.ACTIVE,
        }
    )
    client = _client(tmp_path, WHNT_REST, "nexstar-typed/whnt-wp-20260928000457.json", READ_AT)
    result = fetch.read_station(REGISTRY, station, client, READ_AT)
    (health,) = result.health
    assert (health.status, health.rows, health.variant) == (
        HealthStatus.EMPTY,
        0,
        "nexstar-wp-typed",
    )
    assert health.reason is not None
    assert "last changed 2026-06-07T23:29:23Z" in health.reason
    assert result.rows == []
    # The read itself records what the page held: evidence the station types closings there.
    (read,) = result.reads
    assert (read.state, read.rows) == (ListingState.POPULATED, 1)


def test_a_typed_page_changed_within_the_window_keeps_its_rows(tmp_path: Path) -> None:
    station = REGISTRY.stations["nexstar-typed-whnt"].model_copy(
        update={
            "data_url": WHNT_REST,
            "page_url": "https://whnt.com/weather-closings/",
            "status": StationStatus.ACTIVE,
        }
    )
    now = datetime(2026, 6, 8, 11, 0, tzinfo=UTC)
    client = _client(tmp_path, WHNT_REST, "nexstar-typed/whnt-wp-20260928000457.json", now)
    result = fetch.read_station(REGISTRY, station, client, now)
    (health,) = result.health
    assert (health.status, health.rows) == (HealthStatus.OK, 1)
    (row,) = result.rows
    assert (row.raw_name, row.raw_updated_text) == (
        "Madison County Schools",
        "2026-06-07T23:29:23Z",
    )


def test_an_undated_typed_page_that_names_the_day_keeps_its_rows(tmp_path: Path) -> None:
    url = "https://www.fox13now.com/weather/closings"
    station = REGISTRY.stations["scripps-typed-kstu"].model_copy(
        update={"page_url": url, "status": StationStatus.ACTIVE}
    )
    now = datetime(2023, 2, 22, 13, 0, tzinfo=UTC)
    client = _client(tmp_path, url, "scripps-typed/kstu-page-20230222072846.html", now)
    result = fetch.read_station(REGISTRY, station, client, now)
    (health,) = result.health
    assert (health.status, health.rows) == (HealthStatus.OK, 19)
    assert result.rows[0].raw_name == "Salt Lake City Schools"


def test_a_typed_page_with_no_time_is_stale(tmp_path: Path) -> None:
    url = "https://www.fox13now.com/weather/closings"
    station = REGISTRY.stations["scripps-typed-kstu"].model_copy(
        update={"page_url": url, "status": StationStatus.ACTIVE}
    )
    client = _client(tmp_path, url, "scripps-typed/kstu-page-20260928000513.html", READ_AT)
    result = fetch.read_station(REGISTRY, station, client, READ_AT)
    (health,) = result.health
    assert (health.status, health.rows) == (HealthStatus.STALE, 0)
    assert health.reason is not None
    assert "says no time for it" in health.reason
    assert result.rows == []
