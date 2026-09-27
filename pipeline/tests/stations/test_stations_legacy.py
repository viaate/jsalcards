"""Older page formats: Hearst's ibsys pages, Gray Digital Media pages and the Arc content API.

Fixtures are real Wayback ``id_`` captures sliced with ``hearst-page-v2`` or
``gray-page-v2`` (see fixtures/README.md for each URL and capture time). The expected
names and counts below were read from the fixtures with ``grep`` (``"name":"``,
``<tr><td><b>``, ``"totalCount"``), independently of the adapters. Bodies built here
from a real fixture and then edited are named ``synthetic_*``.
"""

import gzip
from pathlib import Path

import pytest

from snowlight.sources.stations import fixtures, gray, gray_legacy, hearst
from snowlight.sources.stations.model import ListingState, ShapeError

FIXTURES = Path(__file__).parent / "fixtures"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# Hearst ibsys (2014-2015) -------------------------------------------------------------


def test_kcci_january_2014_ibsys_list_is_read_whole() -> None:
    listing = hearst.parse(body("hearst/kcci-20140106024221.html"))
    assert listing.variant == "hearst-ibsys"
    assert listing.state is ListingState.POPULATED
    assert listing.declared_count == 203
    assert len(listing.rows) == 203
    first = listing.rows[0]
    assert first.name == "Ft. Dodge Public/Parochial Schools"
    assert first.status == "Monday: Closed"
    assert first.updated_text == "2014-01-05T13:27:00.000-06:00"
    assert first.extra == {"bucket": "f", "address": "Fort Dodge / Webster / IA"}
    assert [row.name for row in listing.rows[1:3]] == ["Gan Shalom", "Gilbert Schools"]
    assert listing.rows[-1].name == "2 For You Daycare"
    assert listing.rows[-1].extra["bucket"] == "0-9"


def test_wyff_february_2015_ibsys_rows_keep_email_keys_and_multi_day_statuses() -> None:
    listing = hearst.parse(body("hearst/wyff-20150220004919.html"))
    assert listing.declared_count == 67
    assert len(listing.rows) == 67
    church = listing.rows[1]
    assert church.name == "Fellowship Presbyterian Church - Greer"
    assert church.status == (
        "Wednesday: All Services Canceled...... Friday: All Services Canceled...... "
        "Saturday: All Services Canceled"
    )
    assert church.extra["emailListKey"] == "gs_closingsibstandard4393"
    assert church.extra["address"] == "Greer / Greenville / SC"
    assert listing.rows[-1].name == "Yancey County Schools"


def _ibsys(argument: str) -> bytes:
    return f"<script>ibsys.htvClosings.init({argument});</script>".encode()


def test_synthetic_ibsys_counts_must_agree() -> None:
    one = '{"name": "A School", "status": "Monday: Closed"}'
    with pytest.raises(ShapeError, match="says 2 but holds 1"):
        hearst.parse(_ibsys(f'{{"a": {{"count": 2, "institutions": [{one}]}}, "totalCount": 2}}'))
    with pytest.raises(ShapeError, match="totalCount is 3"):
        hearst.parse(_ibsys(f'{{"a": {{"count": 1, "institutions": [{one}]}}, "totalCount": 3}}'))
    with pytest.raises(ShapeError, match="totalCount is not a count"):
        hearst.parse(_ibsys(f'{{"a": {{"count": 1, "institutions": [{one}]}}}}'))


def test_synthetic_ibsys_empty_and_malformed_pages() -> None:
    empty = hearst.parse(_ibsys('{"totalCount": 0}'))
    assert empty.state is ListingState.EMPTY
    assert empty.declared_count == 0
    nameless = '{"a": {"count": 1, "institutions": [{"status": "Closed"}]}, "totalCount": 1}'
    with pytest.raises(ShapeError, match="every institution is missing its name"):
        hearst.parse(_ibsys(nameless))
    for bad, message in [
        ('{"a": [], "totalCount": 0}', "no institutions list"),
        ('{"a": {"count": 1, "institutions": [7]}, "totalCount": 1}', "not an object"),
        ('{"a": {"count": 1, "institutions": [{"name": "X"}]}, "totalCount": 1}', "lacks"),
        (
            '{"a": {"count": 1, "institutions": [{"name": "X", "status": "C", '
            '"updateTimestamp": 5}]}, "totalCount": 1}',
            "non-text updateTimestamp",
        ),
        ("[1, 2]", "not an object"),
        ('{"a": ', "not complete JSON"),
    ]:
        with pytest.raises(ShapeError, match=message):
            hearst.parse(_ibsys(bad))


def test_wbal_march_2015_ibsys_page_with_nothing_listed_is_empty() -> None:
    listing = hearst.parse(body("hearst/wbal-20150326154303.html"))
    assert (listing.variant, listing.state, listing.declared_count) == (
        "hearst-ibsys",
        ListingState.EMPTY,
        0,
    )


def test_hearst_v2_slice_is_v1_for_later_pages_and_keeps_only_the_ibsys_call() -> None:
    later = body("hearst/kmbc-20240117203333.html")
    assert hearst.slice_page_v2(later) == hearst.slice_page(later)
    ibsys = body("hearst/wyff-20150220004919.html")
    with pytest.raises(ShapeError):
        hearst.slice_page(ibsys)
    assert hearst.slice_page_v2(b"<p>ads</p>" + ibsys + b"<p>more</p>") == ibsys
    with pytest.raises(ShapeError, match="not closed"):
        hearst.slice_page_v2(_ibsys('{"totalCount": 0} x'))


# Older Gray station pages: Gray Digital Media (2014-2019), frames and BLOX pages ------


def test_wdbj_december_2018_tables_by_type_with_a_state_column() -> None:
    listing = gray.parse(body("gray/wdbj-20181213170119.html"))
    assert listing.variant == "gray-gdm-table"
    assert listing.state is ListingState.POPULATED
    assert len(listing.rows) == 50
    names = [row.name for row in listing.rows]
    assert (names[0], names[24], names[49]) == (
        "Centra PACE - Gretna",
        "Galax City Schools",
        "RADAR - PART",
    )
    first = listing.rows[0]
    assert first.status == "Closed Thursday"
    assert first.updated_text == "12/13/2018 11:58 AM"
    assert first.extra == {
        "updated_scope": "page",
        "type": "Business/Government/Other",
        "comment": "Closed Thursday",
        "state": "Virginia",
    }
    assert {row.extra["type"] for row in listing.rows} == {
        "Business/Government/Other",
        "Church",
        "Schools",
        "Transportation",
    }
    daycare = next(row for row in listing.rows if row.name == "Wytheville Child Development Ctr")
    assert daycare.status == "Delayed until 9:00AM on 2018-12-13"
    assert daycare.extra["comment"] == ""


def test_wbko_february_2017_school_rows_keep_their_comments() -> None:
    listing = gray.parse(body("gray/wbko-20170208104914.html"))
    assert [row.name for row in listing.rows] == [
        "Ohio County Schools",
        "Todd County Schools",
        "Todd County Schools",
        "Todd County Schools",
    ]
    ohio, todd = listing.rows[:2]
    assert ohio.status == "Closed Wednesday"
    # Runs of spaces in the page are collapsed; the words are kept as written.
    assert ohio.extra["comment"] == "closed Wednesday, Thursday and Friday. due to sickness"
    assert todd.status == "Closed Friday"
    assert todd.extra["comment"] == "Closed due to Illness NON-TRADITIONAL INSTRUCTIONAL DAYS"
    assert "state" not in todd.extra
    assert todd.extra["type"] == "SCHOOLS"


@pytest.mark.parametrize("name", ["wbko-20140326134714.html", "wbko-20181121212552.html"])
def test_gdm_no_closings_sentence_is_empty(name: str) -> None:
    listing = gray.parse(body(f"gray/{name}"))
    assert listing.variant == "gray-gdm-table"
    assert listing.state is ListingState.EMPTY


def test_gdm_2019_page_loads_its_list_from_the_export() -> None:
    listing = gray.parse(body("gray/wbko-20191216135847.html"))
    assert (listing.variant, listing.state) == ("gray-gdm-script", ListingState.DEFERRED)


def test_kktv_february_2014_list_rows() -> None:
    listing = gray.parse(body("gray/kktv-20140214173419.html"))
    assert (listing.variant, listing.state) == ("gray-gdm-list", ListingState.POPULATED)
    assert [row.name for row in listing.rows] == [
        "D-11 Col Springs",
        "D-12 Cheyenne Mtn",
        "D-14 Manitou Springs",
        "D-2 Harrison",
        "D-20 Academy",
        "D-3 Widefield",
        "D-38 Lewis-Palmer",
        "D-49 Falcon",
        "D-60 Pueblo",
        "D-70 Pueblo Cty",
        "D-8 Fountain-Ft Carson",
        "RE-2 Woodland Pk",
    ]
    assert {row.status for row in listing.rows} == {"As Scheduled"}
    assert listing.rows[0].extra == {"type": "Schools"}
    assert listing.rows[0].updated_text is None


@pytest.mark.parametrize(
    "name",
    [
        "wdbj-20141101044630.html",  # pre-Gray ibPublish page framing wdbj7ftp.us
        "kcrg-20151230154606.html",  # Gray Digital Media page framing clickability.com
        "kfvs-20181118182320.html",  # Raycom page framing webpubcontent.raycommedia.com
        "kfvs-20191116212553.html",  # Raycom page framing the GSync embed app
        "wlfi-20250124122656.html",  # Allen Media BLOX page framing ftp2.wlfi.com
        "wbrc-20190129015929.html",  # Raycom page framing its NewsTicker file
    ],
)
def test_pages_that_show_their_list_in_a_frame(name: str) -> None:
    listing = gray.parse(body(f"gray/{name}"))
    assert (listing.variant, listing.state) == ("gray-frame", ListingState.DEFERRED)
    assert listing.declared_count is None


@pytest.mark.parametrize(
    "name",
    [
        "kctv-20181009230234.html",  # Meredith BLOX page loading lmgcorporate.com XML
        "kake-20250317212819.html",  # BLOX page loading its own /app/closings/closings.xml
        "kake-20250219142859.html",  # the same, on a storm day
    ],
)
def test_blox_pages_load_their_list_by_script(name: str) -> None:
    listing = gray.parse(body(f"gray/{name}"))
    assert (listing.variant, listing.state) == ("gray-blox-script", ListingState.DEFERRED)


def test_synthetic_frames_and_blox_pages_need_their_markers() -> None:
    # A tag manager frame names the page only in its query: not a closings frame.
    manager = b'<iframe src="https://www.googletagmanager.com/ns.html?path=%2Fweather%2Fclosings">'
    assert gray_legacy.frame(manager) is None
    blox = body("gray/kctv-20181009230234.html")
    no_mark = blox.replace(b"tncms-", b"other-")
    with pytest.raises(ShapeError, match="not a Gray closings body"):
        gray.parse(no_mark)
    # The file is named outside any script: not a page this adapter knows.
    outside = b'<meta name="tncms-x" /><p>amb-feeds.s3.amazonaws.com/WLFI_closings.json</p>'
    assert gray_legacy.blox_parts(outside) is None
    unclosed = b'<meta name="tncms-x" /><script>get("amb-feeds.s3.amazonaws.com/W_closings.json")'
    assert gray_legacy.blox_parts(unclosed) is None


def test_synthetic_list_rows() -> None:
    row = "<div><span style='font-weight:bold'>{name}</span> - Status: {status}</div>"
    block = (
        '<div id="ClosingsModule1"><h3>Type: Schools</h3>'
        + row.format(name="A School", status="Closed")
        + "<div><span>Not bold</span> - Status: Open</div>"
        + "<div><span style='font-weight:bold'>Heading</span> without a status</div>"
        + "</div>"
    ).encode()
    listing = gray.parse(block)
    assert [(r.name, r.status) for r in listing.rows] == [("A School", "Closed")]
    with pytest.raises(ShapeError, match="no name"):
        gray.parse(block.replace(b"A School", b" "))
    mixed = block.replace(
        b"</div></div>",
        b"</div><table><tr><th>Organization</th><th>Status</th></tr>"
        b"<tr><td>B</td><td>Open</td></tr></table></div>",
    )
    with pytest.raises(ShapeError, match="mixes tables and list rows"):
        gray.parse(mixed)


_TABLE = (
    "<h2>School and Organization Closings and Delays</h2>\n<section>{inner}</section>"
    "<section>not the list</section>"
)


def _gdm(inner: str) -> bytes:
    return _TABLE.format(inner=inner).encode()


def test_synthetic_gdm_table_errors() -> None:
    header = "<tr><th>Organization</th><th>Status</th></tr>"
    for inner, message in [
        ("<table><tr><th>Name</th><th>Status</th></tr></table>", "not Organization, Status"),
        (f"<table>{header}<tr><td>A</td></tr></table>", "1 cells for 2 columns"),
        ("<table><tr><td>A</td><td>Closed</td></tr></table>", "a row before its header"),
        (f"<table>{header}<tr><td> </td><td>Closed</td></tr></table>", "missing its name"),
        (f"<table>{header}</table>", "no rows and no no-closings sentence"),
        ("<p>Nothing to see</p>", "no rows and no no-closings sentence"),
    ]:
        with pytest.raises(ShapeError, match=message):
            gray.parse(_gdm(inner))
    with pytest.raises(ShapeError, match="not closed"):
        gray.parse(b"<h2>School and Organization Closings and Delays</h2><section><p>")
    with pytest.raises(ShapeError, match="not a Gray closings body"):
        gray.parse(b"<html><body>An article</body></html>")


def test_synthetic_gdm_rows_without_page_time_or_heading() -> None:
    inner = (
        "<table><tr><th>Organization</th><th>Status</th></tr>"
        "<tr><td><b>A School</b></td><td>Closed Monday</td></tr>"
        "<tr><td></td><td>Closed</td></tr></table>"
    )
    listing = gray.parse(_gdm(inner))
    (row,) = listing.rows
    assert (row.name, row.status, row.updated_text, row.extra) == (
        "A School",
        "Closed Monday",
        None,
        {},
    )
    assert listing.skipped_rows == 1


def test_gray_v2_slice_is_v1_for_arc_pages_and_exports_and_cuts_older_pages() -> None:
    for name in ("kctv-20240115205330.html", "kwch-export-20250319101557.json"):
        arc = body(f"gray/{name}")
        assert gray.slice_page_v2(arc) == gray.slice_page(arc)
    gdm = body("gray/wbko-20170208104914.html")
    with pytest.raises(ShapeError, match="slice_page_v2"):
        gray.slice_page(gdm)
    assert gray.slice_page_v2(b"<p>ads</p>" + gdm + b"<p>footer</p>") == gdm
    with pytest.raises(ShapeError, match="not a Gray closings body"):
        gray_legacy.slice_page(b"<html>An article</html>")
    compressed = gzip.compress(gdm)
    assert fixtures.slice_body("gray-page-v2", compressed) == gdm


# Arc content API (gsync-closings served alone) ----------------------------------------


def test_wlbt_november_2022_content_api_listing() -> None:
    listing = gray.parse(body("gray/wlbt-api-20221129194333.json"))
    assert listing.variant == "gray-api-orgs"
    assert listing.declared_count == 14
    assert [row.name for row in listing.rows] == [
        "Canton Public School District",
        "Clinton Public School District",
        "Clinton Public School District",
        "Copiah County School District",
        "Hinds County School District",
        "Hinds County School District",
        "Mississippi College",
        "Mississippi State University",
        "Pearl Public School District",
        "Porter's Chapel Academy",
        "Rankin County School District",  # the trailing space is dropped
        "Simpson Academy",
        "University of Southern Mississippi",
        "Vicksburg Warren School District",
    ]


def test_wave_2026_content_api_count_of_zero_is_empty() -> None:
    listing = gray.parse(body("gray/wave-api-20260907225032.json"))
    assert (listing.variant, listing.state, listing.declared_count) == (
        "gray-api-count",
        ListingState.EMPTY,
        0,
    )


def test_a_frame_of_a_cgs_all_active_page_is_followed() -> None:
    """WTVA's 2018 page frames the CGS "All Active" page on cgs.wtva.com (real capture)."""
    body = (FIXTURES / "gray" / "wtva-20180112151927.html").read_bytes()
    listing = gray.parse(body)
    assert (listing.variant, listing.state) == ("gray-frame", ListingState.DEFERRED)
    assert listing.follows == ("http://cgs.wtva.com/wtva/All_Active.html",)


def test_a_blank_counter_says_nothing() -> None:
    """WTVA's banner counter captured 2025-01-26 with ``"numClosings": ""`` (real capture)."""
    body = (FIXTURES / "gray" / "wtva-counter-20250126142814.json").read_bytes()
    listing = gray.parse(body)
    assert (listing.variant, listing.state) == ("gray-file-count-json", ListingState.DEFERRED)
    assert listing.declared_count is None
    assert listing.follows == ()
