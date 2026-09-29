"""The gap-state adapters (Cowles' Montana ticker, Flathead County, the county sheets) on fixtures.

Every fixture in fixtures/gaps/ is a real body (live or archived; see its README and
PROVENANCE.json), and the tests pin exactly what each adapter reads from it. Bodies
named ``SYNTHETIC_*`` below are made up here, confined to these tests, and exercise
the refusals: a body in no known shape raises ShapeError rather than reading as a
day with no closings.
"""

import hashlib
import json
from pathlib import Path

import pytest

from snowlight.sources.stations import coesheet, cowles, flathead, gap_fixtures, gap_markup
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.fixtures import FixtureEntry
from snowlight.sources.stations.model import ListingState, ShapeError

FOLDER = gap_fixtures.DEFAULT_FOLDER
ENTRIES = gap_fixtures.load_entries(FOLDER)
TICKER = "https://company-wide-tickers.s3.us-west-2.amazonaws.com/KULR_School_Results/closings.html"


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda entry: entry.file)
def test_every_fixture_reads_as_its_provenance_says(entry: FixtureEntry) -> None:
    listing = adapter_for(entry.adapter)(_body(entry.file))
    assert listing.variant == entry.expected.variant
    assert listing.state is entry.expected.state
    assert tuple(row.name for row in listing.rows) == entry.expected.names
    assert len(listing.rows) == entry.expected.rows


def test_the_live_ticker_is_the_empty_grid() -> None:
    listing = cowles.parse(_body("cowles/ticker-live-20260927.html"))
    assert listing.variant == cowles.GRID
    assert listing.state is ListingState.EMPTY
    assert listing.rows == ()


@pytest.mark.parametrize(
    "name", ["cowles/kulr-page-live-20260927.html", "cowles/nonstop-page-live-20260927.html"]
)
def test_both_station_pages_frame_the_one_ticker(name: str) -> None:
    listing = cowles.parse(_body(name))
    assert listing.variant == cowles.PAGE
    assert listing.state is ListingState.DEFERRED
    assert listing.follows == (TICKER,)


def test_the_live_flathead_page_lists_every_school_with_its_status() -> None:
    listing = flathead.parse(_body("flathead/closures-live-20260927.html"))
    assert listing.variant == flathead.TABLES
    assert listing.state is ListingState.POPULATED
    assert len(listing.rows) == 35
    tables = [row.extra["table"] for row in listing.rows]
    assert tables.count("Public Schools") == 27
    assert tables.count("Private Schools") == 8
    closed = [row for row in listing.rows if row.status != "Open"]
    assert [(row.name, row.status, row.extra.get("comment")) for row in closed] == [
        ("West Valley", "Closed", "No running water")
    ]
    first = listing.rows[0]
    assert first.name == "Bigfork Elementary"
    assert first.updated_text == "September 25, 26 8:11 AM"
    assert first.extra["updated_scope"] == "page"
    assert "comment" not in first.extra
    assert str(first.extra["notice"]).startswith("School statuses are listed in the tables below.")
    assert "St. Matthew's" in [row.name for row in listing.rows]


@pytest.mark.parametrize("method", sorted(gap_fixtures.SLICERS))
def test_slicing_a_fixture_again_changes_nothing(method: str) -> None:
    for entry in ENTRIES:
        if entry.slice != method:
            continue
        body = _body(entry.file)
        assert gap_fixtures.SLICERS[method](body) == body


SYNTHETIC_GRID_WITH_ROWS = (
    b'<table width="100%" Border="0">Closings Last Updated at 6:05am on 1/13/2024<br>\n<br>\n'
    b'<tr><td width="100%" colspan="3"><b>SYNTHETIC GROUP</b></td></tr>'
    b'<tr><td width="33%"><b>Synthetic School A&nbsp;</b></td><td width="33%">Closed&nbsp;</td>'
    b'<td width="33%">&nbsp;</td></tr>'
    b'<tr><td width="33%"><b>Synthetic School B</b></td><td width="33%">2 Hours Late</td>'
    b'<td width="33%">No morning preschool</td></tr></table>'
)


def test_synthetic_grid_rows_keep_group_comment_and_file_time() -> None:
    listing = cowles.parse(SYNTHETIC_GRID_WITH_ROWS)
    assert listing.state is ListingState.POPULATED
    first, second = listing.rows
    assert (first.name, first.status, first.updated_text) == (
        "Synthetic School A",
        "Closed",
        "6:05am on 1/13/2024",
    )
    assert first.extra == {"updated_scope": "page", "group": "SYNTHETIC GROUP"}
    assert second.extra["comment"] == "No morning preschool"


@pytest.mark.parametrize(
    "body",
    [
        # SYNTHETIC: rows and the no-closings sentence together.
        SYNTHETIC_GRID_WITH_ROWS.replace(
            b"</table>",
            b"<tr><td><b>No Closings have been reported at this time</b></td><td></td><td></td>"
            b"</tr></table>",
        ),
        # SYNTHETIC: a grid row of two cells.
        b"<table>Closings Last Updated at 6:05am on 1/13/2024<br>"
        b"<tr><td><b>A</b></td><td>Closed</td></tr></table>",
        # SYNTHETIC: a grid row without the bold name cell.
        b"<table>Closings Last Updated at 6:05am on 1/13/2024<br>"
        b"<tr><td>A</td><td>Closed</td><td></td></tr></table>",
        # SYNTHETIC: a grid with neither rows nor the no-closings sentence.
        b"<table>Closings Last Updated at 6:05am on 1/13/2024<br></table>",
        # SYNTHETIC: a page that frames something else.
        b'<html><body><iframe src="https://example.com/closings.html"></iframe></body></html>',
        b"",
    ],
)
def test_cowles_refuses_bodies_in_no_known_shape(body: bytes) -> None:
    with pytest.raises(ShapeError):
        cowles.parse(body)


def _flathead_page(
    rows: str, header: str = "<th>School</th><th>Status</th><th>Comments</th>"
) -> bytes:
    """A SYNTHETIC page in the Flathead layout, for the refusals."""
    return (
        '<html><body><p class="ccm-block-page-attribute-display-wrapper">Last Updated January 13,'
        ' 24 6:00 AM</p><h2 id="public-schools-heading">Public Schools</h2>'
        '<table aria-labelledby="public-schools-heading" class="closure-table">'
        f"<thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table></body></html>"
    ).encode()


def test_a_synthetic_flathead_page_reads_its_rows() -> None:
    listing = flathead.parse(
        _flathead_page("<tr><td>Synthetic School</td><td>2 Hour Delay</td><td>Weather</td></tr>")
    )
    (row,) = listing.rows
    assert (row.name, row.status, row.updated_text) == (
        "Synthetic School",
        "2 Hour Delay",
        "January 13, 24 6:00 AM",
    )
    assert row.extra == {"table": "Public Schools", "updated_scope": "page", "comment": "Weather"}


@pytest.mark.parametrize(
    "body",
    [
        _flathead_page(""),
        _flathead_page("<tr><td>A</td><td>Open</td></tr>"),
        _flathead_page(
            "<tr><td>A</td><td>Open</td><td></td></tr>",
            header="<th>School</th><th>Status</th>",
        ),
        b'<html><body><table class="closure-table"><thead><tr><th>School</th><th>Status</th>'
        b"<th>Comments</th></tr></thead><tbody><tr><td>A</td><td>Open</td><td></td></tr></tbody>"
        b"</table></body></html>",
        b"<html><body><table><tr><td>Bigfork Elementary</td><td>Open</td></tr></table>"
        b"</body></html>",
    ],
)
def test_flathead_refuses_bodies_in_no_known_shape(body: bytes) -> None:
    with pytest.raises(ShapeError):
        flathead.parse(body)


def test_fixture_files_and_provenance_agree() -> None:
    names = {entry.file for entry in ENTRIES}
    on_disk = {
        path.relative_to(FOLDER).as_posix()
        for path in FOLDER.rglob("*")
        if path.is_file()
        and path.parent != FOLDER
        and not path.relative_to(FOLDER).as_posix().startswith(("errors/", "generator/"))
    }
    assert names == on_disk
    assert all(isinstance(entry.file, str) for entry in ENTRIES)
    assert Path(FOLDER / "README.md").read_text(encoding="utf-8") == gap_fixtures.render_readme(
        ENTRIES, gap_fixtures.load_errors(FOLDER), FOLDER
    )


SHEET_KEY = "2PACX-1vRt_q35uHlnknDJQ9VW3PzAu5a8qJdFvqA6gBrKOcLHp1Wx0toWwCFmDDqBh6ak38JSB0nC_Om6VOA_"
SHEET = f"https://docs.google.com/spreadsheets/d/e/{SHEET_KEY}"


def test_the_shasta_page_frames_the_widget_and_the_widget_names_its_tab() -> None:
    page = coesheet.parse(_body("coesheet/shasta-page-live-20260927.html"))
    assert (page.variant, page.state) == (coesheet.PAGE, ListingState.DEFERRED)
    assert page.follows == (f"{SHEET}/pubhtml?gid=541890420&single=true&widget=true&headers=false",)
    widget = coesheet.parse(_body("coesheet/shasta-widget-live-20260927.html"))
    assert (widget.variant, widget.state) == (coesheet.WIDGET, ListingState.DEFERRED)
    assert widget.follows == (f"{SHEET}/pubhtml/sheet?headers=false&gid=541890420",)


def test_the_shasta_tab_page_and_csv_output_hold_the_same_rows() -> None:
    tab = coesheet.parse(_body("coesheet/shasta-tab-live-20260927.html"))
    csv_output = coesheet.parse(_body("coesheet/shasta-sheet-live-20260927.csv"))
    assert (tab.variant, csv_output.variant) == (coesheet.TABLE, coesheet.CSV)
    assert len(tab.rows) == 95
    as_read = [(r.name, r.status, r.updated_text, r.extra) for r in tab.rows]
    assert as_read == [(r.name, r.status, r.updated_text, r.extra) for r in csv_output.rows]
    first = tab.rows[0]
    assert (first.name, first.status, first.updated_text) == (
        "Anderson Community Day",
        "OPEN",
        None,
    )
    assert first.extra == {
        "district": "ANDERSON UNION HIGH SCHOOL DISTRICT",
        "school_year": "2026-2027 SCHOOL YEAR",
    }
    changed = [(r.name, r.status, r.updated_text) for r in tab.rows if r.status != "OPEN"]
    assert changed == [
        ("Black Butte Elementary", "Closing at 12:45", "9/10 9:45"),
        ("Black Butte Jr. High", "Closing at 12:45", "9/10 9:45"),
    ]
    charter = next(r for r in tab.rows if r.name == "Anderson New Technology High")
    assert charter.extra["charter"] is True
    assert tab.rows[-1].name == "Whitmore Elementary"


def _synthetic_csv(*rows: str) -> bytes:
    """A SYNTHETIC closure sheet in the Shasta CSV layout, for the refusals."""
    head = (
        ",SHASTA COUNTY SCHOOLS,,2026-2027 SCHOOL YEAR,,,,\n"
        ",DISTRICT NAME,SCHOOL NAME (**CHARTER SCHOOL),DATE/TIME UPDATED,,,,OPEN / CLOSED INFO\n"
    )
    return (head + "".join(row + "\n" for row in rows)).encode()


def test_a_synthetic_csv_row_keeps_its_split_update_cells() -> None:
    listing = coesheet.parse(
        _synthetic_csv(",SYNTHETIC DISTRICT,,,,,,", ",,Synthetic School**,,1/5,,7:10,Closed")
    )
    (row,) = listing.rows
    assert (row.name, row.status, row.updated_text) == ("Synthetic School", "Closed", "1/5 7:10")
    assert row.extra == {
        "district": "SYNTHETIC DISTRICT",
        "charter": True,
        "updated_scope": "row",
        "school_year": "2026-2027 SCHOOL YEAR",
    }


@pytest.mark.parametrize(
    "body",
    [
        _synthetic_csv(",,Synthetic School,,,,,OPEN"),  # a school before any district
        _synthetic_csv(",SYNTHETIC DISTRICT,,,,,,"),  # no school at all
        _synthetic_csv(",SYNTHETIC DISTRICT,,,,,,", "x,,Synthetic School,,,,,OPEN"),
        _synthetic_csv(",SYNTHETIC DISTRICT,,,,,,", ",,Synthetic School,,,,OPEN"),  # 7 columns
        b",DISTRICT,SCHOOL,UPDATED,,,,OPEN / CLOSED INFO\n,,A,,,,,OPEN\n",  # another header
        b'<html><body><table class="waffle"><tr><td>A</td></tr></table></body></html>',
        b'<html><body><script>items.push({name: "x", pageUrl: "https:\\/\\/example.com\\/"});'
        b"</script></body></html>",
        b"<html><body><p>School closures</p></body></html>",
        b"plain text",
    ],
)
def test_coesheet_refuses_bodies_in_no_known_shape(body: bytes) -> None:
    with pytest.raises(ShapeError):
        coesheet.parse(body)


def test_the_trinity_page_embeds_a_sheet_the_server_writes() -> None:
    page = coesheet.parse(_body("coesheet/trinity-page-live-20260927.html"))
    assert (page.variant, page.state) == (coesheet.PAGE, ListingState.DEFERRED)
    key = "2PACX-1vRzrIeQ579iJDJCzp_oD9jDkAFAsjdNUHS-qY1Xe-_-kRRHyLaUS0av9-eoKHphpMPKr4HUVpEMTUiX"
    assert page.follows == (
        f"https://docs.google.com/spreadsheets/d/e/{key}/pubhtml"
        "?gid=0&single=true&widget=false&headers=false",
    )
    sheet = coesheet.parse(_body("coesheet/trinity-sheet-live-20260927.html"))
    assert (sheet.variant, sheet.state, len(sheet.rows)) == (
        coesheet.TABLE,
        ListingState.POPULATED,
        17,
    )
    assert {row.status for row in sheet.rows} == {"Open"}
    first = sheet.rows[0]
    assert (first.name, first.updated_text) == ("Burnt Ranch Elementary", "01/05/2026 8:47 AM")
    assert first.extra == {
        "district": "BURNT RANCH ESD",
        "updated_scope": "row",
        "school_year": "2025-2026 SCHOOL YEAR",
    }
    assert [row.name for row in sheet.rows if row.extra["district"] == "MOUNTAIN VALLEY USD"] == [
        "Hayfork Elementary",
        "Hayfork High",
        "Valley High",
    ]


def test_markup_helpers_decode_windows_1252_and_skip_nameless_rows() -> None:
    assert gap_markup.html_text("Caf\xe9 closed".encode("cp1252")) == "Café closed"
    assert gap_markup.make_row(" \xa0 ", "Closed", None, {}) is None
    row = gap_markup.make_row("  A  B ", " Closed\xa0today ", None, {"note": "x" * 5000})
    assert row is not None
    assert (row.name, row.status) == ("A B", "Closed today")
    assert len(str(row.extra["note"])) == 4000


GENERATOR = FOLDER / "generator"


def test_a_real_populated_grid_of_the_same_generator_reads_row_by_row() -> None:
    # Cowles' own ticker has no archived capture; this is Sinclair WCYB's grid file (the
    # same "Closings Last Updated at" generator) as the archive held it on a storm night,
    # kept only to test the populated form (see PROVENANCE.generator.json).
    provenance = json.loads((GENERATOR / "PROVENANCE.generator.json").read_text())
    entry = provenance["wcyb-grid-20260223.html"]
    body = (GENERATOR / "wcyb-grid-20260223.html").read_bytes()
    assert hashlib.sha256(body).hexdigest() == entry["sha256"]
    listing = cowles.parse(body)
    assert (listing.variant, listing.state) == (cowles.GRID, ListingState.POPULATED)
    assert [row.name for row in listing.rows] == entry["names"]
    assert len(listing.rows) == 35
    first = listing.rows[0]
    assert (first.name, first.status, first.updated_text) == (
        "BUCHANAN CO. SCHOOLS",
        "Virtual Learning",
        "12:10am on 2/23/2026",
    )
    assert first.extra == {"updated_scope": "page"}


def test_the_archived_storm_day_flathead_page_reads_its_closures() -> None:
    listing = flathead.parse(_body("flathead/closures-20260119.html"))
    assert (listing.variant, listing.state, len(listing.rows)) == (
        flathead.CARDS,
        ListingState.POPULATED,
        35,
    )
    changed = [
        (row.name, row.status, row.extra.get("comment"))
        for row in listing.rows
        if row.status != "Open" or "comment" in row.extra
    ]
    assert changed == [
        ("CAYUSE PRAIRIE", "Closed", None),
        ("DEER PARK", "Open", "2 hour delayed start due to power"),
        ("FAIR-MONT-EGAN", "Closed", None),
        ("OLNEY-BISSELL", "Closed", None),
        ("PLEASANT VALLEY", "Closed", None),
        ("WEST GLACIER", "Closed", None),
    ]
    first = listing.rows[0]
    assert first.updated_text == "Wednesday, December 17th, 2025"
    assert first.extra == {
        "table": "Public Schools",
        "school_year": "2025-26",
        "updated_scope": "page",
    }
    assert listing.rows[-1].extra["table"] == "Private Schools"


def test_a_blank_status_in_the_older_layout_is_kept_as_blank() -> None:
    listing = flathead.parse(_body("flathead/closures-20260412.html"))
    blank = [row.name for row in listing.rows if row.status == ""]
    assert blank == ["ONESCHOOL GLOBAL NORTH AMERICA", "VALLEY ADVENTIST CHRISTIAN SCHOOL"]
    assert listing.rows[0].updated_text == "Friday, March 13th, 2026"


def test_the_old_domain_page_of_january_2023_puts_its_date_on_the_next_line() -> None:
    listing = flathead.parse(_body("flathead/closures-oldsite-20230103.html"))
    assert (listing.variant, len(listing.rows)) == (flathead.CARDS, 34)
    first = listing.rows[0]
    assert (first.name, first.status, first.updated_text) == (
        "BIGFORK ELEMENTARY",
        "OPEN",
        "TUESDAY, JANUARY 3, 2023",
    )
    assert first.extra["school_year"] == "2023"
    closed = [
        (r.name, r.status, r.extra.get("comment")) for r in listing.rows if r.status != "OPEN"
    ]
    assert closed == [
        ("SOMERS/LAKESIDE", "CLOSED", "WINTER BREAK, RETURNING ON 1/4/23"),
        ("ST. MATTHEW'S", "CLOSED", "WINTER BREAK RETURNING 1/4/2023"),
    ]


def test_the_old_domain_storm_day_of_february_2024() -> None:
    listing = flathead.parse(_body("flathead/closures-oldsite-20240209.html"))
    assert listing.rows[0].updated_text == "Friday, February 9th, 2024"
    assert [r.name for r in listing.rows if r.status == "Closed"] == [
        "FAIR-MONT-EGAN",
        "OLNEY-BISSELL",
        "PLEASANT VALLEY",
        "WEST VALLEY",
    ]
