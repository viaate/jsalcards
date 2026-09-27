"""Refusals, and populated forms not yet seen in a real body, of this part's readers.

The bodies built here are SYNTHETIC and confined to these tests, or small edits of
real fixtures (named where they are read): each follows the markup its format's
own source documents (FlashAlert's feed page sample, the refusals' small edits of
a format), so the adapters' reading of those forms is pinned until real captures
replace them. The ABC, NBC, FOX and CBS pages and files and the Emergency Closing
Center's data file have been seen populated in archived captures; they are tested
row by row in test_network_archived.py, and only edits of those captures are made
here. Every
refusal test checks that a body in no known shape is an error, never an empty list.
"""

import json
from pathlib import Path

import pytest

from snowlight.sources.stations import abc_owned, cbs_owned, ecc, flashalert, fox_owned, nbc_owned
from snowlight.sources.stations.model import ListingState, ShapeError

FIXTURES = Path(__file__).parent / "fixtures" / "networks"
REAL_ABC = (FIXTURES / "abc-owned/wabc-page-20260223174946.html").read_bytes()
"""WABC's page on 23 February 2026 (a real capture: 14 rows, with the page state)."""
REAL_ECC = (FIXTURES / "ecc/chicago-json-20260122024138.json").read_bytes()
"""The Emergency Closing Center's data file on 21 January 2026 (a real capture: 4 rows)."""


# ABC: edits of a real capture ---------------------------------------------------------


def test_abc_state_that_disagrees_with_the_rows_is_an_error() -> None:
    assert len(abc_owned.parse(REAL_ABC).rows) == 14
    body = REAL_ABC.replace(b'"name":"Secaucus SD"', b'"name":"Other SD"')
    assert body != REAL_ABC
    with pytest.raises(ShapeError, match="differ"):
        abc_owned.parse(body)


def test_abc_refuses_unknown_pages() -> None:
    with pytest.raises(ShapeError):
        abc_owned.parse(b"<html><body><p>School Closings</p></body></html>")
    no_default = REAL_ABC.replace(b"school-closings-list", b"other-list")
    with pytest.raises(ShapeError):
        abc_owned.parse(no_default)


# NBC -----------------------------------------------------------------------------------------


def test_nbc_route_refusals_and_nameless_items() -> None:
    with pytest.raises(ShapeError):
        nbc_owned.parse(b'{"closings": []}')
    with pytest.raises(ShapeError):
        nbc_owned.parse(b'[{"organization": 5, "status": "Closed"}]')
    listing = nbc_owned.parse(b'[{"organization": "", "status": "Closed"}]')
    assert (listing.state, listing.skipped_rows) == (ListingState.EMPTY, 1)


def test_nbc_page_without_a_closings_block_is_an_error() -> None:
    with pytest.raises(ShapeError):
        nbc_owned.parse(b"<html><body><div class='article-content--wrap'></div></body></html>")


# FOX -----------------------------------------------------------------------------------------

_COUNTY_HEAD = (
    b'<HTML><BODY><form name="form"><select name="site" size=1><option value="">'
    b"Select a county...<br></select></form><TABLE>"
    b'<TD colspan="2" CLASS="timestamp">UPDATED TUESDAY, JAN 16 AT 6:05 AM</TD></TR>'
)
_COUNTY_TAIL = (
    b'<TR><TD colspan="2"><a href="#top"><FONT CLASS="timestamp"><CENTER>Return to top'
    b"</CENTER></a></TD></TR></TABLE></BODY></HTML>"
)


def test_fox_county_menu_file_out_of_order_is_an_error() -> None:
    body = _COUNTY_HEAD + b'<TR><TD CLASS="status">Closed</TD></TR>' + _COUNTY_TAIL
    with pytest.raises(ShapeError, match="no name"):
        fox_owned.parse(body)
    with pytest.raises(ShapeError, match="no rows"):
        fox_owned.parse(_COUNTY_HEAD + _COUNTY_TAIL)


def test_fox_table_rows_need_their_column_headers() -> None:
    body = (
        b"<table><tr><th colspan=\"2\" bgcolor='999999'>January 16, 2024 6:05 am EST</th></tr>"
        b"<tr><td>Synthetic Schools</td><td>Closed</td></tr></table>"
    )
    with pytest.raises(ShapeError, match="Location/Status"):
        fox_owned.parse(body)


def test_fox_page_without_a_closings_frame_is_an_error() -> None:
    with pytest.raises(ShapeError, match="no closings frame"):
        fox_owned.parse(b'<!doctype html><html><iframe src="https://example.com/video"></iframe>')


# CBS -----------------------------------------------------------------------------------------


def test_cbs_widget_without_a_feed_is_an_error() -> None:
    body = b'<div data-school-closings-options=\'{"provider":"newsroom"}\'></div>'
    with pytest.raises(ShapeError, match="no feed"):
        cbs_owned.parse(body)
    with pytest.raises(ShapeError):
        cbs_owned.parse(b"<html><body>School Closings</body></html>")


def test_cbs_refuses_a_list_file_its_stations_do_not_use() -> None:
    flash = (
        b"<div id='cwcReportContainer'><div id='cwcReportHeader'>X</div>"
        b"<div class='cwcReport'>No information reported.</div></div>"
    )
    with pytest.raises(ShapeError, match="do not use"):
        cbs_owned.parse(flash)


# ECC: edits of a real capture -----------------------------------------------------------


def test_ecc_closing_without_a_name_is_skipped_not_read() -> None:
    data = json.loads(REAL_ECC)
    data["Closing"][1]["Name1"] = [""]
    listing = ecc.parse(json.dumps(data).encode())
    assert [row.name for row in listing.rows] == [
        "ASHBURN CHRISTIAN ACADEMY",
        "ST. JOHN THE BAPTIST CATHOLIC SCHOOL",
        "ELEMENT GLENDALE HEIGHTS",
    ]
    assert listing.skipped_rows == 1
    for closing in data["Closing"]:
        closing["Name1"] = [" "]
    with pytest.raises(ShapeError, match="missing its name"):
        ecc.parse(json.dumps(data).encode())


def test_ecc_refusals() -> None:
    with pytest.raises(ShapeError, match="unexpected fields"):
        ecc.parse(b'{"$": {"Time": "x"}, "Other": []}')
    with pytest.raises(ShapeError, match=r"no \$\.Time"):
        ecc.parse(b'{"Closing": []}')
    with pytest.raises(ShapeError):
        ecc.parse(b"<html><body>Loading...</body></html>")
    data = json.loads(REAL_ECC)
    data["Closing"][0]["Status1"] = "Closed"
    with pytest.raises(ShapeError, match="Status1"):
        ecc.parse(json.dumps(data).encode())


# FlashAlert: the sample on its feed page (xml-feeds.html, read 2026-09-27) ----------------

SYNTHETIC_FLASH_XML = (
    b'<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"  ?>\n'
    b'<flashnews updated="2012-08-14 03:12:18"><emergency>'
    b'<emergency_category name="Central Co. Schools">'
    b'<emergency_report report_id="26940" effective_date="2012-08-14 15:08:40" updated="0" '
    b'last_update="2012-08-14 15:08:50" testing="0" schoolrelated="1" orgid="413" custom="0" '
    b'operating_code="5" transpo_code="20">'
    b"<detail><![CDATA[2 hrs late, Buses on snow rts]]></detail>"
    b"<tomorrow><![CDATA[Effective tomorrow - Wed Aug 15th]]></tomorrow>"
    b'<orgname orgid="413" tier="1" zipcode="x"><![CDATA[Cityville Schools]]></orgname>'
    b"</emergency_report></emergency_category></emergency></flashnews>"
)


def test_synthetic_flashalert_xml_report() -> None:
    listing = flashalert.parse(SYNTHETIC_FLASH_XML)
    (row,) = listing.rows
    assert (row.name, row.status, row.updated_text) == (
        "Cityville Schools",
        "2 hrs late, Buses on snow rts",
        "2012-08-14 15:08:50",
    )
    assert row.extra["category"] == "Central Co. Schools"
    assert (row.extra["schoolrelated"], row.extra["operating_code"]) == ("1", "5")
    assert (row.extra["orgname_orgid"], row.extra["zipcode"], row.extra["tier"]) == (
        "413",
        "x",
        "1",
    )
    assert row.extra["tomorrow"] == "Effective tomorrow - Wed Aug 15th"


def test_flashalert_refusals() -> None:
    odd = SYNTHETIC_FLASH_XML.replace(b"<tomorrow>", b"<other>").replace(
        b"</tomorrow>", b"</other>"
    )
    with pytest.raises(ShapeError, match="unexpected elements"):
        flashalert.parse(odd)
    with pytest.raises(ShapeError):
        flashalert.parse(b"<html><body>Invalid or inactive account</body></html>")
    newsticker = (
        b'<TABLE><TR><TD CLASS="timestamp">UPDATED MONDAY, JAN 8 AT 5:00 AM</TD></TR>'
        b'<TR><TD CLASS="status">There are no active records at this time.</TD></TR></TABLE>'
    )
    with pytest.raises(ShapeError):
        flashalert.parse(newsticker)
