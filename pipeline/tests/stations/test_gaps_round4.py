"""Part 4's round-4 sources on real fixtures: the ALSDE list, KQ2's file, and the Mobile market.

Every fixture named here is a real body (see fixtures/gaps/README.md and PROVENANCE.json):
the Alabama State Department of Education's School Closures/Delays page as served on
2026-09-28 (four reports), KQ2's closings page and the file it frames (nothing posted),
and live reads of the Mobile - Pensacola market's district sites. Bodies named
``SYNTHETIC_*`` are made up here, confined to these tests, and exercise the edge cases
and refusals.
"""

import pytest

from snowlight.sources.stations import alsde, gap_fixtures, notices, npg
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.model import ListingState, ShapeError
from snowlight.sources.stations.registry import CountyBasis, load_registry

FOLDER = gap_fixtures.DEFAULT_FOLDER
REGISTRY = load_registry()

_CAPTIONS = (
    '<td id="ClosuresGrid_col0"></td><td id="ClosuresGrid_col1">Date</td>'
    '<td id="ClosuresGrid_col3">System</td><td id="ClosuresGrid_col5">School(s)</td>'
    '<td id="ClosuresGrid_col7">Type of Closure</td>'
    '<td id="ClosuresGrid_col8">Opening or Closing Time</td>'
)


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def _synthetic_grid(rows: str, captions: str = _CAPTIONS) -> bytes:
    """A made-up ALSDE page: the grid's captions over its data table."""
    return (
        f"<html><body><table><tr>{captions}</tr></table>"
        f'<table id="ClosuresGrid_DXMainTable">{rows}</table></body></html>'
    ).encode()


def _synthetic_row(*cells: str) -> str:
    tds = "".join(f'<td class="dxgv">{cell}</td>' for cell in cells)
    return f'<tr class="dxgvDataRow"><td class="dxgvCommandColumn dxgv">&nbsp;</td>{tds}</tr>'


# The ALSDE statewide list ------------------------------------------------------------------


def test_the_alsde_list_reads_one_row_per_school_named() -> None:
    listing = alsde.parse(_body("alsde/closures-live-20260928.html"))
    assert listing.variant == alsde.VARIANT
    assert listing.state is ListingState.POPULATED
    assert [row.name for row in listing.rows] == [
        "Pike County Elementary School",
        "Pike County High School",
        "Francis Marion School",
        "Perry County Alternative School",
        "Horseshoe Bend High School",
        "Francis Marion School",
        "Perry County Alternative School",
        "Robert C Hatch High School",
    ]
    assert [row.status for row in listing.rows] == ["Early Dismissal"] * 2 + ["Closed"] * 6
    first = listing.rows[0]
    assert first.updated_text == "9/25/2026 11:32:39 AM"
    assert first.extra == {
        "system": "Pike County",
        "date": "9/25/2026",
        "time": "1:00 PM",
        "reason": "Other",
        "comments": "Main waterline break in City of Brundidge. Must close PCES and PCHS at 1PM.",
        "activities_cancelled": False,
        "schools": 2,
    }
    horseshoe = listing.rows[4]
    assert horseshoe.extra["system"] == "Tallapoosa County"
    assert horseshoe.extra["activities_cancelled"] is True
    assert "time" not in horseshoe.extra  # the cell is blank


def test_the_alsde_slice_reads_as_its_original() -> None:
    body = _body("alsde/closures-live-20260928.html")
    assert alsde.slice_body(body) == body  # the fixture is a slice: slicing it changes nothing
    assert alsde.parse(alsde.slice_body(body)) == alsde.parse(body)


def test_synthetic_a_grid_with_no_data_row_is_empty() -> None:
    empty = '<tr class="dxgvEmptyDataRow"><td class="dxgv">No data to display</td></tr>'
    listing = alsde.parse(_synthetic_grid(empty))
    assert listing.state is ListingState.EMPTY
    assert listing.rows == ()


def test_synthetic_a_report_that_names_no_school_is_named_for_its_system() -> None:
    row = _synthetic_row("1/21/2025", "SYNTHETIC County", "", "Closed", "")
    [found] = alsde.parse(_synthetic_grid(row)).rows
    assert found.name == "SYNTHETIC County"
    assert found.extra == {"system": "SYNTHETIC County", "date": "1/21/2025", "schools": 0}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"<html><body><p>Weather Closure List</p></body></html>", "no ClosuresGrid table"),
        (
            _synthetic_grid("", captions='<td id="ClosuresGrid_col1">Date</td>'),
            "no System, Type of Closure column",
        ),
        (_synthetic_grid(_synthetic_row("1/21/2025", "SYNTHETIC County")), "has 2 cells, not 5"),
    ],
    ids=["SYNTHETIC_no_grid", "SYNTHETIC_no_columns", "SYNTHETIC_short_row"],
)
def test_the_alsde_adapter_refuses(body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        alsde.parse(body)


def test_the_snowstorm_capture_names_whole_systems_by_their_system() -> None:
    """The list on 2025-01-21 17:26 UTC (run 36445058527): most reports are for "All Schools"."""
    listing = alsde.parse(_body("alsde/closures-20250121.html"))
    assert listing.state is ListingState.POPULATED
    assert len(listing.rows) == 180
    assert len({row.extra["system"] for row in listing.rows}) == 54
    assert sum(1 for row in listing.rows if row.extra.get("all_schools")) == 97
    first = listing.rows[0]
    assert (first.name, first.status, first.updated_text) == (
        "Arab City",
        "Delayed",
        "1/20/2025 4:00:26 PM",
    )
    assert first.extra == {
        "system": "Arab City",
        "date": "1/22/2025",
        "time": "9:30 AM",
        "reason": "Other",
        "comments": "Due to frigid temperatures",
        "activities_cancelled": False,
        "schools": 1,
        "all_schools": True,
    }
    assert [(row.name, row.extra.get("reason")) for row in listing.rows[1:3]] == [
        ("Butler County", "Snow/Ice"),
        ("Clarke County", "Snow/Ice"),
    ]
    assert "All Schools" not in {row.name for row in listing.rows}


def test_the_school_years_capture_holds_baldwins_snow_closings() -> None:
    """The list on 2025-06-03 17:26 UTC (run 36470567011): the 2024-25 school year's reports."""
    listing = alsde.parse(_body("alsde/closures-20250603.html"))
    assert len(listing.rows) == 387
    assert len({row.extra["system"] for row in listing.rows}) == 67
    baldwin = [row for row in listing.rows if row.extra["system"] == "Baldwin County"]
    assert [(row.name, row.status, row.extra["date"]) for row in baldwin] == [
        ("Baldwin County", "Closed", "1/24/2025"),
        ("Baldwin County", "Closed", "1/23/2025"),
        ("Baldwin County", "Closed", "1/22/2025"),
        ("Baldwin County", "Closed", "1/21/2025"),
    ]
    assert {row.extra["reason"] for row in baldwin} == {"Snow/Ice"}
    assert "Mobile County" not in {row.extra["system"] for row in listing.rows}


@pytest.mark.parametrize(
    ("state", "message"),
    [
        ("'pageIndex':0,'pageCount':3,'pageRowCount':25", "one page of several"),
        ("'pageIndex':-1,'pageCount':1,'pageRowCount':9", "holds 9 reports but shows 1"),
    ],
    ids=["SYNTHETIC_paged", "SYNTHETIC_count_mismatch"],
)
def test_the_alsde_adapter_refuses_a_partial_grid(state: str, message: str) -> None:
    row = _synthetic_row("1/21/2025", "SYNTHETIC County", "All Schools", "Closed", "")
    control = f"ASPx.createControl(ASPxClientGridView,'ClosuresGrid','',{{{state}}});"
    script = f"<script>{control}</script>"
    body = _synthetic_grid(row).replace(b"</body>", script.encode() + b"</body>")
    with pytest.raises(ShapeError, match=message):
        alsde.parse(body)


def test_the_alsde_station_counts_the_systems_seen_on_its_list() -> None:
    station = REGISTRY.stations["alsde-statewide"]
    assert station.platform == "alsde"
    assert station.states == ("AL",)
    # the systems named in the live read and the archived captures read so far
    assert len(station.leaids) == 98
    assert all(leaid.startswith("01") for leaid in station.leaids)
    assert "0101350" in station.leaids  # Escambia County: reported on 2021-08-30 (Ida)
    assert "0100185" in station.leaids  # Saraland City: the same day
    assert "0100270" in station.leaids  # Baldwin County: the January 2025 snow (2025-06-03)
    assert "0100201" in station.leaids  # Legacy Prep, a charter district, reports there too
    # Mobile County, closed for the January 2025 snow, is on no capture read
    assert "0102370" not in station.leaids
    assert station.counties is not None
    assert station.counties.basis is CountyBasis.DISTRICT
    assert len(station.counties.fips) == 60
    assert "seen to name" in station.counties.source
    assert station.data_url == "https://schoolnotification.alsde.edu/SchoolClosuresPublic.aspx"
    assert station.robots
    assert all(check.allowed for check in station.robots)


def test_the_alsde_list_is_a_closings_list_and_proves_itself() -> None:
    # Not a district's general channel or a status board: any report is a closing.
    assert "alsde-statewide" not in notices.gated_adapters(REGISTRY)


# KQ2 (News-Press & Gazette, St. Joseph) ------------------------------------------------------


def test_kq2s_file_with_nothing_posted_is_an_empty_list() -> None:
    listing = npg.parse(_body("npg/kq2-closings-live-20260928.html"))
    assert listing.variant == npg.EMPTY
    assert listing.state is ListingState.EMPTY


def test_kq2s_file_with_postings_is_read_by_the_newsticker_reader() -> None:
    """KQ2's file on 2023-12-08 15:19 UTC (run 36445058527): two churches' service changes."""
    listing = npg.parse(_body("npg/kq2-closings-20231208.html"))
    assert listing.variant == "newsticker-html"
    assert [(row.name, row.status) for row in listing.rows] == [
        (
            "FIRST BAPTIST CHURCH, SAVANNAH",
            "Streaming service at 10:00 AM - In person attendance if you feel safe. No Sunday "
            "School or other services.",
        ),
        ("ST. FRANCIS BAPTIST TEMPLE", "All Services at St. Francis Baptist Temple are Cancelled!"),
    ]
    assert listing.rows[0].updated_text == "UPDATED FRIDAY, DEC 8 AT 9:15 AM"


def test_kq2s_file_with_a_schools_delay() -> None:
    """KQ2's file on 2021-01-28 14:03 UTC (run 36470567011): one school's two-hour delay."""
    listing = npg.parse(_body("npg/kq2-closings-20210128.html"))
    assert [(row.name, row.status) for row in listing.rows] == [
        ("NORTH DAVIESS R-III", "Classes delayed 2 hours")
    ]


def test_kq2s_file_in_the_pandemic_holds_63_postings() -> None:
    listing = npg.parse(_body("npg/kq2-closings-20200408.html"))
    assert listing.variant == "newsticker-html"
    assert len(listing.rows) == 63
    assert listing.rows[0].name == "1ST PRESBYTERIAN CHURCH (ALBANY, MO)"
    assert listing.rows[0].status == "Closed until May 1"


def test_kq2s_file_said_the_same_when_empty_in_2019() -> None:
    listing = npg.parse(_body("npg/kq2-closings-20190405.html"))
    assert listing.variant == npg.EMPTY
    assert listing.state is ListingState.EMPTY


def test_kq2s_page_follows_the_file_it_frames() -> None:
    listing = npg.parse(_body("npg/kq2-page-live-20260928.html"))
    assert listing.variant == npg.PAGE
    assert listing.state is ListingState.DEFERRED
    assert listing.follows == ("https://ftp2.kq2.com/closings.html",)


def test_synthetic_a_newsticker_file_with_postings_is_read_by_the_newsticker_reader() -> None:
    body = (
        b'<TABLE><TR><TD CLASS="timestamp">UPDATED MONDAY, JAN 6 AT 5:10 AM</TD></TR>'
        b'<TR><TD><FONT CLASS="orgname">SYNTHETIC R-II</FONT>: '
        b'<FONT CLASS="status">Closed</FONT></TD></TR></TABLE>'
    )
    listing = npg.parse(body)
    assert listing.variant == "newsticker-html"
    assert [(row.name, row.status) for row in listing.rows] == [("SYNTHETIC R-II", "Closed")]


@pytest.mark.parametrize(
    "body",
    [
        b'<TABLE><TR><TD CLASS="timestamp">UPDATED</TD></TR><TR><TD><FONT CLASS="orgname">'
        b'SYNTHETIC R-II</FONT>: <FONT CLASS="status">Closed</FONT></TD></TR><TR>'
        b'<TD CLASS="status">No currently active closings or delays to report.</TD></TR></TABLE>',
        b"<html><body><p>SYNTHETIC page without a closings frame</p></body></html>",
    ],
    ids=["SYNTHETIC_rows_and_empty_sentence", "SYNTHETIC_no_frame"],
)
def test_the_npg_adapter_refuses(body: bytes) -> None:
    with pytest.raises(ShapeError):
        npg.parse(body)


def test_kq2_covers_the_st_joseph_market() -> None:
    station = REGISTRY.stations["npg-kqtv"]
    assert station.dma == "St. Joseph, MO - KS DMA"
    assert station.counties is not None
    assert station.counties.basis is CountyBasis.DMA
    assert station.counties.fips == (
        "20043",  # Doniphan, KS
        "29003",  # Andrew
        "29021",  # Buchanan (St. Joseph)
        "29063",  # DeKalb
        "29087",  # Holt
        "29147",  # Nodaway
        "29227",  # Worth
    )
    assert station.data_url == "https://ftp2.kq2.com/closings.html"
    assert REGISTRY.platforms["npg"].terms.owner_decision is not None


# The Mobile - Pensacola market's district sites ------------------------------------------------


@pytest.mark.parametrize(
    ("station_id", "leaids", "fips"),
    [
        # Mobile and Baldwin: the two largest counties no working list reached (round 4).
        ("apptegy-mobile-al", ("0102370",), ("01097",)),
        ("finalsite-baldwin-al", ("0100270",), ("01003",)),
        ("finalsite-saraland-al", ("0100185",), ("01097",)),
        ("finalsite-satsuma-al", ("0100189",), ("01097",)),
        ("finalsite-chickasaw-al", ("0100188",), ("01097",)),
        ("apptegy-santa-rosa-fl", ("1201650",), ("12033", "12113")),
    ],
)
def test_the_mobile_pensacola_district_sources(
    station_id: str, leaids: tuple[str, ...], fips: tuple[str, ...]
) -> None:
    station = REGISTRY.stations[station_id]
    assert station.leaids == leaids
    assert station.counties is not None
    assert station.counties.basis is CountyBasis.DISTRICT
    assert station.counties.fips == fips
    assert "NCES CCD 2024-25 LEA directory" in station.counties.source
    assert station.robots
    assert all(check.allowed for check in station.robots)


def test_mobiles_live_homepage_has_no_banner() -> None:
    listing = adapter_for("apptegy")(_body("apptegy/mobile-live-20260928.html"))
    assert listing.variant == "apptegy-nuxt-state"
    assert listing.state is ListingState.EMPTY


def test_baldwins_empty_page_pops_answer_is_an_empty_list() -> None:
    listing = adapter_for("finalsite")(_body("finalsite/baldwin-page-pops-live-20260928.html"))
    assert listing.variant == "finalsite-no-page-pops"
    assert listing.state is ListingState.EMPTY


def test_chickasaws_event_page_pop_is_a_row_that_proves_nothing() -> None:
    listing = adapter_for("finalsite")(_body("finalsite/chickasaw-page-pops-live-20260928.html"))
    [row] = listing.rows
    assert row.name == "Parent University - October 3, 2026"
    assert row.updated_text == "2026-09-17T12:51:50-05:00"
    assert not notices.row_qualifies(row.name, row.status, listing.variant, board=False)


def test_santa_rosas_survey_banner_is_a_row_that_proves_nothing() -> None:
    listing = adapter_for("apptegy")(_body("apptegy/santa-rosa-live-20260928.html"))
    [row] = listing.rows
    assert row.name == "Santa Rosa County District Schools"
    assert row.status.startswith("Title I Parent Survey")
    assert not notices.row_qualifies(row.name, row.status, listing.variant, board=False)


def test_monroes_live_homepage_has_an_empty_alerts_list() -> None:
    listing = adapter_for("schoolblocks")(_body("schoolblocks/monroe-al-live-20260928.html"))
    assert listing.state is ListingState.EMPTY
