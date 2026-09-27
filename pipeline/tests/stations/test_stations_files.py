"""List files older Gray pages framed or loaded: NewsTicker, Meredith XML, counters and more.

Fixtures are real Wayback ``id_`` captures of the files registered stations' pages
named (see fixtures/README.md for each URL and capture time), kept whole. The
expected names below were read from the fixtures by eye or, for the two long
files, with the standard library's HTML parser (independently of the adapter's
own regular expressions). Bodies built here from a real fixture and then edited,
or written from scratch, are named ``synthetic_*``.
"""

from html.parser import HTMLParser
from pathlib import Path

import pytest

from snowlight.sources.stations import gray, gray_files, gray_legacy
from snowlight.sources.stations.model import ListingState, ShapeError

FIXTURES = Path(__file__).parent / "fixtures" / "gray"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class _Cells(HTMLParser):
    """Collect the text of every element whose class is one of ``wanted`` (stdlib parser)."""

    def __init__(self, wanted: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.wanted = wanted
        self.found: list[tuple[str, str]] = []
        self._open: str | None = None
        self._tag = ""
        self._depth = 0
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._open is not None:
            self._depth += tag == self._tag
            return
        kind = dict(attrs).get("class")
        if kind is not None and kind.lower() in self.wanted:
            self._open, self._tag, self._depth, self._text = kind.lower(), tag, 1, []

    def handle_endtag(self, tag: str) -> None:
        if self._open is None or tag != self._tag:
            return
        self._depth -= 1
        if self._depth == 0:
            self.found.append((self._open, " ".join("".join(self._text).split())))
            self._open = None

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._text.append(data)


def _pairs(name: str, name_class: str, status_class: str) -> list[tuple[str, str]]:
    parser = _Cells({name_class, status_class})
    parser.feed(body(name).decode("utf-8"))
    # The adapter drops a "[WEB]" link after a name (its address goes in raw_extra).
    names = [text.removesuffix(" [WEB]") for kind, text in parser.found if kind == name_class]
    statuses = [text for kind, text in parser.found if kind == status_class]
    assert len(names) == len(statuses)
    return list(zip(names, statuses, strict=True))


# NewsTicker HTML -------------------------------------------------------------------------


def test_wbrc_january_2019_newsticker_file_lists_196_organizations() -> None:
    listing = gray.parse(body("wbrc-file-20190129043208.html"))
    assert listing.variant == "gray-file-newsticker"
    assert listing.state is ListingState.POPULATED
    expected = _pairs("wbrc-file-20190129043208.html", "orgname", "status")
    assert len(expected) == 196
    assert [(row.name, row.status) for row in listing.rows] == expected
    first = listing.rows[0]
    assert first.name == "A G GASTON BOYS AND GIRLS CLUB"
    assert first.status == "CLOSED TUESDAY"
    assert first.updated_text == "UPDATED MONDAY, JAN 28 AT 10:25 PM"
    assert first.extra == {"updated_scope": "page"}
    linked = [row.name for row in listing.rows if "homepage" in row.extra]
    assert linked == ["Holy Infant of Prague Church"]


def test_wafb_school_details_layout_is_read_row_by_row() -> None:
    listing = gray.parse(body("wafb-file-20190418025348.html"))
    assert listing.variant == "gray-file-newsticker"
    expected = _pairs("wafb-file-20190418025348.html", "school", "details")
    assert len(expected) == 71
    assert [(row.name, row.status) for row in listing.rows] == expected
    assert listing.rows[2].name == "Baker School Sytem"  # the file's own spelling
    assert listing.rows[0].updated_text == "UPDATED WEDNESDAY, APR 17 AT 9:30 PM"


def test_woio_rows_carry_their_county_heading() -> None:
    listing = gray.parse(body("woio-file-20191112192419.html"))
    groups = [(row.extra["group"], row.name) for row in listing.rows]
    assert groups == [
        ("ASHLAND", "Mapleton Local SD"),
        ("ASHTABULA", "Conneaut Area City SD"),
        ("CUYAHOGA", "St Joseph Academy High"),
        ("CUYAHOGA", "St Martin High"),
        ("ERIE", "Edison Local SD"),
        ("ERIE", "EHOVE Career Center Voc"),
        ("ERIE", "Sandusky City SD"),
        ("GEAUGA", "Berkshire Local SD"),
        ("GEAUGA", "St Helen Elem"),
        ("GEAUGA", "West Geauga Local SD"),
        ("HURON", "Monroeville Local SD"),
        ("HURON", "New London Local SD"),
        ("HURON", "Norwalk City SD"),
        ("HURON", "South Central Local SD"),
        ("HURON", "Western Reserve Local SD - Collins"),
        ("LAKE", "Auburn Career Center"),
        ("RICHLAND", "Crestview Local SD"),
        ("WAYNE", "West Salem Christian Educators"),
    ]
    assert listing.rows[9].status == "No Evening Classes; All evening activities cancelled"


def test_wave_rows_keep_state_and_category_and_drop_the_web_link_from_the_name() -> None:
    listing = gray.parse(body("wave-file-20190327182656.html"))
    assert [row.name for row in listing.rows] == [
        "Jeff Co Catholic Elementary Schools",
        "Jeff Co Catholic High Schools",
    ]
    row = listing.rows[0]
    assert row.status == "OPEN"
    assert row.updated_text == "LAST UPDATED: WEDNESDAY, MAR 27 AT 2:25 PM"
    assert row.extra == {
        "updated_scope": "page",
        "state": "Kentucky",
        "category": "SCHOOLS",
        "homepage": "http://www.archlou.org/archlou/schools",
    }


def test_wis_category_headings_and_wfsb_linked_names() -> None:
    wis = gray.parse(body("wis-file-20190322150050.html"))
    assert [(row.extra["group"], row.name, row.status) for row in wis.rows] == [
        ("BUSINESS", "Hansen International", "Normal Schedule; Normal Time"),
        (
            "CHURCHES",
            "St. Joseph Parish Religious Education",
            "No evening classes; Due to water main break",
        ),
    ]
    wfsb = gray.parse(body("wfsb-file-20241209072211.html"))
    assert [row.name for row in wfsb.rows] == [
        "Danbury Schools",
        "Henry Abbott Technical HS-Danbury",
        "Life Christian School-Danbury",
    ]
    assert {row.status for row in wfsb.rows} == {"Closed Today"}
    assert "homepage" not in wfsb.rows[0].extra


def test_newsticker_empty_state() -> None:
    listing = gray.parse(body("wlio-file-20260905112750.html"))
    assert listing.variant == "gray-file-newsticker"
    assert listing.state is ListingState.EMPTY


def test_synthetic_newsticker_files_that_do_not_add_up() -> None:
    real = body("wis-file-20190322150050.html")
    stray = real.replace(
        b"</TABLE>", b'<TR><TD><FONT CLASS="orgname">Loose</FONT></TD></TR></TABLE>'
    )
    with pytest.raises(ShapeError, match="neither a row nor a heading"):
        gray.parse(stray)
    nameless = real.replace(b">Hansen International<", b"> <")
    with pytest.raises(ShapeError, match="has no name"):
        gray.parse(nameless)
    silent = (
        b'<TABLE><TR><TD CLASS="timestamp">UPDATED MONDAY</TD></TR>'
        b'<TR><TD CLASS="school"></TD></TR></TABLE>'
    )
    with pytest.raises(ShapeError, match="no rows and no no-records sentence"):
        gray.parse(silent)


# XML files ---------------------------------------------------------------------------


def test_kctv_ticker_rows_and_empty_ticker() -> None:
    listing = gray.parse(body("kctv-ticker-20200121233932.xml"))
    assert listing.variant == "gray-file-ticker-xml"
    assert [(row.name, row.status, row.updated_text) for row in listing.rows] == [
        (
            "Immanuel Baptist Church, Indep., MO",
            "Wednesday, Jan 22, noon service cancelled",
            "01/21/2020 11:10:15 AM",
        ),
        ("Livingston Co. R-III School, Chula, MO", "Closed", "01/21/2020 05:09:53 PM"),
    ]
    assert listing.rows[1].extra == {"type": "Schools", "state": "MO", "id": "052980"}
    empty = gray.parse(body("kctv-ticker-20181219005936.xml"))
    assert (empty.variant, empty.state) == ("gray-file-ticker-xml", ListingState.EMPTY)


def test_synthetic_ticker_shapes() -> None:
    with pytest.raises(ShapeError, match="no no-closings sentence"):
        gray.parse(b'<?xml version="1.0"?>\n<ticker lastupdate="x"></ticker>')
    with pytest.raises(ShapeError, match="lacks its name"):
        gray.parse(
            b'<?xml version="1.0"?>\n<ticker><closing><status>Closed</status></closing></ticker>'
        )
    with pytest.raises(ShapeError, match="not a <closing>"):
        gray.parse(b'<?xml version="1.0"?>\n<ticker><item/></ticker>')
    with pytest.raises(ShapeError, match="does not parse"):
        gray.parse(b'<?xml version="1.0"?>\n<ticker><closing></ticker>')


def test_kmov_sc_file_empty_and_synthetic_rows() -> None:
    empty = gray.parse(body("kmov-sc-20201208195958.xml"))
    assert (empty.variant, empty.state) == ("gray-file-sc-xml", ListingState.EMPTY)
    synthetic = (
        b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<File Time="01/02/2020 06:00am">'
        b"<Closing><EntityType>Schools</EntityType><Name1>Caf\xe9 School</Name1>"
        b"<Status>Closed</Status><Status2></Status2></Closing>"
        b"<Closing><EntityType>Schools</EntityType><Name1></Name1><Status>Closed</Status></Closing>"
        b"</File>"
    )
    listing = gray.parse(synthetic)
    assert [(row.name, row.status) for row in listing.rows] == [("Café School", "Closed")]
    assert listing.skipped_rows == 1
    assert listing.rows[0].extra == {
        "EntityType": "Schools",
        "Status2": "",
        "updated_scope": "page",
    }
    assert listing.rows[0].updated_text == "01/02/2020 06:00am"
    with pytest.raises(ShapeError, match="has no Status"):
        gray.parse(b'<?xml version="1.0"?><File><Closing><Name1>A</Name1></Closing></File>')


def test_kake_newsticker_xml_empty_export_and_synthetic_counts() -> None:
    empty = gray.parse(body("kake-newsticker-20250317213113.xml"))
    assert (empty.variant, empty.state, empty.declared_count) == (
        "gray-file-newsticker-xml",
        ListingState.EMPTY,
        0,
    )
    record = (
        b"<RECORD><REC_ID>7</REC_ID><FORCED_ORGANIZATION_NAME>USD 259 Wichita"
        b"</FORCED_ORGANIZATION_NAME><FORCED_STATUS_NAME>Closed Today</FORCED_STATUS_NAME>"
        b"<UPDATED>2025-01-06</UPDATED><COUNTY_NAME1>Sedgwick</COUNTY_NAME1></RECORD>"
    )
    head = b'<?xml version="1.0"?><DATA><SOURCE>NewsTicker</SOURCE><NUM_CLOSINGS>%d</NUM_CLOSINGS>'
    listing = gray.parse(head % 1 + record + b"</DATA>")
    row = listing.rows[0]
    assert (row.name, row.status, row.updated_text) == (
        "USD 259 Wichita",
        "Closed Today",
        "2025-01-06",
    )
    assert row.extra == {"rec_id": "7", "county_name1": "Sedgwick"}
    assert listing.declared_count == 1
    with pytest.raises(ShapeError, match="NUM_CLOSINGS is 2"):
        gray.parse(head % 2 + record + b"</DATA>")


# Counters, empty-only formats, and files that load another ------------------------------


def test_allen_media_counter_is_a_count_not_a_list() -> None:
    listing = gray.parse(body("wlfi-counter-20250125011749.json"))
    assert (listing.variant, listing.state, listing.declared_count) == (
        "gray-file-count-json",
        ListingState.EMPTY,
        0,
    )
    real = body("wlfi-counter-20250125011749.json")
    counted = gray.parse(real.replace(b'"numClosings":"0"', b'"numClosings":"12"'))
    assert (counted.state, counted.declared_count, counted.follows) == (
        ListingState.COUNT_ONLY,
        12,
        (),
    )
    with pytest.raises(ShapeError, match="not a count"):
        gray.parse(real.replace(b'"numClosings":"0"', b'"numClosings":"many"'))


class _Tagged(HTMLParser):
    """Collect the text of every ``tag`` element (stdlib parser), outer spaces trimmed."""

    def __init__(self, tag: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tag = tag
        self.found: list[str] = []
        self._text: list[str] | None = None

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag == self.tag:
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == self.tag and self._text is not None:
            self.found.append(" ".join("".join(self._text).split()))
            self._text = None

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text.append(data)


def _tagged(name: str, tag: str) -> list[str]:
    parser = _Tagged(tag)
    parser.feed(body(name).decode("utf-8"))
    return parser.found


def test_wjrt_storm_night_grid_lists_216_organizations_name_by_name() -> None:
    listing = gray.parse(body("wjrt-file-20220203035319.html"))
    assert (listing.variant, listing.state) == ("gray-file-grid", ListingState.POPULATED)
    # Every bold cell, read with the standard library's parser, is one row's name.
    assert [row.name for row in listing.rows] == _tagged("wjrt-file-20220203035319.html", "b")
    assert len(listing.rows) == 216
    first, second, third = listing.rows[:3]
    assert (first.name, first.status, first.extra) == (
        "Akron/Fairgrove Schools",
        "Closed",
        {"updated_scope": "page", "comment": "Thursday"},
    )
    assert (second.name, second.status, second.extra) == (
        "Alma Schools",
        "Closed",
        {"updated_scope": "page"},
    )
    assert (third.status, third.extra["comment"]) == (
        "Opening at 12:00 PM (Noon)",
        "on Thursday, February 3, 2022",
    )
    assert {row.updated_text for row in listing.rows} == {"10:52pm on 2/02/2022"}


def test_whns_grid_and_the_empty_grid() -> None:
    listing = gray.parse(body("whns-file-20200327091409.html"))
    assert [row.name for row in listing.rows] == [
        "Holly Tree Pediatric Dentistry",
        "ProGrin Boiling Springs",
        "SHARE Headstart",
        "Jackson Baptist Church",
        "White Hall Independent Methodist Church",
        "Trinity Preschool Anderson",
    ]
    assert (listing.rows[0].status, listing.rows[0].extra["comment"]) == (
        "Closed Mar 17 - 27",
        "Emergency patients only",
    )
    assert listing.rows[0].updated_text == "5:13am on 3/27/2020"
    empty = gray.parse(body("wjrt-file-20250210160919.html"))
    assert (empty.variant, empty.state) == ("gray-file-grid", ListingState.EMPTY)


def test_synthetic_grids_that_do_not_read() -> None:
    real = body("whns-file-20200327091409.html")
    both = (
        real.replace(
            b"<b>Holly Tree Pediatric Dentistry&nbsp;</b>",
            b"<b>No Closings have been reported at this time</b>",
        )
        .replace(b"Closed Mar 17 - 27&nbsp;", b"&nbsp;")
        .replace(b"Emergency patients only&nbsp;", b"")
    )
    with pytest.raises(ShapeError, match="lists rows and says none"):
        gray.parse(both)
    with pytest.raises(ShapeError, match="has 2 cells"):
        gray.parse(real.replace(b'<td width="33%">Emergency patients only&nbsp;</td>', b""))
    with pytest.raises(ShapeError, match="not a bold name"):
        gray.parse(real.replace(b"<b>SHARE Headstart&nbsp;</b>", b"SHARE Headstart"))
    with pytest.raises(ShapeError, match="no rows and no no-closings"):
        gray.parse(b"<table>Closings Last Updated at 1:00am on 1/01/2020<br></table>")


def test_kptv_flashalert_report_name_by_name() -> None:
    listing = gray.parse(body("kptv-file-20200317023000.html"))
    assert (listing.variant, listing.state) == ("gray-file-flashalert", ListingState.POPULATED)
    # The first bold element of each report is its name; "UPDATE" is a mark, not a name.
    strong = _tagged("kptv-file-20200317023000.html", "strong")
    names = [text for text in strong if text != "UPDATE"]
    assert [row.name for row in listing.rows] == names
    assert len(names) == 22
    by_name = {row.name: row for row in listing.rows}
    molalla = by_name["Molalla River Sch. Dist."]
    assert molalla.status.startswith("Closed. Grab-and-Go meal hours expanded:")
    assert molalla.status.endswith("(For Tue. Mar 17th)")
    assert molalla.extra == {"updated_scope": "page", "category": "Clackamas Co. Schools"}
    assert molalla.updated_text == "Portland/Vanc/Salem School Closures for Mon. Mar. 16 - 7:20 pm"
    assert by_name["WA School for the Deaf"].status == (
        "Closed. March 16-April 24. Conditions will be reevaluated and adjusted if necessary."
        " UPDATE"
    )
    assert by_name["Greater Portland Baptist Church & Academy"].extra["category"] == (
        "Churches/Synagogues"
    )
    one = gray.parse(body("kptv-file-20190321165417.html"))
    assert [(row.name, row.status, row.extra["category"]) for row in one.rows] == [
        (
            "EOCF Head Start/ECEAP",
            "Long Beach HS classrooms closed. UPDATE",
            "Head Start /Early Childhood Centers",
        )
    ]
    empty = gray.parse(body("kptv-file-20240131153828.html"))
    assert (empty.variant, empty.state) == ("gray-file-flashalert", ListingState.EMPTY)


def test_synthetic_flashalert_reports_that_do_not_read() -> None:
    real = body("kptv-file-20190321165417.html")
    with pytest.raises(ShapeError, match="not followed by"):
        gray.parse(real.replace(b"</strong>&nbsp;- Long Beach", b"</strong> Long Beach"))
    with pytest.raises(ShapeError, match="does not start with a bold name"):
        gray.parse(real.replace(b"<strong>EOCF Head Start/ECEAP</strong>", b"EOCF"))
    both = real.replace(
        b"<div class='cwcReportCat'>",
        b"<div class='cwcReport'>No information reported.</div><div class='cwcReportCat'>",
    )
    with pytest.raises(ShapeError, match="lists rows and says nothing"):
        gray.parse(both)


def test_a_gsync_embed_frame_is_followed_to_the_export_its_script_reads() -> None:
    page = gray.parse(body("kfvs-20191116212553.html"))
    assert (page.variant, page.state) == ("gray-frame", ListingState.DEFERRED)
    assert page.follows == (
        "https://s3.amazonaws.com/grayfilestore-kfvs/closingsData/closings_KFVS.json",
    )
    assert gray_legacy.gsync_export(
        "//webpubcontent.raycommedia.com/raycom/gsync/#/embed/closings/wave"
    ) == ("https://s3.amazonaws.com/grayfilestore-wave/closingsData/closings_WAVE.json")
    assert gray_legacy.gsync_export(
        "https://webpubcontent.raycommedia.com/raycom/gsync/#/embed/closings/wistv"
    ) == ("https://s3.amazonaws.com/grayfilestore-wis/closingsData/closings_WIS.json")
    assert gray_legacy.gsync_export("//webpubcontent.raycommedia.com/wbrc/closings.html") is None


def test_wdbj_framed_page_names_the_sc_file_its_script_loads() -> None:
    listing = gray.parse(body("wdbj-frame-20141014142544.html"))
    assert listing.variant == "gray-file-sc-script"
    assert listing.state is ListingState.DEFERRED
    assert listing.follows == ("../WDBJ-SC4C.xml",)


def test_list_files_are_kept_whole_as_fixtures() -> None:
    for name in ("wbrc-file-20190129043208.html", "kctv-ticker-20200121233932.xml"):
        assert gray.slice_page_v3(body(name)) == body(name)
        assert gray_files.is_file(body(name))
    assert not gray_files.is_file(b"<html><body>Nothing here</body></html>")
    with pytest.raises(ShapeError, match="not a closings list file"):
        gray_files.parse(b"<html><body>Nothing here</body></html>")
