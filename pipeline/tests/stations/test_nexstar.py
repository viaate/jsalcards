"""The Nexstar adapter against real live bodies (fixtures/groups/nexstar/) and error cases.

Fixtures are live responses read on 2026-09-26 with the pipeline's own client (see
fixtures/groups/README.md for each one's URL, time and SHA-256). The expected names
below were read from the fixtures with ``grep`` over ``h3.closing__title`` (and the
feed's ``content`` values), independently of the adapter. Bodies built in this file,
from a real fixture or from nothing, are named ``synthetic_*``.
"""

import gzip
import json
import re
from pathlib import Path

import pytest

from snowlight.sources.stations import nexstar
from snowlight.sources.stations.model import ListingState, ShapeError

FIXTURES = Path(__file__).parent / "fixtures" / "groups"
DASH = "\N{EN DASH}"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


WTNH = ["Glanbia Nutritionals", f"St. James Episcopal Church {DASH} NL", "UCC of Westerly"]
WPRI = [
    "Beneficent Church",
    f"First Congregational {DASH} Bristol",
    f"First Congregational {DASH} Warwick",
    "Roger Williams Park Zoo",
    "Seekonk Congregational Church, UCC",
    "Slatersville Congregational Church",
    f"St Francis Xavier {DASH} E. Prov.",
    "Wesley United Methodist Church",
]


def test_wtnh_rest_page_by_id_reads_every_row_with_details() -> None:
    listing = nexstar.parse(body("nexstar/wtnh-page-20260926224825.json"))
    assert (listing.variant, listing.state) == ("nexstar-wp-closings", ListingState.POPULATED)
    assert [row.name for row in listing.rows] == WTNH
    first, _second, third = listing.rows
    assert first.status == "Team C and 2nd shift all locations Cancelled."
    assert first.extra == {"locality": "W Haven", "category": "Business", "letter": "G"}
    assert first.updated_text is None
    # A row without a locality keeps only what the page gives.
    assert third.extra == {"category": "Religious", "letter": "U"}
    assert listing.skipped_rows == 0


def test_the_slug_array_reads_as_the_page_by_id() -> None:
    by_slug = nexstar.parse(body("nexstar/wtnh-slug-20260926223951.json"))
    assert [row.name for row in by_slug.rows] == WTNH
    assert by_slug.variant == "nexstar-wp-closings"


def test_wpri_rows_keep_comments_and_the_page_order() -> None:
    listing = nexstar.parse(body("nexstar/wpri-page-20260926224828.json"))
    assert [row.name for row in listing.rows] == WPRI
    warwick = listing.rows[2]
    assert warwick.status == "No Sunday Services"
    assert warwick.extra["comments"] == "Weather"
    assert [row.extra["letter"] for row in listing.rows] == ["B", "F", "F", "R", "S", "S", "S", "W"]


def test_the_app_feed_carries_the_same_rows_as_the_page() -> None:
    feed = nexstar.parse(body("nexstar/wpri-feed-20260926223957.json"))
    page = nexstar.parse(body("nexstar/wpri-page-20260926224828.json"))
    assert feed.variant == "nexstar-app-feed"
    # The feed writes a plain hyphen where the page renders an en dash.
    assert [row.name.replace(" - ", f" {DASH} ") for row in feed.rows] == [
        row.name for row in page.rows
    ]
    assert [row.status for row in feed.rows] == [row.status for row in page.rows]
    warwick = feed.rows[2]
    assert warwick.extra["comments_line1"] == "Weather"
    assert warwick.extra["city"] == "Warwick"
    assert warwick.extra["uuid"] == "facf73f7-15e7-5005-b9f2-6779491145af"
    wtnh = nexstar.parse(body("nexstar/wtnh-feed-20260926223952.json"))
    assert len(wtnh.rows) == 3


def test_koin_empty_page_says_so_in_its_own_words() -> None:
    listing = nexstar.parse(body("nexstar/koin-page-20260926224830.json"))
    assert (listing.variant, listing.state, listing.rows) == (
        "nexstar-wp-closings",
        ListingState.EMPTY,
        (),
    )


def test_koin_feed_with_only_a_nameless_row_is_an_error() -> None:
    with pytest.raises(ShapeError, match="missing its name"):
        nexstar.parse(body("errors/koin-feed-20260926223959.json"))


def test_pages_that_frame_their_list_are_deferred_to_the_file() -> None:
    ksn = nexstar.parse(body("nexstar/ksnw-page-20260926224815.json"))
    assert (ksn.variant, ksn.state) == ("nexstar-wp-frame", ListingState.DEFERRED)
    assert ksn.follows == (
        "https://media.psg.nexstardigital.net/ksnw/weather/ksnwx-closings-nwt.html",
    )
    kolr = nexstar.parse(body("nexstar/kolr-page-20260926224818.json"))
    assert kolr.follows == (
        "https://www.schoolclosingsnet.com/report.php?type=html&code=c81e720002",
    )
    # The ECC frame is an application, not a list: nothing is named, and the reader
    # loads the station's registered data_url instead.
    wgn = nexstar.parse(body("nexstar/wgn-page-20260926224820.json"))
    assert (wgn.state, wgn.follows) == (ListingState.DEFERRED, ())


def test_frame_files_in_their_empty_states() -> None:
    psg = nexstar.parse(body("nexstar/ksnw-psg-20260926224342.html"))
    assert (psg.variant, psg.state) == ("nexstar-psg-closings", ListingState.EMPTY)
    scn = nexstar.parse(body("nexstar/kolr-scn-20260926224344.html"))
    assert (scn.variant, scn.state) == ("schoolclosingsnet-table", ListingState.EMPTY)
    ecc = nexstar.parse(body("nexstar/wgn-ecc-20260926224340.json"))
    assert (ecc.variant, ecc.state) == ("nexstar-ecc-json", ListingState.EMPTY)


def test_a_gzip_body_reads_like_the_plain_one() -> None:
    plain = body("nexstar/wtnh-page-20260926224825.json")
    assert nexstar.parse(gzip.compress(plain)).rows == nexstar.parse(plain).rows


def _article(name: str) -> str:
    rendered = json.loads(body(name))["content"]["rendered"]
    assert isinstance(rendered, str)
    return rendered


def test_synthetic_html_page_holding_the_real_article_reads_as_nexstar_page() -> None:
    # An archived HTML page carries the same server-rendered article; no such capture
    # has been downloaded yet, so the real article is wrapped in a minimal page.
    synthetic_page = f"<html><body><main>{_article('nexstar/wtnh-page-20260926224825.json')}"
    synthetic_page += "</main></body></html>"
    listing = nexstar.parse(synthetic_page.encode())
    assert listing.variant == "nexstar-page"
    assert [row.name for row in listing.rows] == WTNH


def test_synthetic_html_pages_that_frame_list_files() -> None:
    synthetic_tribune = (
        '<html><body><p>[localtv_vendor_embed src="https://cdn.trb.tv/wdaf-ftp/closings/'
        'allactive.html"]</p><iframe src="https://www.youtube.com/embed/x"></iframe></body></html>'
    )
    listing = nexstar.parse(synthetic_tribune.encode())
    assert (listing.variant, listing.state) == ("nexstar-page-frame", ListingState.DEFERRED)
    assert listing.follows == ("https://cdn.trb.tv/wdaf-ftp/closings/allactive.html",)
    synthetic_video_only = '<html><body><iframe src="https://www.youtube.com/embed/x"></iframe>'
    with pytest.raises(ShapeError, match="not a Nexstar closings body"):
        nexstar.parse(synthetic_video_only.encode())


def test_synthetic_ecc_file_with_closings_reads_as_its_application_does() -> None:
    # The populated form has not been captured; this follows the fields the ECC
    # application's own code reads (ID, Name1, City, EntityType, Status1, Status2).
    synthetic_ecc = {
        "$": {"Time": "01/12/2026 05:40:31 AM"},
        "Closing": [
            {
                "ID": ["1001"],
                "Name1": ["Example School District 1"],
                "City": ["Chicago"],
                "EntityType": ["Public School"],
                "Status1": ["Closed Today"],
                "Status2": ["No Evening Activities"],
            },
            {"ID": ["1002"], "Name1": [""], "Status1": ["Closed"]},
        ],
    }
    listing = nexstar.parse(json.dumps(synthetic_ecc).encode())
    assert listing.state is ListingState.POPULATED
    (row,) = listing.rows
    assert row.name == "Example School District 1"
    assert row.status == "Closed Today | No Evening Activities"
    assert row.updated_text == "01/12/2026 05:40:31 AM"
    assert row.extra == {
        "updated_scope": "page",
        "ID": "1001",
        "City": "Chicago",
        "EntityType": "Public School",
    }
    assert listing.skipped_rows == 1


@pytest.mark.parametrize(
    ("synthetic_ecc", "message"),
    [
        ({"$": {}}, r"\$\.Time"),
        ({"$": {"Time": "x"}, "Other": 1}, "unexpected fields"),
        ({"$": {"Time": "x"}, "Closing": {}}, "not a list"),
        ({"$": {"Time": "x"}, "Closing": ["x"]}, "not an object"),
        ({"$": {"Time": "x"}, "Closing": [{"Name1": "x"}]}, "not a list of text"),
        ({"$": {"Time": "x"}, "Closing": [{"Status1": ["Closed"]}]}, "missing its name"),
    ],
)
def test_synthetic_ecc_shapes_that_are_errors(synthetic_ecc: object, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        nexstar.parse(json.dumps(synthetic_ecc).encode())


def test_synthetic_school_closings_network_rows_follow_the_real_header() -> None:
    real = body("nexstar/kolr-scn-20260926224344.html").decode()
    synthetic_rows = real.replace(
        "<tbody>",
        "<tbody><tr><td>Example R-1 Schools</td><td>01/12/2026</td><td>01/13/2026</td>"
        "<td>Closed</td><td>Snow routes</td></tr><tr><td></td><td></td><td></td><td>Closed</td>"
        "<td></td></tr>",
    )
    listing = nexstar.parse(synthetic_rows.encode())
    (row,) = listing.rows
    assert (row.name, row.status) == ("Example R-1 Schools", "Closed")
    assert row.extra == {
        "closing_start": "01/12/2026",
        "through": "01/13/2026",
        "notes": "Snow routes",
    }
    assert listing.skipped_rows == 1
    synthetic_short = real.replace("<tbody>", "<tbody><tr><td>Only one cell</td></tr>")
    with pytest.raises(ShapeError, match="1 cells for 5 columns"):
        nexstar.parse(synthetic_short.encode())
    synthetic_header = real.replace("<th>Status</th>", "<th>State</th>")
    with pytest.raises(ShapeError, match="header"):
        nexstar.parse(synthetic_header.encode())


def test_synthetic_psg_file_with_neither_rows_nor_its_empty_sentence_is_an_error() -> None:
    real = body("nexstar/ksnw-psg-20260926224342.html").decode()
    synthetic = real.replace("<strong>No closings to report</strong>", "<div>Example</div>")
    with pytest.raises(ShapeError, match="no rows and no empty sentence"):
        nexstar.parse(synthetic.encode())
    nameless = real.replace(
        "<strong>No closings to report</strong>",
        '<div class="closing_row"><strong>:</strong> Closed</div>',
    )
    with pytest.raises(ShapeError, match="missing its name"):
        nexstar.parse(nameless.encode())
    unbolded = real.replace(
        "<strong>No closings to report</strong>", '<div class="closing_row">Closed</div>'
    )
    with pytest.raises(ShapeError, match="without its bold name"):
        nexstar.parse(unbolded.encode())


def _page_json(rendered: str) -> bytes:
    return json.dumps(
        {"id": 1, "link": "https://x.test/", "content": {"rendered": rendered}}
    ).encode()


def test_synthetic_article_shapes_that_are_errors() -> None:
    article = _article("nexstar/wtnh-page-20260926224825.json")
    with pytest.raises(ShapeError, match="no closings-list"):
        nexstar.parse(_page_json(article.replace('class="closings-list"', 'class="other"')))
    # A row shown with its name alone (as KOIN's archived page has one) has the empty status.
    no_status = article.replace("closing__status", "closing__other")
    assert {row.status for row in nexstar.parse(_page_json(no_status)).rows} == {""}
    nameless = article.replace("closing__title", "closing__heading")
    with pytest.raises(ShapeError, match="missing its name"):
        nexstar.parse(_page_json(nameless))
    empty = _article("nexstar/koin-page-20260926224830.json")
    reworded = empty.replace("Most recent closings", "Latest closings")
    with pytest.raises(ShapeError, match="no rows and no empty sentence"):
        nexstar.parse(_page_json(reworded))
    with pytest.raises(ShapeError, match="no closings article and frames no list"):
        nexstar.parse(_page_json("<p>Madison County Schools will operate on a delay.</p>"))


def test_synthetic_rest_arrays() -> None:
    article = _article("nexstar/wtnh-page-20260926224825.json")
    older = {"id": 2, "content": {"rendered": "<p>There are no current closings.</p>"}}
    current = {"id": 1, "content": {"rendered": article}}
    listing = nexstar.parse(json.dumps([older, current]).encode())
    assert [row.name for row in listing.rows] == WTNH
    other = _article("nexstar/wpri-page-20260926224828.json")
    twins = [current, {"id": 3, "content": {"rendered": other}}]
    with pytest.raises(ShapeError, match="list different rows"):
        nexstar.parse(json.dumps(twins).encode())
    with pytest.raises(ShapeError, match="none holds the closings article"):
        nexstar.parse(json.dumps([older, older]).encode())
    with pytest.raises(ShapeError, match=r"without content\.rendered"):
        nexstar.parse(json.dumps({"content": {"raw": "x"}}).encode())


@pytest.mark.parametrize(
    ("synthetic", "message"),
    [
        (b"[1, 2]", "neither the app feed nor REST pages"),
        (b'{"a": 1}', "does not know"),
        (b"[{", "not JSON"),
        (b'[{"uuid": "x", "content": "A"}]', "not a closing object"),
        (b'[{"uuid": "x", "content": 1, "status": "Closed"}]', "not text"),
        (b"<html><body>Hello</body></html>", "not a Nexstar closings body"),
    ],
)
def test_synthetic_bodies_in_no_known_shape(synthetic: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        nexstar.parse(synthetic)


def test_empty_array_is_the_app_feed_empty_state() -> None:
    # The feed's own empty answer. (A pages?slug= query for a missing page also
    # answers [], which is why the registry reads pages by id.)
    listing = nexstar.parse(b"[]")
    assert (listing.variant, listing.state) == ("nexstar-app-feed", ListingState.EMPTY)


@pytest.mark.parametrize(
    "name",
    [
        "nexstar/wtnh-page-20260926224825.json",
        "nexstar/ksnw-page-20260926224815.json",
        "nexstar/wgn-ecc-20260926224340.json",
        "nexstar/kolr-scn-20260926224344.html",
    ],
)
def test_slicing_is_stable(name: str) -> None:
    original = body(name)
    assert nexstar.slice_body(original) == original


def test_slicing_an_html_page_keeps_the_article_or_the_frames() -> None:
    article = _article("nexstar/wtnh-page-20260926224825.json")
    synthetic_page = f"<html><head><title>x</title></head><body>{article}<footer>f</footer>"
    cut = nexstar.slice_body(synthetic_page.encode())
    assert b"<footer>" not in cut
    assert nexstar.parse(cut).rows == nexstar.parse(synthetic_page.encode()).rows
    synthetic_frame = (
        '<html><body><iframe src="https://media.psg.nexstardigital.net/ksnw/weather/x.html">'
        "</iframe><nav>n</nav></body></html>"
    )
    cut = nexstar.slice_body(synthetic_frame.encode())
    assert b"<nav>" not in cut
    assert nexstar.parse(cut).follows == nexstar.parse(synthetic_frame.encode()).follows
    array = json.dumps(
        [
            {"id": 2, "content": {"rendered": "<p>old</p>"}},
            {"id": 1, "content": {"rendered": article}},
        ]
    ).encode()
    assert nexstar.parse(nexstar.slice_body(array)).rows == nexstar.parse(array).rows
    with pytest.raises(ShapeError, match="not closed"):
        nexstar.slice_body(_page_json('<article class="closings-page"><p>'))


def test_synthetic_closing_outside_the_list_is_not_read() -> None:
    article = _article("nexstar/wtnh-page-20260926224825.json")
    stray = '<div class="closing"><h3 class="closing__title">Stray</h3></div>'
    synthetic = article.replace("</article>", f"</article>{stray}")
    listing = nexstar.parse(_page_json(synthetic))
    assert [row.name for row in listing.rows] == WTNH


# Archived variants: CGS, the NewsTicker table, the script-filled pages ------------------------


def test_synthetic_cgs_pages() -> None:
    real = body("nexstar/wdaf-cgs-20191216111946.html").decode()
    head = real.split('<table class="tableborder">', 1)[0]
    empty = (
        head + '<table class="tablenoborder"><tr><td class="msg">There are no \'All Active\' '
        "closings to report.</td></tr></table></body></html>"
    )
    assert nexstar.parse(empty.encode()).state is ListingState.EMPTY
    with pytest.raises(ShapeError, match="no rows and no empty sentence"):
        nexstar.parse((head + "</body></html>").encode())
    nameless = (
        head + '<table class="tableborder"><tr><td class="cat">A</td><td class="org"> </td>'
        '<td class="sts">Closed</td></tr></table>'
    )
    with pytest.raises(ShapeError, match="missing its organization"):
        nexstar.parse(nameless.encode())
    one_less = nameless.replace('<td class="org"> </td>', "")
    with pytest.raises(ShapeError, match="organization and status cells"):
        nexstar.parse(one_less.encode())
    no_stamp = real.replace('<div class="msg">12/16/2019 5:19:26 AM</div>', "")
    with pytest.raises(ShapeError, match="no time stamp"):
        nexstar.parse(no_stamp.encode())
    skipped = real.replace(
        '<td class="org">Casco Area Workshop Harrisonville</td>', '<td class="org"></td>'
    )
    assert nexstar.parse(skipped.encode()).skipped_rows == 1


def test_synthetic_newsticker_tables() -> None:
    real = body("nexstar/wpri-newsticker-20201218214155.html").decode()
    odd = real.replace("<TR><TD>&nbsp;</TD></TR>", "<TR><TD>a</TD><TD>b</TD><TD>c</TD></TR>", 1)
    with pytest.raises(ShapeError, match="no known shape"):
        nexstar.parse(odd.encode())
    unnamed = real.replace(
        '<FONT CLASS="orgname">Cumberland Public Schools</FONT>', '<FONT CLASS="orgname"></FONT>'
    )
    with pytest.raises(ShapeError, match="has no name"):
        nexstar.parse(unnamed.encode())
    two_status = real.replace(
        '<FONT CLASS="orgname">Cumberland Public Schools</FONT>',
        '<FONT CLASS="status">Cumberland Public Schools</FONT>',
    )
    with pytest.raises(ShapeError, match="not a town, a name and a status"):
        nexstar.parse(two_status.encode())
    row = (
        '<TR><TD><FONT CLASS="status">X</FONT></TD><TD><FONT CLASS="orgname">Y</FONT>: '
        '<FONT CLASS="status">Z</FONT></TD></TR>'
    )
    with pytest.raises(ShapeError, match="no organization rows"):
        nexstar.parse_newsticker_table("<TABLE></TABLE>")
    (only,) = nexstar.parse_newsticker_table(f"<TABLE>{row}</TABLE>").rows
    assert (only.name, only.status, only.updated_text, only.extra) == (
        "Y",
        "Z",
        None,
        {"town": "X"},
    )


def test_synthetic_script_filled_and_frankly_pages() -> None:
    feed = '<div data-feed="//media.example.com/a/closings/X.xml" data-feed-type="XML"></div>'
    page = f"<html><body>{feed}</body></html>".encode()
    listing = nexstar.parse(page)
    assert (listing.variant, listing.follows) == (
        "nexstar-feed-page",
        ("//media.example.com/a/closings/X.xml",),
    )
    assert nexstar.parse(nexstar.slice_body_v2(page)).follows == listing.follows
    frankly = b'<html><body><div id="closing-alerts-auto-complete-1"></div></body></html>'
    with pytest.raises(ShapeError, match="Frankly"):
        nexstar.parse(frankly)
    with pytest.raises(ShapeError, match="not a Nexstar closings body"):
        nexstar.slice_body_v2(b"<html><body>Hello</body></html>")
    rest = _page_json(f"<div>{feed}</div>")
    assert nexstar.parse(rest).variant == "nexstar-feed-page"


def test_shortcodes_as_the_tribune_era_pages_wrote_them() -> None:
    escaped = (
        "<p>[localtv_vendor_embed src=&quot;https://newcdn.tribtv.com/x/SchoolClosings/c.html&quot;"
        " height=&quot;500&quot;]</p>"
    )
    plain = (
        '[localtv_vendor_embed src="https://s3.amazonaws.com/kdvrclosings/kdvr.html" height="5"]'
    )
    blank = '[localtv_vendor_embed src="" height="5"]'
    for page, follows in [
        (escaped, ("https://newcdn.tribtv.com/x/SchoolClosings/c.html",)),
        (plain + blank, ("https://s3.amazonaws.com/kdvrclosings/kdvr.html",)),
    ]:
        listing = nexstar.parse(f"<html><body>{page}</body></html>".encode())
        assert listing.follows == follows
        cut = nexstar.slice_body_v2(f"<html><body>{page}<nav>n</nav></body></html>".encode())
        assert b"<nav>" not in cut
        assert nexstar.parse(cut).follows == follows


@pytest.mark.parametrize(
    "name",
    [
        "nexstar/wtnh-page-20260926224825.json",
        "nexstar/wpri-feed-20260926223957.json",
        "nexstar/ksnw-psg-20260926224342.html",
        "nexstar/kolr-scn-20260926224344.html",
        "nexstar/wdaf-cgs-20191216111946.html",
        "nexstar/wowk-psgpage-20250213090134.html",
    ],
)
def test_v2_keeps_what_v1_keeps(name: str) -> None:
    original = body(name)
    assert nexstar.slice_body_v2(original) == nexstar.slice_body(original) == original


def test_synthetic_school_information_and_storm_tracker_shapes() -> None:
    real = body("nexstar/wreg-schoolinfo-20200215171705.html").decode()
    with pytest.raises(ShapeError, match="no update time"):
        nexstar.parse(real.replace("<b>School Information", "<i>School Information").encode())
    odd = real.replace("<td>&nbsp;</font></td></tr>", "</tr>", 1)
    with pytest.raises(ShapeError, match="no known shape"):
        nexstar.parse(odd.encode())
    only_heading = re.sub(r"<tr valign=top><td width=400>.*?</tr>", "", real)
    with pytest.raises(ShapeError, match="no rows"):
        nexstar.parse(only_heading.encode())
    comment = real.replace("<td>&nbsp;</font></td>", "<td>Buses late</font></td>", 1)
    assert nexstar.parse(comment.encode()).rows[0].extra["comment"] == "Buses late"
    storm = body("nexstar/wten-stormtracker-20181203111455.html").decode()
    with pytest.raises(ShapeError, match="no posted time"):
        nexstar.parse(storm.replace("(posted:", "(at:").encode())
    with pytest.raises(ShapeError, match="no rows and no empty sentence"):
        nexstar.parse(storm.replace("No School Closings to Report", "Nothing").encode())
