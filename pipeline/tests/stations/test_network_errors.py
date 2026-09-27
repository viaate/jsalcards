"""Refusals of the network, ECC and FlashAlert adapters, and the fixture tool's commands.

Every malformed body here is SYNTHETIC and confined to this test: each is a small
edit of a real format (the real fixtures in fixtures/networks/ are read by
test_network_fixtures.py) that the adapter must refuse rather than read as an
empty list. The fixture-tool tests run the command line over real fixture bodies
placed in a synthetic capture log and a synthetic snapshot manifest.
"""

import hashlib
import json
from pathlib import Path

import pytest

from snowlight.sources.stations import (
    abc_owned,
    cbs_owned,
    ecc,
    flashalert,
    fox_owned,
    nbc_owned,
    network_fixtures,
)
from snowlight.sources.stations.model import ListingState, ShapeError

FIXTURES = Path(__file__).parent / "fixtures" / "networks"
_EMPTY_ABC = (
    '<section class="school-list inner"><div class="meta">Last updated: <!-- -->'
    '09/26/2026 01:05am</div><li class="school-closing"><span class="school-closing-name">'
    "No Closings at this time.</span></li></section>"
)


def _abc(state: str, section: str = _EMPTY_ABC) -> bytes:
    return f"<html><body>{section}<script>{{{state}}}</script></body></html>".encode()


@pytest.mark.parametrize(
    "state",
    [
        '"schoolclosings":{"time":1,"states":[}',
        '"schoolclosings":{"time":1,"states":[],"other":1}',
        '"schoolclosings":{"time":"1","states":[]}',
        '"schoolclosings":{"time":1,"states":[{"name":"X"}]}',
        '"schoolclosings":{"time":1,"states":[{"name":"X","schools":[5]}]}',
        '"schoolclosings":{"time":1,"states":[{"name":"X","schools":[{"name":5}]}]}',
        '"schoolclosings":{"time":1,"states":[{"name":"X","schools":[{"name":"A"}]}]}',
    ],
)
def test_abc_page_state_in_an_unknown_shape_is_an_error(state: str) -> None:
    with pytest.raises(ShapeError):
        abc_owned.parse(_abc(state))


_NO_SCHOOLS = '"schoolclosings":{"time":1,"states":[]}'


def test_abc_list_refusals() -> None:
    no_meta = _EMPTY_ABC.replace("Last updated:", "Updated:")
    with pytest.raises(ShapeError, match="Last updated"):
        abc_owned.parse(_abc(_NO_SCHOOLS, no_meta))
    headless = (
        '<section class="school-list inner"><div class="meta">Last updated: 1</div>'
        '<ul class="school-closings-list"><li class="school-closing">'
        '<span class="school-closing-name">A</span></li></ul></section>'
    )
    with pytest.raises(ShapeError, match="no state heading"):
        abc_owned.parse(_abc(_NO_SCHOOLS, headless))
    loose = headless.replace(
        '<ul class="school-closings-list">',
        '<div class="section-header">New York</div><ul class="school-closings-list">',
    ).replace("</section>", '<li class="school-closing"><span>B</span></li></section>')
    with pytest.raises(ShapeError, match="outside"):
        abc_owned.parse(_abc(_NO_SCHOOLS, loose))
    nameless = headless.replace(
        '<ul class="school-closings-list">',
        '<div class="section-header">New York</div><ul class="school-closings-list">',
    ).replace(">A<", "><")
    with pytest.raises(ShapeError, match="missing its name"):
        abc_owned.parse(_abc(_NO_SCHOOLS, nameless))


_LEGACY_ROW = '<li class="school-closing"><span class="school-closing-name">A </span></li>'
_LEGACY_EMPTY = (
    '<li class="school-closing"><span class="school-closing-name">No Closings at this time. '
    "</span></li>"
)


def _legacy(inner: str) -> bytes:
    return (
        f'<html><body><section class="school-list inner">{inner}</section></body></html>'.encode()
    )


def test_abc_legacy_list_refusals() -> None:
    both = (
        f'<ul class="school-closings-list">{_LEGACY_EMPTY}</ul><div class="section-header">X</div>'
    )
    both += f'<ul class="school-closings-list">{_LEGACY_ROW}</ul>'
    with pytest.raises(ShapeError, match="both closings and the no-closings line"):
        abc_owned.parse(_legacy(both))
    mixed = (
        f'<ul class="school-closings-list">{_LEGACY_ROW}</ul><div class="section-header">X</div>'
    )
    mixed += f'<ul class="school-closings-list">{_LEGACY_ROW}</ul>'
    with pytest.raises(ShapeError, match="mixes"):
        abc_owned.parse(_legacy(mixed))
    more = f'<div class="section-header">{abc_owned.MORE_HEADING}</div>'
    more += f'<ul class="school-closings-list">{_LEGACY_ROW}</ul>'
    with pytest.raises(ShapeError, match="other than links"):
        abc_owned.parse(_legacy(more))
    # One empty list and nothing else is the empty state (KTRK, December 2015, a real
    # fixture); with anything beside it, such as a state anchor, it is not.
    bare = abc_owned.parse(_legacy('<ul class="school-closings-list"></ul>'))
    assert (bare.state, bare.rows) == (ListingState.EMPTY, ())
    anchored = '<a href="#schools-PA" class="state-anchor">Pennsylvania</a>'
    with pytest.raises(ShapeError, match="neither"):
        abc_owned.parse(_legacy(anchored + '<ul class="school-closings-list"></ul>'))
    with pytest.raises(ShapeError, match="neither"):
        abc_owned.parse(
            _legacy('<ul class="school-closings-list"></ul><ul class="school-closings-list"></ul>')
        )
    outside = f'<ul class="school-closings-list">{_LEGACY_ROW}</ul><div>{_LEGACY_ROW}</div>'
    with pytest.raises(ShapeError, match="outside"):
        abc_owned.parse(_legacy(outside))
    with pytest.raises(ShapeError, match="Last updated"):
        abc_owned.parse(_legacy('<div class="meta">Updated</div>' + both))
    nameless = '<ul class="school-closings-list"><li class="school-closing"><span></span></li></ul>'
    with pytest.raises(ShapeError, match="missing its name"):
        abc_owned.parse(_legacy(nameless))


def test_abc_county_text_is_kept_as_written_without_its_parentheses() -> None:
    section = (
        '<section class="school-list inner"><div class="meta">Last updated: 1</div>'
        '<div class="section-header">Texas</div><ul class="school-closings-list">'
        '<li class="school-closing"><span class="school-closing-name">A ISD</span>'
        '<span class="school-closing-county"> (Harris)</span></li>'
        '<li class="school-closing"><span class="school-closing-name">B ISD</span>'
        '<span class="school-closing-county">Fort Bend</span></li></ul></section>'
    )
    listing = abc_owned.parse(_abc('"x":1', section))
    assert [(row.name, row.status, row.extra["county"]) for row in listing.rows] == [
        ("A ISD", "", "Harris"),
        ("B ISD", "", "Fort Bend"),
    ]
    assert listing.list_updated_at is None


def test_abc_frame_refusals_and_slicing() -> None:
    two_frames = (
        b'<html><div class="main main-left"><iframe src="https://a/x.html"></iframe>'
        b'<iframe src="https://b/y.html"></iframe></div></html>'
    )
    with pytest.raises(ShapeError):
        abc_owned.parse(two_frames)
    with pytest.raises(ShapeError):
        abc_owned.slice_page(b"<html><body>nothing</body></html>")
    real = (FIXTURES / "abc-owned/wls-page-live-20260927013726.html").read_bytes()
    assert abc_owned.slice_page(real) == real


def test_nbc_page_before_the_wordpress_platform_refusals() -> None:
    real = (FIXTURES / "nbc-owned/wcau-page-20190220201954.html").read_bytes()
    empty = (FIXTURES / "nbc-owned/wbts-page-20170204125739.html").read_bytes()
    assert len(nbc_owned.parse(real).rows) == 47
    other = empty.replace(b"Forecast: School's Open.", b"Forecast: Snow.")
    with pytest.raises(ShapeError, match="neither a listing"):
        nbc_owned.parse(other)
    extra = real.replace(b"ABC Learning Station<br/>", b"ABC Learning Station<br/><em>x</em>")
    with pytest.raises(ShapeError, match="unexpected <em>"):
        nbc_owned.parse(extra)
    trailing = real.replace(b"<span>Closed </span></p>", b"<span>Closed </span>more</p>", 1)
    with pytest.raises(ShapeError, match="text after its status"):
        nbc_owned.parse(trailing)
    start = real.index(b'<p class="closing_item">')
    end = real.rindex(b"</p>", 0, real.index(b'<p class="schoolOpen"></p>')) + len(b"</p>")
    with pytest.raises(ShapeError, match="no named closing"):
        nbc_owned.parse(real[:start] + real[end:])
    assert nbc_owned.slice_page(real) == real
    with pytest.raises(ShapeError):
        nbc_owned.slice_page(b"<html><body><div id='other'></div></body></html>")


def test_nbc_page_refusals() -> None:
    both = (
        b'<div class="article-content--wrap closings"><div class="closings--inactive">'
        b'<h3 class="closings__heading">Forecast: School&#039;s Open.</h3></div>'
        b'<div class="closings--active"></div></div>'
    )
    with pytest.raises(ShapeError, match="neither active nor inactive"):
        nbc_owned.parse(both)
    other_heading = both.replace(b'<div class="closings--active"></div>', b"").replace(
        b"Forecast", b"Weather"
    )
    with pytest.raises(ShapeError, match="School's Open"):
        nbc_owned.parse(other_heading)
    no_listings = b'<div class="article-content--wrap closings"><div class="closings--active">'
    with pytest.raises(ShapeError, match="no listings"):
        nbc_owned.parse(no_listings + b"</div></div>")
    tabs = (
        b'<div class="article-content--wrap closings"><div class="closings__tabs">'
        b'<ul class="tabs__nav"><li><a href="#all">All</a></li><li><a href="#maine">Maine</a>'
        b'</li></ul><div class="tab-pane" id="all"><div class="listing">'
        b'<h4 class="listing__org">A (Maine)</h4><p class="listing__notice">Closed</p></div>'
        b'</div><div class="tab-pane" id="maine"></div><div class="tab-pane" id="vt"></div>'
        b"</div></div>"
    )
    with pytest.raises(ShapeError, match="has no tab"):
        nbc_owned.parse(tabs)
    with pytest.raises(ShapeError, match="All"):
        nbc_owned.parse(tabs.replace(b'id="vt"', b'id="maine"'))
    no_all = tabs.replace(b'href="#all"', b'href="#x"')
    with pytest.raises(ShapeError, match="'All' pane"):
        nbc_owned.parse(no_all)
    with pytest.raises(ShapeError):
        nbc_owned.slice_page(b"<html></html>")


def test_fox_tab_list_refusals() -> None:
    head = (
        "<h4>School Closings Last Updated: Fri Apr 17 01:30:02 CDT 2020</h4>"
        '<ul id="schools" class="closings">'
    )
    good = (
        '<li class="ln-a"><span class="place">A School | <span class="pstatus">Closed</span></li>'
    )
    listing = fox_owned.parse((head + good + "</ul>").encode())
    assert [(row.name, row.status) for row in listing.rows] == [("A School", "Closed")]
    with pytest.raises(ShapeError, match="not a place and its status"):
        fox_owned.parse((head + '<li class="ln-a">A School - Closed</li></ul>').encode())
    with pytest.raises(ShapeError, match="empty form is unseen"):
        fox_owned.parse((head + "</ul>").encode())


def test_fox_refusals() -> None:
    menu_only = (
        b'<form><select name="site"><option>Select a county...</select></form>'
        b'<TABLE><TR><TD CLASS="none">There are no closings or cancellations at this time.'
        b"</TD></TR></TABLE>"
    )
    with pytest.raises(ShapeError, match="no update time"):
        fox_owned.parse(menu_only)
    unmenu = menu_only.replace(b"Select a county...", b"Choose")
    with pytest.raises(ShapeError):
        fox_owned.parse(unmenu)
    both = menu_only.replace(
        b"<TABLE>",
        b'<TABLE><TR><TD CLASS="timestamp">UPDATED</TD></TR><TR><TD CLASS="orgname">A</TD>'
        b'<TD CLASS="status">Closed</TD></TR>',
    )
    with pytest.raises(ShapeError, match="says nothing"):
        fox_owned.parse(both)
    dangling = both.replace(b'<TD CLASS="status">Closed</TD>', b"")
    with pytest.raises(ShapeError, match="no status"):
        fox_owned.parse(dangling)
    table = (
        b"<table><tr><th colspan=\"2\" bgcolor='999999'>September 26</th></tr>"
        b"<tr><th colspan=\"2\" bgcolor='999999'>SOMETHING ELSE</th></tr></table>"
    )
    with pytest.raises(ShapeError, match="out of place"):
        fox_owned.parse(table)
    with pytest.raises(ShapeError, match="do not use"):
        fox_owned.parse(
            (FIXTURES / "flashalert/portland-report-live-20260927013931.html").read_bytes()
        )
    with pytest.raises(ShapeError):
        fox_owned.parse(b"just text")


def test_fox_cell_and_table_refusals() -> None:
    dallas = (FIXTURES / "fox-owned/kdfw-file-20250109195953.html").read_bytes()
    no_status = dallas.replace(b'<FONT CLASS="status">Closed Tomorrow</FONT>', b"", 1)
    with pytest.raises(ShapeError, match="not a category, name and status"):
        fox_owned.parse(no_status)
    two_times = dallas.replace(b"</TD></TR>", b'</TD></TR><TR><TD CLASS="timestamp">X</TD></TR>', 1)
    with pytest.raises(ShapeError, match="exactly one update time"):
        fox_owned.parse(two_times)
    classed = dallas.replace(b'<TD BGCOLOR="#EEEEEE">', b'<TD CLASS="none">', 1)
    with pytest.raises(ShapeError, match="none cell"):
        fox_owned.parse(classed)
    table = (FIXTURES / "fox-owned/wttg-file-20250104184041.html").read_bytes()
    both = table.replace(
        b"</table>",
        b'<tr><th colspan="2">THERE ARE CURRENTLY NO CLOSINGS OR CANCELLATIONS</th></tr></table>',
    )
    with pytest.raises(ShapeError, match="says nothing is listed"):
        fox_owned.parse(both)
    three = table.replace(
        b"Closed Monday<BR></font></td>", b"Closed Monday<BR></font></td><td>x</td>"
    )
    with pytest.raises(ShapeError, match="outside the Location/Status columns"):
        fox_owned.parse(three)
    quiet = (FIXTURES / "fox-owned/witi-page-20200730224123.html").read_bytes()
    with pytest.raises(ShapeError, match="no closings frame"):
        fox_owned.parse(quiet.replace(b"There are currently no closings", b"Closings soon"))


def test_ecc_and_flashalert_refusals() -> None:
    with pytest.raises(ShapeError, match="not a JSON object"):
        ecc.parse_json([])
    with pytest.raises(ShapeError, match="not a list"):
        ecc.parse(b'{"$": {"Time": "x"}, "Closing": {"Name1": ["A"]}}')
    with pytest.raises(ShapeError, match="not an object"):
        ecc.parse(b'{"$": {"Time": "x"}, "Closing": [5]}')
    with pytest.raises(ShapeError, match="list of text"):
        ecc.parse(b'{"$": {"Time": "x"}, "Closing": [{"Name1": "A"}]}')
    with pytest.raises(ShapeError, match="missing its name"):
        ecc.parse(b'{"$": {"Time": "x"}, "Closing": [{"Name1": [""]}]}')
    head = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n'
    for body in (
        head + b"<flashnews><other/></flashnews>",
        head + b"<flashnews><emergency><x/></emergency></flashnews>",
        head + b'<flashnews><emergency><emergency_category name="A"><x/>'
        b"</emergency_category></emergency></flashnews>",
        head + b'<flashnews><emergency><emergency_category name="A"><emergency_report>'
        b"<orgname></orgname></emergency_report></emergency_category></emergency></flashnews>",
        head + b"<flashnews><emergency>",
    ):
        with pytest.raises(ShapeError):
            flashalert.parse_xml(body)
    with pytest.raises(ShapeError, match="root"):
        flashalert.parse_xml(head + b"<flashnewz/>")


_SITE = (
    "<html><head><title>FlashAlertEugene - Emergency Reports</title></head><body>"
    "<div id='cwcReportHeader'>Eugene Emerg. Reports for Thu. Feb. 28 - 1:32 am</div>"
    "<div id='cwcReportBody'>{}</div></body></html>"
)
_SITE_CAT = (
    '<div class="cwcReportCat ReportToggle"> Lane Co. Schools <span class="GroupCount">({})</div>'
)
_SITE_ROW = '<div class="cwcReport">&bull; <a href="x">Blachly Sch. Dist.</a> - Closed</div>'
_SITE_EMPTY = f'<div class="cwcReport">{flashalert.SITE_EMPTY}</div>'


def _site(inner: str) -> bytes:
    return _SITE.format(inner).encode()


def test_flashalert_site_page_refusals() -> None:
    good = flashalert.parse(_site(_SITE_CAT.format(2) + _SITE_ROW))
    assert [(row.name, row.status, row.extra["category_count"]) for row in good.rows] == [
        ("Blachly Sch. Dist.", "Closed", 2)  # the page's own count, kept as given
    ]
    with pytest.raises(ShapeError, match="says nothing is reported"):
        flashalert.parse(_site(_SITE_CAT.format(1) + _SITE_ROW + _SITE_EMPTY))
    with pytest.raises(ShapeError, match="no ' - '"):
        flashalert.parse(_site('<div class="cwcReport">&bull; Blachly closed</div>'))
    with pytest.raises(ShapeError, match="not followed by"):
        flashalert.parse(_site('<div class="cwcReport">&bull; <a>Blachly</a> Closed</div>'))
    with pytest.raises(ShapeError, match="no rows and no empty-state"):
        flashalert.parse(_site(_SITE_CAT.format(0)))
    with pytest.raises(ShapeError, match="no name or no status side"):
        flashalert.parse(_site("<div class='cwcReportLR'><div class='cwcReportLeft'>A</div></div>"))
    with pytest.raises(ShapeError, match="no report header"):
        flashalert.parse(_site("").replace(b"cwcReportHeader", b"other"))


_ECC_HEAD = (
    "<html><head><title>ECC: Status Search</title></head><body>"
    '<p class="text">... ECC facilities as of 11:50 PM, CST (updated every 15 minutes).</p>'
    "<table><tr><td>&nbsp;</td><td><p>Facility Name</p></td><td>&nbsp;</td><td><p>City</p></td>"
    "<td>&nbsp;</td><td><p>Status</p></td></tr>"
)
_ECC_ROW = (
    "<tr><td>&nbsp;</td><td><p class=text>{}</p></td><td>&nbsp;</td><td><p class=text>{}</p></td>"
    "<td>&nbsp;</td><td><p class=text>{}</p></td></tr>"
)


def test_ecc_legacy_page_refusals() -> None:
    row = _ECC_ROW.format("A SCHOOL", "CHICAGO", "(TODAY) CLOSED")
    more = _ECC_ROW.format("&nbsp;", "&nbsp;", "(TOMORROW) CLOSED")
    good = ecc.parse((_ECC_HEAD + row + more + "</table></body></html>").encode())
    assert [(r.name, r.status, r.extra["status_lines"]) for r in good.rows] == [
        ("A SCHOOL", "(TODAY) CLOSED | (TOMORROW) CLOSED", 2)
    ]
    assert good.rows[0].updated_text == "11:50 PM, CST"
    with pytest.raises(ShapeError, match="no facility above it"):
        ecc.parse((_ECC_HEAD + more + row + "</table>").encode())
    with pytest.raises(ShapeError, match="empty form is unseen"):
        ecc.parse((_ECC_HEAD + "</table>").encode())
    with pytest.raises(ShapeError, match="not closed"):  # a capture cut off mid-table
        ecc.parse((_ECC_HEAD + row).encode())
    with pytest.raises(ShapeError, match="facility, city and status"):
        ecc.parse((_ECC_HEAD + "<tr><td>A</td></tr></table>").encode())
    with pytest.raises(ShapeError, match="heading"):
        ecc.parse((_ECC_HEAD.replace("<p>City</p>", "<p>Town</p>") + row + "</table>").encode())
    # The old home page carries the same table below a search form whose own
    # "Facility Name:" label is a form cell, not the table's heading.
    form = (
        '<form><table><tr><td class=try nowrap>Facility Name: </td><td><input name="n">'
        "</td></tr></table></form>"
    )
    home = _ECC_HEAD.replace("ECC: Status Search", "ECC: Home").replace(
        "<p class=", form + "<p class=", 1
    )
    listed = ecc.parse((home + row + more + "</table></body></html>").encode())
    assert (listed.variant, [r.name for r in listed.rows]) == ("ecc-legacy-page", ["A SCHOOL"])
    with pytest.raises(ShapeError, match="not the legacy ECC page"):
        ecc.slice_legacy_page(b"<html><title>ECC: Status Search</title></html>")


def test_fixture_tool_commands(tmp_path: Path) -> None:
    folder = tmp_path / "fixtures"
    # A synthetic capture log over a real live body.
    body = (FIXTURES / "fox-owned/wjbk-page-live-20260927013834.html").read_bytes()
    log = tmp_path / "log"
    log.mkdir()
    (log / "page.body").write_bytes(body)
    record = {
        "url": "https://www.fox2detroit.com/closings",
        "fetched_at": "2026-09-27T01:38:34Z",
        "sha256": hashlib.sha256(body).hexdigest(),
        "file": "page.body",
    }
    (log / network_fixtures.LOG_FILE).write_text(json.dumps(record) + "\n", encoding="utf-8")
    common = ["--folder", str(folder)]
    assert (
        network_fixtures.main(
            [
                *common,
                "add",
                "--log",
                str(log / network_fixtures.LOG_FILE),
                "--url",
                record["url"],
                "--file",
                "fox-owned/wjbk-page.html",
                "--source",
                "fox-owned-wjbk",
                "--adapter",
                "fox-owned",
                "--slice",
                "fox-page-v1",
            ]
        )
        == 0
    )
    # A synthetic manifest over a real archived body.
    archived = (FIXTURES / "cbs-owned/wnem-sc-20201210023135.xml").read_bytes()
    snapshots = tmp_path / "artifacts" / "run" / "snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / "a.body").write_bytes(archived)
    url = "https://lmgcorporate.com/closings/wnem/schools.xml"
    line = {
        "timestamp": "20201210000000",
        "url": url,
        "requested": "x",
        "final_timestamp": "20201210023135",
        "final_original": url,
        "retrieved_at": "2026-09-26T02:30:44Z",
        "file": "snapshots/a.body",
        "sha256": hashlib.sha256(archived).hexdigest(),
    }
    (snapshots / "manifest.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    args = ["--timestamp", "20201210000000", "--url", url, "--file", "cbs-owned/wnem.xml"]
    source = ["--source", "gray-wnem", "--adapter", "cbs-owned"]
    artifacts = ["--artifacts", str(tmp_path / "artifacts")]
    assert network_fixtures.main([*common, "add-archived", *artifacts, *args, *source]) == 0
    entries = network_fixtures.load_entries(folder)
    assert [(e.file, e.expected.state) for e in entries] == [
        ("cbs-owned/wnem.xml", ListingState.POPULATED),
        ("fox-owned/wjbk-page.html", ListingState.DEFERRED),
    ]
    assert entries[0].archive_url == (f"https://web.archive.org/web/20201210023135id_/{url}")
    assert network_fixtures.main([*common, "readme"]) == 0
    # A capture that is not there, and a body that no longer matches its checksum.
    missing = ["--timestamp", "20201210000001", "--url", url, "--file", "cbs-owned/x.xml"]
    assert network_fixtures.main([*common, "add-archived", *artifacts, *missing, *source]) == 1
    (snapshots / "a.body").write_bytes(archived + b" ")
    assert network_fixtures.main([*common, "add-archived", *artifacts, *args, *source]) == 1


def test_slicers_refuse_pages_without_their_parts() -> None:
    with pytest.raises(ShapeError):
        network_fixtures.slice_fox_page(b"<html><iframe src='https://x/video'></iframe></html>")
    with pytest.raises(ShapeError):
        network_fixtures.slice_cbs_page(b"<html><body>nothing</body></html>")


def test_cbs_shorter_export_refusals() -> None:
    feed = (FIXTURES / "cbs-owned/wwj-feed-20260119143100.xml").read_bytes()
    wrong = feed.replace(b"<NUM_CLOSINGS>7</NUM_CLOSINGS>", b"<NUM_CLOSINGS>8</NUM_CLOSINGS>")
    with pytest.raises(ShapeError, match="NUM_CLOSINGS is 8"):
        cbs_owned.parse(wrong)
    stray = feed.replace(b"<RUN_EPOCH>", b"<OTHER>x</OTHER><RUN_EPOCH>")
    with pytest.raises(ShapeError, match="holds a <OTHER>"):
        cbs_owned.parse(stray)
    no_status = feed.replace(b"<FORCED_STATUS_NAME>Closed </FORCED_STATUS_NAME>", b"", 1)
    with pytest.raises(ShapeError, match="no FORCED_STATUS_NAME"):
        cbs_owned.parse(no_status)
