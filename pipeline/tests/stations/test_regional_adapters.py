"""Error handling and edge cases of part 3b's adapters, on small synthetic bodies.

Every body in this file is SYNTHETIC: written here, in the shape the module docstrings
describe, to exercise one rule (a refusal, a row layout, a count check). Real bodies,
live and archived, are the fixtures in fixtures/regional/ (test_regional_fixtures.py).
"""

import base64
import gzip
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from snowlight.sources.stations import (
    allen,
    blox,
    cox,
    delaware,
    eventdelay,
    graham,
    heritage,
    hubbard,
    lockwood,
    ncpr,
    news12,
    newsticker,
    regional,
    sinclair,
    spectrum,
    townsquare,
    weatherthreat,
    whdh,
    wral,
    wtop,
    wveis,
)
from snowlight.sources.stations.model import Listing, ListingState, ShapeError

FIXTURES = Path(__file__).parent / "fixtures" / "regional"

SYNTHETIC_NEWSTICKER = (
    b'<P><TABLE><TR><TD CLASS="timestamp">UPDATED MONDAY, JAN 6 AT  5:40 AM</TD></TR>'
    b'<TR><TD CLASS="orgname" COLSPAN=2><B>PUBLIC SCHOOLS</B></TD></TR>'
    b'<TR><TD><FONT CLASS="orgname">Synthetic County Schools</FONT>: '
    b'<FONT CLASS="status">Closed</FONT></TD></TR>'
    b'<TR><TD><FONT CLASS="status">Springfield</FONT></TD><TD><FONT CLASS="orgname">'
    b'Synthetic Academy&nbsp;[<a href="http://example.invalid" target=_new>WEB</A>]</FONT>: '
    b'<FONT CLASS="status">2 Hours Late</FONT></TD></TR></TABLE>'
)


def test_newsticker_reads_groups_towns_and_web_links() -> None:
    listing = newsticker.parse(SYNTHETIC_NEWSTICKER)
    assert listing.variant == "newsticker-html"
    assert [(r.name, r.status) for r in listing.rows] == [
        ("Synthetic County Schools", "Closed"),
        ("Synthetic Academy", "2 Hours Late"),
    ]
    first, second = listing.rows
    assert first.updated_text == "UPDATED MONDAY, JAN 6 AT 5:40 AM"
    assert first.extra == {"updated_scope": "page", "group": "PUBLIC SCHOOLS"}
    assert second.extra["location"] == "Springfield"
    assert second.extra["homepage"] == "http://example.invalid"
    # An archived copy still gzip-encoded reads the same.
    assert newsticker.parse(gzip.compress(SYNTHETIC_NEWSTICKER)) == listing


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            SYNTHETIC_NEWSTICKER.replace(
                b"</TABLE>",
                b'<TR><TD CLASS="status">There are no active records at this time.'
                b"</TD></TR></TABLE>",
            ),
            "says there are no records",
        ),
        (
            b'<TABLE><TR><TD CLASS="timestamp">UPDATED</TD></TR><TR><TD>Something else</TD></TR>'
            b'<TR><TD><FONT CLASS="orgname">X</FONT></TD></TR></TABLE>',
            "neither a heading nor a listing",
        ),
        (
            b'<TABLE><TR><TD CLASS="timestamp">UPDATED</TD></TR><TR><TD><FONT CLASS="orgname">A'
            b'</FONT> <FONT CLASS="orgname">B</FONT></TD></TR></TABLE>',
            "more than one orgname",
        ),
    ],
)
def test_newsticker_refuses_contradictions(body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        newsticker.parse(body)


def test_closings_grid_rows_headings_and_refusals() -> None:
    grid = (
        b'<table width="100%">Closings Last Updated at 6:02am on 1/06/2025<br>'
        b'<tr><td colspan="3"><b>ATLANTIC</b></td></tr>'
        b'<tr><td width="33%"><b>Synthetic Schools&nbsp;</b></td><td>Closed&nbsp;</td>'
        b"<td>No activities</td></tr></table>"
    )
    listing = newsticker.parse(grid)
    assert listing.variant == "closings-grid"
    assert listing.rows[0].extra == {
        "updated_scope": "page",
        "group": "ATLANTIC",
        "comment": "No activities",
    }
    assert listing.rows[0].updated_text == "6:02am on 1/06/2025"
    with pytest.raises(ShapeError, match="2 cells"):
        newsticker.parse(grid.replace(b"<td>No activities</td>", b""))
    with pytest.raises(ShapeError, match="bold"):
        newsticker.parse(b"Closings Last Updated at 1am<table><tr><td>x</td></tr></table>")
    with pytest.raises(ShapeError, match="no rows and no"):
        newsticker.parse(b"Closings Last Updated at 1am on 1/1/2025<br><table></table>")
    with pytest.raises(ShapeError, match="neither"):
        newsticker.parse(b"<html>nothing</html>")


def test_sinclair_chameleon_answers_and_pages() -> None:
    answer = {
        "closingGroup": {
            "closingList": [
                {
                    "id": 7,
                    "name": "SYNTHETIC",
                    "institution_name": "Synthetic School District",
                    "statusName": "Closed",
                    "lastModified": "2025-01-06T11:00:00Z",
                    "group": "Schools",
                },
                {"id": 8, "name": "Synthetic Church", "statusName": "Services canceled"},
            ]
        }
    }
    listing = sinclair.parse(json.dumps(answer).encode())
    assert listing.variant == "chameleon-json"
    assert [(r.name, r.status) for r in listing.rows] == [
        ("Synthetic School District", "Closed"),
        ("Synthetic Church", "Services canceled"),
    ]
    assert listing.rows[0].extra == {"id": 7, "name": "SYNTHETIC", "group": "Schools"}
    assert listing.rows[0].updated_text == "2025-01-06T11:00:00Z"
    assert sinclair.parse(b'{"generated": "x", "bladeQueryItem": []}').state is ListingState.EMPTY
    with pytest.raises(ShapeError, match="statusName"):
        sinclair.parse(b'{"bladeQueryItem": [{"name": "x"}]}')
    with pytest.raises(ShapeError, match="neither"):
        sinclair.parse(b'{"other": []}')
    address = base64.b64encode(b"https://ticker.example.invalid/q?format=json").decode()
    page = f"<title>Closings Display</title><script>const jsonUrl = atob('{address}');</script>"
    assert sinclair.parse(page.encode()).follows == (
        "https://ticker.example.invalid/q?format=json",
    )
    bad = base64.b64encode(b"http://insecure.invalid/").decode()
    with pytest.raises(ShapeError, match="https"):
        sinclair.parse(f"<title>Closings Display</title>const jsonUrl = atob('{bad}')".encode())
    with pytest.raises(ShapeError, match="frames no list"):
        sinclair.parse(b'<div>NewsCustomPage_htmlEmbed__x\\",\\"html\\":\\"\\"</div>')
    older = b'<html><iframe src="https://x.invalid/resources/ftptransfer/abcd/closings/a.html">'
    assert sinclair.parse(older).variant == "sinclair-frame-page"
    with pytest.raises(ShapeError):
        sinclair.parse(b"")
    with pytest.raises(ShapeError, match="page shell"):
        sinclair.parse(b'<script>sinclairDigital.siteSlug = "abcd";</script>')


def test_sinclair_page_shell_reads_the_frame_in_its_injected_markup() -> None:
    # As the 2025 page shells write it: the facade's iframe presentation carries its
    # markup base64-encoded; a sign-up frame may come before the list file's.
    markup = (
        '<a href="/weather/submit-a-closing">Report</a>'
        '<iframe src="https://forms.invalid/closings"></iframe>'
        '<iframe src="/resources/ftptransfer/abcd/closings/closings.htm"></iframe>'
    )
    encoded = base64.b64encode(markup.encode()).decode()
    shell = (
        '<script>sinclairDigital.siteSlug = "abcd";\nsinclairDigital.facade = {"a":'
        '{"data":{"injectedMarkup":""}},"b":{"data":{"injectedMarkup":"'
        + encoded
        + '"}}};</script>'
    ).encode()
    listing = sinclair.parse(shell)
    assert (listing.variant, listing.state) == ("sinclair-facade-page", ListingState.DEFERRED)
    assert listing.follows == ("/resources/ftptransfer/abcd/closings/closings.htm",)
    sliced = sinclair.slice_body(shell)
    assert sinclair.parse(sliced) == listing
    assert sinclair.slice_body(sliced) == sliced
    only_form = base64.b64encode(b'<iframe src="https://forms.invalid/c"></iframe>').decode()
    form_shell = f'sinclairDigital.siteSlug = "x"; "injectedMarkup":"{only_form}"'.encode()
    assert sinclair.parse(form_shell).follows == ("https://forms.invalid/c",)
    with pytest.raises(ShapeError, match="does not decode"):
        sinclair.parse(b'sinclairDigital.siteSlug = "x"; "injectedMarkup":"AAA"')
    with pytest.raises(ShapeError, match="frames no list"):
        sinclair.parse(b'sinclairDigital.siteSlug = "x"; "injectedMarkup":"PGI+PC9iPg=="')
    # As the 2022 shells write it: the markup as a plain JSON string.
    plain = (
        b'sinclairDigital.siteSlug = "x"; {"data":{"injectedMarkup":"<p>Report</p>'
        b'<iframe src=\\"\\/resources\\/ftptransfer\\/abcd\\/closings\\/closings.html\\">'
        b'<\\/iframe>"}}'
    )
    assert sinclair.parse(plain).follows == ("/resources/ftptransfer/abcd/closings/closings.html",)
    assert sinclair.parse(sinclair.slice_body(plain)) == sinclair.parse(plain)
    with pytest.raises(ShapeError, match="not a JSON string"):
        sinclair.parse(b'sinclairDigital.siteSlug = "x"; "injectedMarkup":"unterminated')


def test_sinclair_embed_as_a_server_stream_reference() -> None:
    # As WCTI's page of 2026 writes it: the embed's html is "$14", a text chunk of the
    # page's React Server Components stream, which comments out an older frame and
    # frames a sign-up form before the list file.
    html = (
        '<!-- <iframe src="https://old.invalid/SchoolClosings.htm"></iframe> -->'
        '<iframe src="https://forms.invalid/s/closings?client=x"></iframe>'
        '<iframe src="/resources/ftptransfer/abcd/closings/closings.html"></iframe>'
    )
    head = json.dumps(
        '5:["$","$L13",null,{"className":"NewsCustomPage_htmlEmbed__x","html":"$14"}]'
    )
    chunk = json.dumps(f"\n14:T{len(html.encode()):x},{html}")
    page = (
        f"<script>self.__next_f.push([1,{head}])</script>"
        f"<script>self.__next_f.push([1,{chunk}])</script>"
    ).encode()
    listing = sinclair.parse(page)
    assert (listing.variant, listing.follows) == (
        "sinclair-next-page",
        ("/resources/ftptransfer/abcd/closings/closings.html",),
    )
    sliced = sinclair.slice_body(page)
    assert sinclair.slice_body(sliced) == sliced
    assert sinclair.parse(sliced).follows == listing.follows
    with pytest.raises(ShapeError, match="which it lacks"):
        sinclair.parse(page.replace(b"14:T", b"15:T"))
    short = json.dumps(f"\n14:T{len(html.encode()) + 5:x},{html}")
    with pytest.raises(ShapeError, match="cut short"):
        sinclair.parse(page.replace(chunk.encode(), short.encode()))


def test_allen_counter_header_table_and_cgs() -> None:
    counter = b'{"title":"t","station":"KWWL","closingsURL":"u","numClosings":"12"}'
    listing = allen.parse(counter)
    assert (listing.state, listing.declared_count) == (ListingState.COUNT_ONLY, 12)
    with pytest.raises(ShapeError, match="not a count"):
        allen.parse(counter.replace(b'"12"', b'"a"'))
    with pytest.raises(ShapeError, match="not an Allen"):
        allen.parse(b'{"numClosings": 1}')
    # KIMT's populated layout (as captured 2026-03-17): a blank row, the time, the
    # column heads, then one row per organization.
    table = (
        b'<table><tr><td align="center"></td></tr>'
        b"<tr><th colspan=\"2\" bgcolor='999999'>January 6, 2025 5:10 am CST</th></tr>"
        b"<tr><th>&nbsp;Location</th><th>&nbsp;Status<BR></th></tr>"
        b"<tr><td>&nbsp;Synthetic Community Schools</td><td>&nbsp;Closed<BR></td></tr>"
        b"</table>"
    )
    rows = allen.parse(table).rows
    assert [(r.name, r.status, r.updated_text, r.extra) for r in rows] == [
        (
            "Synthetic Community Schools",
            "Closed",
            "January 6, 2025 5:10 am CST",
            {"updated_scope": "page"},
        )
    ]
    with pytest.raises(ShapeError, match="not 2"):
        allen.parse(table.replace(b"<td>&nbsp;Closed<BR></td>", b""))
    with pytest.raises(ShapeError, match="heading not seen before"):
        allen.parse(
            table.replace(b"<tr><td>&nbsp;Synthetic", b"<tr><th>SCHOOLS</th></tr><tr><td>S")
        )
    cgs = (
        b'<meta http-equiv="Created by CGS Infographics Automation"/><div class="msg">T</div>'
        b'<div class="msg">1/6/2025 5:00 AM</div><table class="tablenoborder"><tr>'
        b"<td class=\"msg\">There are no 'All Active' closings to report.</td></tr></table>"
    )
    assert allen.parse(cgs).state is ListingState.EMPTY
    assert sinclair.parse(cgs).variant == "cgs-all-active"
    # KIMT's populated layout (captures of 2020 to 2024): a table of category links,
    # then one table.tableborder per entry, its cells cat, org and sts (or their dark
    # alternates).
    entry = (
        b'<table class="tablenoborder"><tr><td class="links"><A HREF=#Schools>Schools</A>'
        b'</td></tr></table><table class="tableborder"><tr><td class="catdark">Schools</td>'
        b'<td class="orgdark">Synthetic School</td><td class="stsdark">Delayed</td></tr></table>'
    )
    listed = cgs.replace(
        b'<table class="tablenoborder"><tr>'
        b"<td class=\"msg\">There are no 'All Active' closings to report.</td></tr></table>",
        entry,
    )
    assert [(r.name, r.status, r.updated_text, r.extra) for r in allen.parse(listed).rows] == [
        (
            "Synthetic School",
            "Delayed",
            "1/6/2025 5:00 AM",
            {"category": "Schools", "updated_scope": "page"},
        )
    ]
    with pytest.raises(ShapeError, match="not \\('cat', 'org', 'sts'\\)"):
        allen.parse(listed.replace(b'class="stsdark"', b'class="sts2"'))
    with pytest.raises(ShapeError, match="navigation table"):
        allen.parse(listed.replace(b'class="links"', b'class="msg"'))
    with pytest.raises(ShapeError, match="a table of class"):
        allen.parse(listed.replace(b'class="tableborder"', b'class="other"'))
    with pytest.raises(ShapeError, match="neither entries nor its empty sentence"):
        allen.parse(
            cgs.replace(
                b"<td class=\"msg\">There are no 'All Active' closings to report.</td>",
                b'<td class="links">Schools</td>',
            )
        )


def test_heritage_closings_and_its_older_table() -> None:
    with pytest.raises(ShapeError, match="no status"):
        heritage.parse(b'{"lastUpdated":"x","closing":[{"a":1}]}')
    with pytest.raises(ShapeError, match="not seen before"):
        heritage.parse(b'{"lastUpdated":"x","closings":[]}')
    with pytest.raises(ShapeError, match="not a list"):
        heritage.parse(b'{"lastUpdated":"x","closing":{}}')
    with pytest.raises(ShapeError, match="not an object"):
        heritage.parse(b'{"lastUpdated":"x","closing":[1]}')
    closing = {"name1": "Synthetic Public", "name2": "", "status": "Closed", "status2": "Code 1"}
    item = heritage.parse(
        json.dumps(
            {"lastUpdated": "x", "closing": [closing | {"updatetime": "01/06/2025"}]}
        ).encode()
    ).rows[0]
    assert (item.name, item.status, item.updated_text, item.extra) == (
        "Synthetic Public",
        "Closed",
        "01/06/2025",
        {"name2": "", "status2": "Code 1"},
    )
    empty_list = heritage.parse(b'{"lastUpdated":"x","closing":[],"_id":"y"}')
    assert empty_list.state is ListingState.EMPTY
    table = (
        b'<table class="bti_closings"><tbody><tr><td class="location"><span class="location_name">'
        b'Synthetic Public</span><span class="location_type">Districts</span></td>'
        b'<td class="address"> </td><td class="status"><span class="status_desc">Closed</span>'
        b'<span class="last_updated" title="01/06/2025 05:00am">Updated 1 hour ago</span></td>'
        b"</tr></tbody></table>"
    )
    listed = heritage.parse(table)
    assert [(r.name, r.status, r.updated_text, r.extra) for r in listed.rows] == [
        (
            "Synthetic Public",
            "Closed",
            "01/06/2025 05:00am",
            {"location_type": "Districts", "updated_label": "Updated 1 hour ago"},
        )
    ]
    with pytest.raises(ShapeError, match="without rows"):
        heritage.parse(b'<table class="bti_closings"><tbody></tbody></table>')
    with pytest.raises(ShapeError, match=r"0 span\.status_desc"):
        heritage.parse(table.replace(b"status_desc", b"other"))


def test_arc_sources_read_seen_rows_and_refuse_unseen_ones() -> None:
    cox_answer = {
        "totalClosings": 2,
        "closings": [
            {
                "response": {
                    "name": "Synthetic Schools",
                    "county": "Fulton",
                    "status": "Closed Today",
                }
            },
            {
                "response": {
                    "name": "Synthetic Daycare",
                    "status": "",
                    "status_code_display": "Other",
                }
            },
        ],
        "_id": "a",
    }
    listing = cox.parse(json.dumps(cox_answer).encode())
    assert [(r.name, r.status, r.updated_text, r.extra) for r in listing.rows] == [
        ("Synthetic Schools", "Closed Today", None, {"county": "Fulton"}),
        ("Synthetic Daycare", "Other", None, {"status_code_display": "Other"}),
    ]
    with pytest.raises(ShapeError, match="not been seen"):
        cox.parse(b'{"totalClosings":1,"closings":[{"name":"x"}],"_id":"a"}')
    with pytest.raises(ShapeError, match="not been seen"):
        cox.parse(b'{"totalClosings":1,"closings":[{"response":{"name":"x","status":"y","z":1}}]}')
    with pytest.raises(ShapeError, match="counts 3"):
        cox.parse(json.dumps(cox_answer | {"totalClosings": 3}).encode())
    with pytest.raises(ShapeError, match="count"):
        cox.parse(b'{"totalClosings":"1","closings":[]}')
    school = {
        "id": "1",
        "name_one": "Synthetic Academy",
        "category": "Schools",
        "status_name_one": "Closed",
        "status_two_name_one": None,
        "updated": "2025-01-06 11:00:00",
    }
    answer = {"schools": [school], "timestamp": 1, "time_from_origin": "Monday 6:00 AM EST"}
    row = graham.parse(json.dumps(answer).encode()).rows[0]
    assert (row.name, row.status, row.updated_text) == (
        "Synthetic Academy",
        "Closed",
        "2025-01-06 11:00:00",
    )
    assert row.extra == {
        "id": "1",
        "category": "Schools",
        "status_two_name_one": None,
        "updated_zone": "UTC",
    }
    undated = {**answer, "schools": [school | {"updated": None}]}
    row = graham.parse(json.dumps(undated).encode()).rows[0]
    assert (row.updated_text, "updated_zone" in row.extra) == ("Monday 6:00 AM EST", False)
    with pytest.raises(ShapeError, match="not been seen"):
        graham.parse(b'{"schools":[{"name":"x"}],"timestamp":1}')
    with pytest.raises(ShapeError, match="not been seen"):
        graham.parse(json.dumps({**answer, "schools": [school | {"extra": 1}]}).encode())
    with pytest.raises(ShapeError, match="timestamp"):
        graham.parse(b'{"schools":[]}')
    page = (
        b'<script>Fusion.contentCache={"closing":{"undefined":{"data":'
        b'{"totalClosings":0,"closings":[]},"lastModified":1736150400000}}};</script>'
    )
    listing = cox.parse(page)
    assert listing.variant == "cox-arc-page"
    assert listing.declared_at is not None
    assert listing.declared_at.isoformat() == "2025-01-06T08:00:00+00:00"
    with pytest.raises(ShapeError, match="not JSON"):
        cox.parse(b"<script>Fusion.contentCache={broken</script>")
    with pytest.raises(ShapeError, match="no closing content"):
        cox.parse(b'<script>Fusion.contentCache={"other":{}};</script>')


def test_json_list_files() -> None:
    raven = [
        {"orgType": "Schools", "closings": [{"accountName": "Synthetic CSD", "status": "Closed"}]}
    ]
    row = spectrum.parse(json.dumps(raven).encode()).rows[0]
    assert (row.name, row.status, row.extra) == ("Synthetic CSD", "Closed", {"orgType": "Schools"})
    with pytest.raises(ShapeError, match="no status"):
        spectrum.parse(b'[{"orgType":"S","closings":[{"accountName":"x"}]}]')
    api = {
        "count": 1,
        "closings": [
            {
                "orgDisplayName": "Synthetic Schools",
                "orgName": "SYN",
                "statusText": "Closed",
                "county": "Wake",
            }
        ],
    }
    row = wral.parse(json.dumps(api).encode()).rows[0]
    assert (row.name, row.status, row.extra["county"], row.extra["orgName"]) == (
        "Synthetic Schools",
        "Closed",
        "Wake",
        "SYN",
    )
    with pytest.raises(ShapeError, match="counts 2"):
        wral.parse(json.dumps({**api, "count": 2}).encode())
    export = [
        {
            "record": [
                {
                    "organization_name": "Synthetic County",
                    "status_name": "Closed",
                    "status_name_2": "Staff report",
                    "category_name": "Schools",
                }
            ],
            "num_closings": 1,
            "run_date": "01-06-2025 at 05:00 am",
        }
    ]
    row = lockwood.parse(json.dumps(export).encode()).rows[0]
    assert (row.name, row.status) == ("Synthetic County", "Closed, Staff report")
    assert row.extra == {"category_name": "Schools", "updated_scope": "page"}
    with pytest.raises(ShapeError, match="one export"):
        lockwood.parse(b"[]")


def test_state_feeds() -> None:
    feed = (
        b"<rows><page>1</page><records>1</records><lastModified>1/6/2025 5:00 AM</lastModified>"
        b'<row id="3"><cell>Synthetic SD</cell><cell>Closed</cell><cell>Synthetic</cell>'
        b"<cell>1/6/2025</cell></row></rows>"
    )
    row = delaware.parse(feed).rows[0]
    assert (row.name, row.status, row.updated_text) == (
        "Synthetic SD",
        "Closed",
        "1/6/2025 5:00 AM",
    )
    assert row.extra == {
        "district": "Synthetic",
        "note": "1/6/2025",
        "id": "3",
        "updated_scope": "page",
    }
    stamped = feed.replace(
        b"<lastModified>1/6/2025 5:00 AM</lastModified>", b"<timestamp>t</timestamp>"
    )
    assert delaware.parse(stamped).rows[0].updated_text == "t"
    page = (
        b"<script>jQuery('#list1').jqGrid({datatype: function () { jQuery.ajax({"
        b"url: '/XML/PortalFeed',"
    )
    assert delaware.parse(page).follows == ("/XML/PortalFeed",)
    with pytest.raises(ShapeError, match="names no PortalFeed"):
        delaware.parse(b"<script>jQuery('#list1').jqGrid({url: '/other'})</script>")
    with pytest.raises(ShapeError, match="counts 2"):
        delaware.parse(feed.replace(b"<records>1", b"<records>2"))
    # Cells are read by position, as the page's grid reads them: a row without the
    # fourth cell has no note, and cells past the fourth are kept, numbered.
    short = delaware.parse(feed.replace(b"<cell>1/6/2025</cell>", b"")).rows[0]
    assert (short.name, short.status, short.extra) == (
        "Synthetic SD",
        "Closed",
        {"district": "Synthetic", "id": "3", "updated_scope": "page"},
    )
    longer = feed.replace(
        b"<cell>1/6/2025</cell>",
        b"<cell>1/6/2025</cell><cell>https://example.invalid/1.xml</cell><cell>x</cell>",
    )
    assert delaware.parse(longer).rows[0].extra == {
        "district": "Synthetic",
        "note": "1/6/2025",
        "cell_5": "https://example.invalid/1.xml",
        "cell_6": "x",
        "id": "3",
        "updated_scope": "page",
    }
    # A note that is an RFC 2822 date is the row's own time; the list's is kept.
    dated = delaware.parse(
        feed.replace(b"<cell>1/6/2025</cell>", b"<cell>Mon, 06 Jan 2025 04:12:00 GMT</cell>")
    ).rows[0]
    assert (dated.updated_text, dated.extra["updated_scope"], dated.extra["list_updated"]) == (
        "Mon, 06 Jan 2025 04:12:00 GMT",
        "row",
        "1/6/2025 5:00 AM",
    )
    unstamped = feed.replace(b"<lastModified>1/6/2025 5:00 AM</lastModified>", b"<timestamp/>")
    assert delaware.parse(unstamped).rows[0].updated_text is None
    assert "updated_scope" not in delaware.parse(unstamped).rows[0].extra
    with pytest.raises(ShapeError, match="fewer than 2"):
        delaware.parse(b"<rows><records>1</records><row><cell>Synthetic SD</cell></row></rows>")
    with pytest.raises(ShapeError, match="holds a <b>"):
        delaware.parse(feed.replace(b"<cell>1/6/2025</cell>", b"<b>1/6/2025</b>"))
    assert (
        delaware.parse(feed.replace(b"<cell>Closed</cell>", b"<cell>" + b"x" * 2500 + b"</cell>"))
        .rows[0]
        .status
        == "x" * 1999 + "\u2026"
    )
    with pytest.raises(ShapeError, match="does not parse"):
        delaware.parse(b"<rows>")
    rss = (
        b'<?xml version="1.0"?><rss><channel><item><title>All schools in Synthetic County</title>'
        b"<link>https://example.invalid/county.php?id=1</link>"
        b"<description><![CDATA[As of Jan 6, 5:00am: Closed.]]></description>"
        b"<pubDate>Mon, 06 Jan 2025 05:00:00 -0500</pubDate><guid>7-1</guid></item>"
        b"</channel></rss>"
    )
    posting = wveis.parse(rss).rows[0]
    assert (posting.name, posting.status, posting.updated_text) == (
        "All schools in Synthetic County",
        "As of Jan 6, 5:00am: Closed.",
        "Mon, 06 Jan 2025 05:00:00 -0500",
    )
    assert posting.extra == {"link": "https://example.invalid/county.php?id=1", "guid": "7-1"}
    with pytest.raises(ShapeError, match="without a title or description"):
        wveis.parse(
            rss.replace(b"<description><![CDATA[As of Jan 6, 5:00am: Closed.]]></description>", b"")
        )
    nothing = (
        b"<item><title>No closings to report</title><description>Nothing to report</description>"
        b"</item>"
    )
    with pytest.raises(ShapeError, match="also posts"):
        wveis.parse(rss.replace(b"</channel>", nothing + b"</channel>"))
    with pytest.raises(ShapeError, match="no item"):
        wveis.parse(b"<rss><channel></channel></rss>")
    with pytest.raises(ShapeError, match="not plain text"):
        wveis.parse(rss.replace(b"<guid>7-1</guid>", b"<guid><b>7</b></guid>"))


def test_pages_with_their_own_lists() -> None:
    table = (
        b'<table id="table_header"><tr><td>Today Mon Jan 6, 2025</td><td>Tomorrow</td></tr>'
        b"</table>"
        b'<table id="table-reflow"><thead><tr><th>Name</th><th>City</th><th>Status</th></tr>'
        b"</thead>"
        b'<tbody><tr df="1"><td><div>Synthetic Library</div></td><td>Mineola</td>'
        b"<td>Closed<span></span></td></tr></tbody></table>"
    )
    row = news12.parse(table).rows[0]
    assert row.extra == {"city": "Mineola", "day": "tomorrow", "day_label": "Tomorrow"}
    with pytest.raises(ShapeError, match="no known tab"):
        news12.parse(table.replace(b'df="1"', b'df="9"'))
    notice = (
        b'<div class="wp-block-school-closings"><article class="closure-notice">'
        b'<div class="closure-header">Public Schools \xe2\x80\x93 Updated: 2025-01-06 05:00:00'
        b"</div>"
        b'<h3 class="entry-title">Synthetic Public Schools</h3><div class="current-status">Closed'
        b'</div><div class="status-expiration">2025-01-06 23:00:00</div></article></div>'
    )
    row = whdh.parse(notice).rows[0]
    assert (row.name, row.status, row.updated_text) == (
        "Synthetic Public Schools",
        "Closed",
        "2025-01-06 05:00:00",
    )
    assert row.extra == {"category": "Public Schools", "expiration": "2025-01-06 23:00:00"}
    with pytest.raises(ShapeError, match="no notice"):
        whdh.parse(b'<div class="wp-block-school-closings"></div>')
    posting = {
        "status": "Closed on Monday 1/6",
        "note": "",
        "post_title": "Synthetic County Public Schools: Closed Monday",
        "post_modified_gmt": "2025-01-06 00:38:40",
        "org": {"term_id": 1, "name": "Synthetic County Public Schools", "city": "Town"},
    }
    placeholder = posting | {"org": {"term_id": "X", "name": "Unknown", "state": "XX"}}
    states = {
        "VA": {"name": "Virginia", "categories": {"Public Schools": [posting]}},
        "XX": {"name": "Unknown", "categories": {"None": [placeholder]}},
    }
    page = f"<script>Site.closings_by_state = {json.dumps(states)};</script>".encode()
    listing = wtop.parse(page)
    assert (listing.state, listing.skipped_rows) == (ListingState.POPULATED, 1)
    row = listing.rows[0]
    assert (row.name, row.status, row.updated_text) == (
        "Synthetic County Public Schools",
        "Closed on Monday 1/6",
        "2025-01-06 00:38:40",
    )
    assert row.extra == {
        "state_code": "VA",
        "state_name": "Virginia",
        "category": "Public Schools",
        "updated_zone": "UTC",
        "post_title": "Synthetic County Public Schools: Closed Monday",
        "note": "",
        "org_term_id": 1,
        "org_city": "Town",
    }
    assert wtop.slice_body(wtop.slice_body(page)) == wtop.slice_body(page)
    unseen = {"MD": {"name": "Maryland", "categories": {"x": [{"org": {}}]}}}
    with pytest.raises(ShapeError, match="not been seen before"):
        wtop.parse(f"Site.closings_by_state = {json.dumps(unseen)};".encode())
    with pytest.raises(ShapeError, match="no organization"):
        wtop.parse(
            b'Site.closings_by_state = {"MD": {"name": "Maryland", "categories": {"x": [{}]}}};'
        )
    with pytest.raises(ShapeError, match="neither an empty list nor an object"):
        wtop.parse(b'Site.closings_by_state = [{"state":"MD"}];')
    with pytest.raises(ShapeError, match="no-closings"):
        wtop.parse(b"Site.closings_by_state = [];")
    alert = (
        b'<p class="lastUpdated">Last updated: 2025-01-06 05:00:00</p>'
        b'<div class="everyOther p-2"><strong>SYNTHETIC PUBLIC SCHOOLS</strong><br />'
        b"Closed Monday </div><p>&nbsp;</p><style>p.lastUpdated { font-size: 0.75rem; }</style>"
    )
    assert [(r.name, r.status, r.updated_text) for r in hubbard.parse(alert).rows] == [
        ("SYNTHETIC PUBLIC SCHOOLS", "Closed Monday", "2025-01-06 05:00:00")
    ]
    with pytest.raises(ShapeError, match="not seen before"):
        hubbard.parse(b'<p class="lastUpdated">Last updated: x</p><p class="everyOther">A</p>')
    with pytest.raises(ShapeError, match="2 names"):
        hubbard.parse(alert.replace(b"<br />", b"<strong>x</strong>"))
    with pytest.raises(ShapeError, match="does not start with its name"):
        hubbard.parse(alert.replace(b"<strong>", b"x<strong>"))
    nothing = b"<p>There are currently no reported closings.</p>"
    with pytest.raises(ShapeError, match="says there are none"):
        hubbard.parse(alert.replace(b"<p>&nbsp;</p>", nothing))
    with pytest.raises(ShapeError, match="no rows and no"):
        hubbard.parse(b'<p class="lastUpdated">Last updated: x</p><p>&nbsp;</p>')
    old_page = b'<html><iframe src="/wp-content/uploads/wx/schoolalert.html" style="x"></iframe>'
    assert hubbard.parse(old_page).follows == ("/wp-content/uploads/wx/schoolalert.html",)
    assert hubbard.parse(hubbard.slice_body(old_page)).variant == "hubbard-frame-page"
    with pytest.raises(ShapeError, match="display mode"):
        eventdelay.parse(
            b'<body class="widget widget-channel"><div id="body"><h3 class="date-label">Mon</h3>'
            b"<table><tr><td>Synthetic</td></tr></table></div></body>"
        )
    with pytest.raises(ShapeError, match="or a page framing one"):
        eventdelay.parse(b'<html><iframe src="https://example.com/other.php"></iframe></html>')


def test_snowatch_list_before_eventdelay() -> None:
    """WDEL's older SnoWatch list: an index of categories, and one page per category."""
    folder = FIXTURES / "eventdelay"
    index = eventdelay.parse((folder / "snowatch-20200321.html").read_bytes())
    assert index.state is ListingState.DEFERRED
    assert index.follows == tuple(f"snowatch.php?type={n}" for n in (6, 5, 7, 3, 8, 10, 1))
    category = eventdelay.parse((folder / "snowatch-category-20200925.html").read_bytes())
    assert [(r.name, r.status, r.extra) for r in category.rows] == [
        (
            "North Elk Coffee House",
            "Closed",
            {
                "group": "Community/Non-Profit",
                "moreinfo": "The September, October, and November concerts at the North Elk "
                "Coffee House have been cancelled. Stay tuned for 2021.",
                "color": "#AA0000",
            },
        )
    ]
    mark = b'<a href="snowatch-request.php">register</a>'
    viewing = (
        b"You are now viewing an alphabetical listing of all SnoWatch listings for <b>Schools</b>:"
    )
    no_status = b"<div class=snowatch><div class=org>Synthetic School</div></div>"
    with pytest.raises(ShapeError, match="1 names and 0 statuses"):
        eventdelay.parse(mark + viewing + no_status)
    with pytest.raises(ShapeError, match="empty form has not been seen"):
        eventdelay.parse(mark + viewing)
    active = b"The following categories currently have active SnoWatch listings"
    with pytest.raises(ShapeError, match="neither lists categories"):
        eventdelay.parse(mark + active)


def test_sinclair_earlier_files() -> None:
    """KATV's page framed a header table in 2023; WBFF's earlier file is a paragraph list."""
    folder = FIXTURES / "sinclair"
    page = sinclair.parse((folder / "katv-page-20230202.html").read_bytes())
    assert page.follows == ("https://katv.com/resources/ftptransfer/katv/closings/closings.html",)
    katv = sinclair.parse((folder / "katv-20230202.html").read_bytes())
    assert (katv.rows[0].name, katv.rows[0].status, katv.rows[0].updated_text) == (
        "AEDD - Children's Center",
        "Closed Tomorrow",
        "February 1, 2023 9:45 pm CST",
    )
    wbff = sinclair.parse((folder / "wbff-20220107.html").read_bytes())
    assert [(r.name, r.status) for r in wbff.rows[:2]] == [
        ("Annapolis City Government", "Opening 2 hours late Liberal leave"),
        ("Anne Arundel Co Circuit Court", "Opening at 9:00 AM"),
    ]
    assert wbff.rows[0].updated_text == "8:39am on 1/07/2022"
    stamp = b"<P>Last Updated at 5:00am on 1/06/2025</P>\n"
    entry = b"<b>Synthetic County Schools</b><br>Closed <br><br>\n"
    assert newsticker.parse(stamp + b"<P>" + entry + b"</P>").rows[0].status == "Closed"
    with pytest.raises(ShapeError, match="holds"):
        newsticker.parse(stamp + b"<P>stray text " + entry + b"</P>")
    with pytest.raises(ShapeError, match="ends with"):
        newsticker.parse(stamp + b"<P>" + entry + b"stray text</P>")
    with pytest.raises(ShapeError, match="no entries"):
        newsticker.parse(stamp + b"<P> </P>")


def test_weatherthreat_pages() -> None:
    """KNEB's page: the alert bar's postings when it shows them, else the list script."""
    folder = FIXTURES / "weatherthreat"
    bar = weatherthreat.parse((folder / "kneb-page-20230118.html").read_bytes())
    assert [(r.name, r.status, r.extra) for r in bar.rows[:2]] == [
        (
            "WESTERN COMMUNITY COLLEGE AREA BOARD OF GOVERNORS",
            "Event Cancelled - Jan. Meeting Rescheduled to 1/25",
            {"location": "Scottsbluff"},
        ),
        ("CITY OF GERING", "Notice - SNOW EMERGENCY 8p 1/17 until lifted", {"location": "Gering"}),
    ]
    page = weatherthreat.parse((folder / "kneb-page-20151125.html").read_bytes())
    assert page.follows == (
        "http://wt1.weatherthreat.com/wt_list/viewClosings.php"
        "?media_id=kneb&plugin=1&server=wt1&version=2.0.1&directory=",
    )
    plugin = b"<!-- WeatherThreat Alerts Page Plugin -->"
    entry = (
        b'<ul class="cc_wt_list"><li class="cc_wt_title_wrapper"><a><span>SYNTHETIC SCHOOLS'
        b"</span><span>Closed (Details...)</span></a></li></ul>"
    )
    with pytest.raises(ShapeError, match="names no town"):
        weatherthreat.parse(plugin + entry)
    with pytest.raises(ShapeError, match="1 spans"):
        weatherthreat.parse(plugin + entry.replace(b"<span>Closed (Details...)</span>", b""))
    with pytest.raises(ShapeError, match="address is incomplete"):
        weatherthreat.parse(plugin + b"<script>'media_id=' + 'kneb'</script>")


def test_schoolclosings_table_before_blox() -> None:
    """KXLY's page before BLOX carried the schoolclosings.org table 9&10's page had."""
    folder = FIXTURES / "blox"
    table = blox.parse((folder / "kxly-page-20221130.html").read_bytes())
    assert [(r.name, r.updated_text, r.extra) for r in table.rows[:1]] == [
        (
            "Deer Park School District",
            "11/29/2022 03:55pm",
            {"address": "Deer Park, WA", "updated_label": "Updated 55 mins ago"},
        )
    ]
    assert blox.parse((folder / "kxly-page-20210215.html").read_bytes()).state is (
        ListingState.EMPTY
    )
    other = b'<div class="gtx-school-closings-page">Something else.</div>'
    with pytest.raises(ShapeError, match="neither its table"):
        blox.parse(other)


def test_hubbard_banner_is_a_count() -> None:
    """WHEC's site alert banner counts closings; it names none."""
    banner = hubbard.parse((FIXTURES / "hubbard" / "whec-banner-20221225.html").read_bytes())
    assert (banner.variant, banner.state, banner.declared_count) == (
        "hubbard-banner",
        ListingState.COUNT_ONLY,
        9,
    )
    assert banner.rows == ()
    assert banner.follows == ()
    zero = b'<div id="siteAlertBanner-21"><strong>0 School Closings: </strong></div>'
    with pytest.raises(ShapeError, match="count above zero"):
        hubbard.parse(zero)


def test_eventdelay_page_follows_its_frames() -> None:
    """WDEL's page frames the widget or the older SnoWatch list; frames in comments are not."""
    folder = FIXTURES / "eventdelay"
    live = eventdelay.parse((folder / "wdel-page-live-20260927.html").read_bytes())
    assert live.follows == ("https://eventdelay.com/new/widget/channel/114/page",)
    assert eventdelay.parse((folder / "wdel-page-20260124.html").read_bytes()).follows == (
        "https://eventdelay.com/new/widget/channel/114/page",
    )
    assert eventdelay.parse((folder / "wdel-page-20250118.html").read_bytes()).follows == (
        "https://www.eventdelay.com/new/widget/channel/114/list/",
    )
    assert eventdelay.parse((folder / "wdel-page-20180104.html").read_bytes()).follows == (
        "https://delmarvabroadcasting.com/wdel/snowatch.php",
    )
    assert eventdelay.parse((folder / "wdel-page-20210201.html").read_bytes()).follows == (
        "https://foreverdigitalmedia.com/wdel/snowatch.php",
    )
    commented = (
        b'<html><!--<iframe src="https://foreverdigitalmedia.com/wdel/snowatch.php"></iframe>-->'
        b'<iframe src="https://www.eventdelay.com/new/widget/channel/114/list/"></iframe></html>'
    )
    assert eventdelay.parse(commented).follows == (
        "https://www.eventdelay.com/new/widget/channel/114/list/",
    )
    with pytest.raises(ShapeError, match="or a page framing one"):
        eventdelay.parse(
            commented.replace(b'<iframe src="https://www.', b"<!--x").replace(
                b'list/"></iframe>', b"-->"
            )
        )


def test_eventdelay_list_mode_storm_days() -> None:
    """The list-mode widget on the storm days of January 2025: every closing, exactly."""
    folder = FIXTURES / "eventdelay"
    storm = eventdelay.parse((folder / "wdel-list-20250108.html").read_bytes())
    assert (storm.variant, storm.state, storm.skipped_rows) == (
        "eventdelay-list",
        ListingState.POPULATED,
        0,
    )
    assert [(r.name, r.status, r.updated_text, r.extra["category"]) for r in storm.rows] == [
        (
            "Caesar Rodney School District",
            "Asynchronous learning",
            "Tue, 01-7-25, 4:06pm",
            "Schools",
        ),
        ("Capital School District", "Asynchronous learning", "Tue, 01-7-25, 3:58pm", "Schools"),
        ("Cecil County Public Schools", "2 hr Delay", "Wed, 01-8-25, 4:24am", "Schools"),
        ("Harford County Public Schools", "2 hr Delay", "Wed, 01-8-25, 4:21am", "Schools"),
        ("Queen Anne's County Public Schools", "Closed", "Tue, 01-7-25, 5:36pm", "Schools"),
        ("SMYRNA SCHOOL DISTRICT", "Asynchronous learning", "Tue, 01-7-25, 4:03pm", "Schools"),
        ("Osher Lifelong Learning", "Closed", "Tue, 01-7-25, 5:35pm", "College / Adult Ed."),
        ("THE MUSIC SCHOOL OF DELAWARE", "Closed", "Tue, 01-7-25, 5:16pm", "Community"),
        (
            "DELAWARE STATE OFFICES SUSSEX COUNTY",
            "2 hr Delay",
            "Tue, 01-7-25, 6:13pm",
            "Government",
        ),
    ]
    capital = storm.rows[1]
    assert capital.extra == {
        "day": "Wednesday, January 8th",
        "category": "Schools",
        "dates": "01-08-2025 through 01-08-2025",
        "updated_scope": "row",
        "timezone": "America/New_York",
    }
    assert storm.rows[0].extra["details"] == (
        "10 and 12-month staff should report to buildings at 10:00 a.m."
    )
    sunday = eventdelay.parse((folder / "wdel-list-20250118.html").read_bytes())
    assert [(r.name, r.status, r.extra["day"]) for r in sunday.rows] == [
        ("DELAWARE MUSEUM OF NATURE AND SCIENCE", "Closed", "Sunday, January 19th")
    ]
    for empty in ("wdel-list-20241223.html", "wdel-list-live-20260927.html"):
        listing = eventdelay.parse((folder / empty).read_bytes())
        assert (listing.variant, listing.state) == ("eventdelay-list", ListingState.EMPTY)


def test_eventdelay_list_mode_refuses_unseen_markup() -> None:
    # Page mode's template writes a day's closings into a table (it closes one after
    # each day); that form has never been seen with rows, so it is refused.
    with pytest.raises(ShapeError, match="only the list mode's closing lists"):
        eventdelay.parse(
            b'<body class="widget widget-channel mode-page"><div id="body">'
            b'<h3 class="date-label">Mon</h3><table><tr><td>Synthetic</td></tr></table>'
            b"</div></body>"
        )
    body = (FIXTURES / "eventdelay" / "wdel-list-20250118.html").read_bytes()
    with pytest.raises(ShapeError, match="not labelled"):
        eventdelay.parse(body.replace(b"<label>Status: </label>", b"<label>State: </label>"))
    with pytest.raises(ShapeError, match="has not seen"):
        eventdelay.parse(
            body.replace(b'<p class="details">', b'<p class="extra">x</p><p class="details">')
        )
    with pytest.raises(ShapeError, match="holds a <table>"):
        eventdelay.parse(
            body.replace(b'<dt class="org_type">', b'<table></table><dt class="org_type">')
        )
    with pytest.raises(ShapeError, match=r"neither|something other"):
        eventdelay.parse(body.replace(b"There are no closings to display", b"Nothing to display"))


def test_blox_files_and_pages() -> None:
    sc = (
        b'<?xml version="1.0"?><File Time="01/06/2025 05:00am"><Closing><Name1>Synthetic R-VI'
        b"</Name1><EntityType>Schools</EntityType><Status>Closed</Status></Closing></File>"
    )
    row = blox.parse(sc).rows[0]
    assert (row.name, row.status, row.updated_text) == (
        "Synthetic R-VI",
        "Closed",
        "01/06/2025 05:00am",
    )
    assert row.extra == {"EntityType": "Schools", "updated_scope": "page"}
    cgs = (
        b'<?xml version="1.0"?><WEBCLOSE_XML><Source>CGS Mercury Publisher</Source>'
        b"<RecordCount>1</RecordCount><pubDate>Monday, January 6, 2025 5:00:00 AM CST</pubDate>"
        b"<Organization><Category>SCHOOLS</Category><Org>SYNTHETIC R-VI</Org>"
        b"<Status>Closed</Status><Status2 /></Organization></WEBCLOSE_XML>"
    )
    posting = blox.parse(cgs).rows[0]
    assert (posting.name, posting.status, posting.updated_text) == (
        "SYNTHETIC R-VI",
        "Closed",
        "Monday, January 6, 2025 5:00:00 AM CST",
    )
    assert posting.extra == {"Category": "SCHOOLS", "Status2": "", "updated_scope": "page"}
    with pytest.raises(ShapeError, match="counts 2"):
        blox.parse(cgs.replace(b">1<", b">2<"))
    nt = (
        b'<?xml version="1.0"?><DATA><NUM_CLOSINGS>1</NUM_CLOSINGS><RECORD>'
        b"<FORCED_ORGANIZATION_NAME>Synthetic SD</FORCED_ORGANIZATION_NAME>"
        b"<FORCED_STATUS_NAME>Closed</FORCED_STATUS_NAME><COUNTY>Spokane</COUNTY></RECORD></DATA>"
    )
    assert blox.parse(nt).rows[0].extra == {"county": "Spokane"}
    with pytest.raises(ShapeError, match="counts 2"):
        blox.parse(nt.replace(b">1<", b">2<"))
    with pytest.raises(ShapeError, match="root"):
        blox.parse(b'<?xml version="1.0"?><other/>')
    tables = b'<table class="weather-closings"><tbody><tr><td>x</td></tr></tbody></table>'
    with pytest.raises(ShapeError, match="not been seen"):
        blox.parse(tables)
    with pytest.raises(ShapeError, match="not a BLOX"):
        blox.parse(b"<html></html>")


def test_weatherthreat_hides_what_the_page_hides() -> None:
    def posting(kind: str, name: str, flagged: str) -> str:
        fields = [""] * 25
        fields[0], fields[5], fields[9], fields[13] = kind, name, "Closed", "2"
        fields[4], fields[23] = "All day", flagged
        return "~~".join(fields)

    script = "\n".join(
        [
            "function closing(theData) {}",
            "var closings = new Array();",
            f"closings[0] = new closing('{posting('clos', 'Synthetic Public Schools', '0')}');",
            f"closings[1] = new closing('{posting('unco', 'Unconfirmed School', '0')}');",
            f"closings[2] = new closing('{posting('clos', 'Flagged School', '2')}');",
            f"closings[3] = new closing('{posting('weat', '', '0')}');",
        ]
    )
    listing = weatherthreat.parse(script.encode())
    assert [(r.name, r.status) for r in listing.rows] == [
        ("Synthetic Public Schools", "Closed Monday - All day")
    ]
    assert listing.skipped_rows == 1
    with pytest.raises(ShapeError, match="not a WeatherThreat"):
        weatherthreat.parse(b"var x = 1;")


def test_townsquare_page_and_helpers() -> None:
    page = b'"html":"<iframe src=\\"/wp-content/uploads/njclosings/ByCountyclosings.html\\"'
    assert townsquare.parse(page).follows == (
        "/wp-content/uploads/njclosings/ByCountyclosings.html",
    )
    with pytest.raises(ShapeError, match=r"NJ 101\.5"):
        townsquare.parse(b"<html></html>")
    table = (
        b'Closings Last Updated at 5:00am on 1/6/2025<br><table id="closings-table"><tbody>'
        b'<tr><td colspan="2" class="county">Synthetic County</td></tr>'
        b'<tr class="business-rows"><td><span class="business">Synthetic Library</span><br>'
        b'<span class="city">Springfield</span></td><td><span class="status">Closed Today</span>'
        b'<br><span class="message"></span></td></tr></tbody></table>'
    )
    business = townsquare.parse(table).rows[0]
    assert (business.name, business.status, business.updated_text) == (
        "Synthetic Library",
        "Closed Today",
        "5:00am on 1/6/2025",
    )
    assert business.extra == {
        "updated_scope": "page",
        "city": "Springfield",
        "group": "Synthetic County",
    }
    with pytest.raises(ShapeError, match=r"0 span\.status"):
        townsquare.parse(table.replace(b'class="status"', b'class="other"'))
    with pytest.raises(ShapeError, match="not seen before"):
        townsquare.parse(table.replace(b'class="county"', b""))
    with pytest.raises(ShapeError, match="outside its rows"):
        townsquare.parse(table.replace(b">Synthetic County<", b'><span class="business">x</span><'))
    empty = b"<tr><td><b>No Closings have been reported at this time</b></td></tr>"
    with pytest.raises(ShapeError, match="says none"):
        townsquare.parse(table.replace(b"</tbody>", empty + b"</tbody>"))
    with pytest.raises(ShapeError, match="no rows and no"):
        townsquare.parse(
            b'Closings Last Updated at 5am<table id="closings-table"><tr><td></td></tr></table>'
        )
    assert regional.scalar(["a", 1]) == '["a", 1]'
    cut = regional.scalar("x" * 5000)
    assert isinstance(cut, str)
    assert cut.endswith("…")
    long_name = regional.row("n" * 600, "s", None, {})
    assert long_name is not None
    assert len(long_name.name) == 500
    assert regional.row("  ", "s", None, {}) is None
    with pytest.raises(ShapeError, match="not UTF-8"):
        regional.json_body(b'{"a": "\xff"}')
    with pytest.raises(ShapeError, match="not text"):
        regional.text_field({"a": 1}, "a")


NT_HEAD = b'<TABLE><TR><TD CLASS="timestamp">UPDATED MONDAY</TD></TR>'


def test_newsticker_worldnow_heading_cells() -> None:
    # As WHAM's and KOMO's WorldNow-styled exports write it: a racename heading cell,
    # rows in canname cells, empty separator rows between them.
    body = (
        NT_HEAD + b'<TR><TD CLASS="racename"><A NAME=""></A>County</TD></TR>'
        b'<TD HEIGHT=1 COLSPAN=4 CLASS="sub3"></TD></TR><TR><TD CLASS="canname">'
        b'<FONT CLASS="orgname">Synthetic Schools</FONT>: <FONT CLASS="status">Closed Today'
        b'</FONT></TD></TR><TR><TD HEIGHT=1 COLSPAN=4 CLASS="prereporting"></TD></TR></TABLE>'
    )
    listing = newsticker.parse(body)
    assert [(r.name, r.status, r.extra) for r in listing.rows] == [
        ("Synthetic Schools", "Closed Today", {"updated_scope": "page", "group": "County"})
    ]


REFUSALS = [
    # (adapter, SYNTHETIC body, part of the error message)
    (
        allen.parse,
        b"<table><tr><th colspan=\"2\" bgcolor='999999'></th></tr></table>",
        "without its time",
    ),
    (
        allen.parse,
        b"<table><tr><th colspan=\"2\" bgcolor='999999'>T</th></tr><tr><th>THERE ARE CURRENTLY NO "
        b"CLOSINGS OR CANCELLATIONS</th></tr><tr><td>A</td><td>Closed</td></tr></table>",
        "says there are none",
    ),
    (
        allen.parse,
        b"<table><tr><th colspan=\"2\" bgcolor='999999'>T</th></tr></table>",
        "no rows and no",
    ),
    (allen.parse, b"Created by CGS Infographics Automation<table></table>", "no title or time"),
    (
        allen.parse,
        b'Created by CGS Infographics Automation<div class="msg">T</div><table><tr><td>'
        b"There are no 'All Active' closings to report.</td></tr><tr><td>A</td><td>B</td></tr>"
        b"</table>",
        "a table of class None",
    ),
    (allen.parse, b"<html>nothing</html>", "not an Allen"),
    (blox.parse, b'<?xml version="1.0"?><File><Closing>', "does not parse"),
    (blox.parse, b'<File Time="t"><Closing><Name1>a</Name1></Closing></File>', "no Status"),
    (
        blox.parse,
        b'<File Time="t"><Closing><Status>x</Status><X><y/></X></Closing></File>',
        "plain text",
    ),
    (blox.parse, b'<File Time="t"><Other/></File>', "not a <Closing>"),
    (blox.parse, b'<File Time="t">some text</File>', "holds text"),
    (blox.parse, b'<?xml version="1.0"?><DATA><RECORD/></DATA>', "no NUM_CLOSINGS"),
    (
        blox.parse,
        b'<?xml version="1.0"?><DATA><NUM_CLOSINGS>0</NUM_CLOSINGS><X/></DATA>',
        "holds a <X>",
    ),
    (
        blox.parse,
        b'<?xml version="1.0"?><DATA><NUM_CLOSINGS>1</NUM_CLOSINGS><RECORD><A>a</A></RECORD>'
        b"</DATA>",
        "FORCED_STATUS_NAME",
    ),
    (blox.parse, b'<?xml version="1.0"?><WEBCLOSE_XML/>', "no RecordCount"),
    (
        blox.parse,
        b'<?xml version="1.0"?><WEBCLOSE_XML><RecordCount>0</RecordCount><X/></WEBCLOSE_XML>',
        "holds a <X>",
    ),
    (
        blox.parse,
        b'<?xml version="1.0"?><WEBCLOSE_XML><RecordCount>1</RecordCount><Organization><Org>a'
        b"</Org></Organization></WEBCLOSE_XML>",
        "no Status",
    ),
    (
        blox.parse,
        b'<div class="tncms-block closings"><article class="card"></article></div>',
        "headline",
    ),
    (delaware.parse, b"<other/>", "not a jqGrid"),
    (delaware.parse, b"<rows><records>x</records></rows>", "no record count"),
    (delaware.parse, b"<rows><records>0</records><other/></rows>", "holds a <other>"),
    (lockwood.parse, b'[{"record": [1], "num_closings": 1}]', "not an object"),
    (lockwood.parse, b'[{"record": [{"a": 1}], "num_closings": 1}]', "no status_name"),
    (lockwood.parse, b'[{"record": [], "num_closings": "0"}]', "record list and count"),
    (news12.parse, b"<html></html>", "no table-reflow"),
    (
        news12.parse,
        b'<table id="table-reflow"><thead><tr><th>A</th></tr></thead></table>',
        "columns",
    ),
    (
        news12.parse,
        b'<table id="table-reflow"><thead><tr><th>Name</th><th>City</th><th>Status</th></tr>'
        b'</thead><tbody><tr df="0"><td>A</td></tr></tbody></table>',
        "1 cells",
    ),
    (spectrum.parse, b'{"a": 1}', "not a list"),
    (spectrum.parse, b"[1]", "no closings list"),
    (spectrum.parse, b'[{"orgType": "S", "closings": [1]}]', "not an object"),
    (spectrum.parse, b"<html>nothing here</html>", "not a Spectrum"),
    (
        whdh.parse,
        b'<div class="wp-block-school-closings"><article class="closure-notice"></article></div>',
        "title or status",
    ),
    (whdh.parse, b"<html></html>", "no school-closings block"),
    (
        whdh.parse,
        b'<div class="wp-block-school-closings"><p>There are currently no school closings listed.'
        b'</p><article class="closure-notice"><h3 class="entry-title">A</h3><div class="current-'
        b'status">B</div></article></div>',
        "says none are listed",
    ),
    (wral.parse, b'{"closings": [1]}', "not an object"),
    (wral.parse, b'{"closings": [{"orgName": "a"}]}', "no statusText"),
    (wral.parse, b'{"other": 1}', "not a WRAL"),
    (wral.parse, b'{"closings": {}}', "not a list"),
    (wral.parse, b'{"closings": [], "count": "0"}', "not a number"),
    (wral.parse, b"<html></html>", "not a WRAL"),
    (wtop.parse, b"<html></html>", "no closings_by_state"),
    (wtop.parse, b"Site.closings_by_state = [broken", "not JSON"),
    (wtop.parse, b"Site.closings_by_state = {};", "neither an empty list"),
    (ncpr.parse, b"<html><body>storm</body></html>", "no div#closings"),
    (ncpr.parse, b'<div id="closings"><h4>x</h4></div>', "no update line"),
    (
        ncpr.parse,
        b'<div id="closings"><h3 id="updatedon">This data automatically updates every 60s. '
        b"Last updated Monday</h3><div><div>Synthetic Central School: Closed</div></div></div>",
        "under no posting heading",
    ),
    (
        ncpr.parse,
        b'<div id="closings"><h3 id="updatedon">This data automatically updates every 60s. '
        b"Last updated Monday</h3><h4>Closed</h4><div><div>Synthetic School</div></div></div>",
        "holds 0 organizations",
    ),
    (
        ncpr.parse,
        b'<div id="closings"><h3 id="updatedon">This data automatically updates every 60s. '
        b"Last updated Monday</h3><h4>Closed</h4><div></div></div>",
        "no entries and no",
    ),
    (
        ncpr.parse,
        b'<div id="closings"><h3 id="updatedon">This data automatically updates every 60s. '
        b"Last updated Monday</h3><p>x</p></div>",
        "holds a <p>",
    ),
    (wveis.parse, b"<rss><channel>", "does not parse"),
    (wveis.parse, b"<feed/>", "not the WVEIS closings feed or page"),
    (wveis.parse, b"<rss><feed/></rss>", "not an RSS"),
    (
        wveis.parse,
        b'<div id="page-content"><p>For today, Monday</p></div>',
        "no postings and no",
    ),
    (
        wveis.parse,
        b'<div id="page-content"><table class="closings-table"><tr><th>Name</th><th>Closed</th>'
        b"<th>Last update</th></tr></table></div>",
        "with the columns",
    ),
    (
        wveis.parse,
        b'<div id="page-content"><table class="closings-table"><tr><th>County</th><th>Closed</th>'
        b"<th>Last update</th></tr><tr><td>A</td><td>All</td></tr></table></div>",
        "2 cells, not 3",
    ),
    (
        wveis.parse,
        b'<div id="page-content"><p>No announcements to report</p><table class="closings-table">'
        b"<tr><th>County</th><th>Closed</th><th>Last update</th></tr><tr><td>A</td><td>All</td>"
        b"<td>x</td></tr></table></div>",
        "says there are none",
    ),
    (heritage.parse, b'{"a": 1}', "not a 9&10"),
    (heritage.parse, b"<html></html>", "no school closings content"),
    (graham.parse, b'{"a": 1}', "not a Graham"),
    (graham.parse, b"<html></html>", "no school-closings content"),
    (cox.parse, b'{"a": 1}', "not a Cox"),
    (sinclair.parse, b"<title>Closings Display</title>", "names no data address"),
    (
        sinclair.parse,
        b"<title>Closings Display</title>const jsonUrl = atob('@@@@')",
        "names no data",
    ),
    (
        sinclair.parse,
        b"<title>Closings Display</title>const jsonUrl = atob('aGk')",
        "does not decode",
    ),
    (sinclair.parse, b'{"bladeQueryItem": [1]}', "not an object"),
    (sinclair.parse, b"[1]", "not an object"),
    (sinclair.parse, b'{"bladeQueryItem": {}}', "not a list"),
    (sinclair.parse, b"\xff\xfe<html>", "not a Sinclair"),
    (hubbard.parse, b"<html></html>", "not a Hubbard"),
    (
        newsticker.parse,
        NT_HEAD + b'<TR><TD><FONT CLASS="orgname">A</FONT></TD><TD><FONT CLASS="status">'
        b'B</FONT></TD><TD><FONT CLASS="status">C</FONT></TD></TR></TABLE>',
        "one name and one",
    ),
    (newsticker.parse, NT_HEAD + b'<TR><TD class="school">A</TD></TR></TABLE>', "one school"),
    (
        newsticker.parse,
        b'<CENTER><FONT CLASS="orgname">A</FONT></CENTER>' + NT_HEAD + b"</TABLE>",
        "orgnames",
    ),
]


@pytest.mark.parametrize(
    ("parse", "body", "message"),
    REFUSALS,
    ids=[f"{p.__module__.rsplit('.', 1)[1]}-{n}" for n, (p, _b, _t) in enumerate(REFUSALS)],
)
def test_refusals(parse: Callable[[bytes], Listing], body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        parse(body)


def test_nameless_rows_are_counted_not_kept() -> None:
    sc = b'<File Time="t"><Closing><Name1></Name1><Status>Closed</Status></Closing></File>'
    assert (blox.parse(sc).state, blox.parse(sc).skipped_rows) == (ListingState.EMPTY, 1)
    grid = (
        b"Closings Last Updated at 1am<table><tr><td><b> </b></td><td>Closed</td><td></td></tr>"
        b"<tr><td><b>A</b></td><td>Open</td><td></td></tr></table>"
    )
    assert newsticker.parse(grid).skipped_rows == 1
    assert spectrum.parse(b'[{"closings": [{"status": "Closed"}]}]').skipped_rows == 1
    assert wral.parse(b'{"closings": [{"statusText": "Closed"}]}').skipped_rows == 1
    feed = b"<rows><records>1</records><row><cell/><cell>x</cell><cell/><cell/></row></rows>"
    assert delaware.parse(feed).skipped_rows == 1
    export = b'[{"record": [{"status_name": "Closed"}], "num_closings": 1}]'
    assert lockwood.parse(export).skipped_rows == 1
    assert sinclair.parse(b'{"bladeQueryItem": [{"statusName": "Closed"}]}').skipped_rows == 1
    cgs = (
        b'<?xml version="1.0"?><WEBCLOSE_XML><RecordCount>1</RecordCount><Organization>'
        b"<Status>x</Status></Organization></WEBCLOSE_XML>"
    )
    assert blox.parse(cgs).skipped_rows == 1
    nt = (
        b'<?xml version="1.0"?><DATA><NUM_CLOSINGS>1</NUM_CLOSINGS><RECORD>'
        b"<FORCED_STATUS_NAME>x</FORCED_STATUS_NAME></RECORD></DATA>"
    )
    assert blox.parse(nt).skipped_rows == 1


def test_helpers_decode_what_servers_send() -> None:
    assert regional.html_text(b"caf\xe9") == "café"  # Windows-1252, as older files are
    with pytest.raises(ShapeError, match="not JSON"):
        regional.json_body(b"{broken")
    assert regional.fusion_entry("no cache here", "closing") is None
    with pytest.raises(ShapeError, match="not an object"):
        regional.fusion_entry("Fusion.contentCache=[1]", "closing")
    with pytest.raises(ShapeError, match="unknown shape"):
        regional.fusion_entry('Fusion.contentCache={"closing": 1}', "closing")
    with pytest.raises(ShapeError, match="no data"):
        regional.fusion_entry('Fusion.contentCache={"closing": {"k": {}}}', "closing")
    page = (
        b'<script>Fusion.contentCache={"closing":{"u":{"data":{"totalClosings":0,'
        b'"closings":[]}}}};</script>'
    )
    assert cox.parse(page).declared_at is None
    notice = (
        b'<div class="wp-block-school-closings"><article class="closure-notice">'
        b'<div class="closure-header">Schools</div><h3 class="entry-title">A</h3>'
        b'<div class="current-status">B</div>'
        b'<div class="address"><span>1 Main St</span></div></article></div>'
    )
    assert whdh.parse(notice).rows[0].extra == {"category": "Schools", "address": "1 Main St"}
    older = (
        b'<html><iframe src="https://x.invalid/resources/ftptransfer/abcd/closings/a.html"></html>'
    )
    assert sinclair.slice_body(older) == regional.document(
        '<iframe src="https://x.invalid/resources/ftptransfer/abcd/closings/a.html"></iframe>'
    )
