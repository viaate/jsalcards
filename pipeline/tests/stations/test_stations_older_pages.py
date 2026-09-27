"""Older Gray pages that hold no list of their own, read through the file that holds it.

Each test lays real fixtures (fixtures/gray/, see its README for every URL and capture
time) out as the archive workflow writes them, at their real capture times, and
reads them with the real registry, so the page is followed to the list file captured
nearest it. The expected names are read from the list files independently of the
adapter (the standard library's JSON, XML and HTML parsers). Where a test moves a
real body to another time, it says so and is named ``synthetic_*``.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import pytest

from snowlight.sources.stations import archive, gray, gray_files, gray_legacy
from snowlight.sources.stations.fetch import RunResult
from snowlight.sources.stations.model import HealthStatus, ListingRead, ListingState, ShapeError
from snowlight.sources.stations.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "gray"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _artifact(tmp_path: Path, captures: Sequence[tuple[str, str, bytes]]) -> Path:
    """Lay out (timestamp, URL, body) captures the way the archive workflow writes them."""
    root = tmp_path / "artifact"
    snaps = root / "snapshots"
    snaps.mkdir(parents=True)
    records: list[Mapping[str, object]] = []
    for number, (stamp, url, data) in enumerate(captures):
        name = f"snapshots/{number}.body"
        (root / name).write_bytes(data)
        records.append(
            {
                "timestamp": stamp,
                "url": url,
                "requested": f"https://web.archive.org/web/{stamp}id_/{url}",
                "retrieved_at": "2026-09-26T03:00:00Z",
                "final_timestamp": stamp,
                "final_original": url,
                "http_status": 200,
                "file": name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    text = "".join(json.dumps(record) + "\n" for record in records)
    (snaps / "manifest.jsonl").write_text(text, encoding="utf-8")
    return root


def _followed(tmp_path: Path, captures: Sequence[tuple[str, str, bytes]]) -> RunResult:
    result = archive.parse_snapshots(load_registry(), _artifact(tmp_path, captures))
    assert len(result.reads) == 1
    return result


def _only_read(result: RunResult) -> ListingRead:
    (read,) = result.reads
    return read


def _export_names(name: str) -> list[str]:
    """Names in an S3 export, as the stdlib JSON parser reads them (outer spaces trimmed)."""
    (export,) = json.loads(body(name))
    return [item["forced_organization_name"].strip() for item in export["record"]]


def _xml_names(name: str, record: str, field: str) -> list[str]:
    root = ElementTree.fromstring(body(name))  # noqa: S314 - a real fixture from this repo
    return [(item.findtext(field) or "").strip() for item in root.iter(record)]


class _Classed(HTMLParser):
    """Text of each element whose class is ``wanted`` (stdlib parser, case-insensitive)."""

    def __init__(self, wanted: str) -> None:
        super().__init__(convert_charrefs=True)
        self.wanted = wanted
        self.found: list[str] = []
        self._depth = 0
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if self._depth:
            self._depth += 1
        elif (dict(attrs).get("class") or "").lower() == self.wanted:
            self._depth, self._text = 1, []

    def handle_endtag(self, tag: str) -> None:  # noqa: ARG002
        if self._depth:
            self._depth -= 1
            if not self._depth:
                self.found.append(" ".join("".join(self._text).split()))

    def handle_data(self, data: str) -> None:
        if self._depth:
            self._text.append(data)


def _orgnames(name: str) -> list[str]:
    parser = _Classed("orgname")
    parser.feed(body(name).decode("utf-8"))
    return [text.removesuffix(" [WEB]") for text in parser.found]


class _Bold(HTMLParser):
    """Text of each ``<b>`` that holds no heading: the SC paragraph names (stdlib parser)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[str] = []
        self._text: list[str] | None = None
        self._heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag == "b":
            self._text, self._heading = [], False
        elif tag == "h2" and self._text is not None:
            self._heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "b" and self._text is not None:
            if not self._heading:
                self.found.append(" ".join("".join(self._text).split()))
            self._text = None

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text.append(data)


def _bold_names(name: str) -> list[str]:
    parser = _Bold()
    parser.feed(body(name).decode("utf-8"))
    return parser.found


# The five older page formats, each followed to its list -----------------------------


def test_raycom_frame_page_is_read_through_its_newsticker_file(tmp_path: Path) -> None:
    # gray-frame: WBRC's page captured 2019-01-29 01:59:29 framed
    # //webpubcontent.raycommedia.com/wbrc/closings.html, captured 2 h 32 min later.
    page = "http://www.wbrc.com/weather/closings/"
    file = "https://webpubcontent.raycommedia.com/wbrc/closings.html"
    result = _followed(
        tmp_path,
        [
            ("20190129015929", page, body("wbrc-20190129015929.html")),
            ("20190129043208", file, body("wbrc-file-20190129043208.html")),
        ],
    )
    read = _only_read(result)
    assert (read.source_id, read.url, read.variant, read.rows) == (
        "gray-wbrc",
        file,
        "gray-file-newsticker",
        196,
    )
    (hop,) = read.via
    # The page writes the frame's src without a scheme; it resolves against the page's.
    assert (hop.url, hop.variant, hop.state, hop.follows, hop.gap_seconds) == (
        page,
        "gray-frame",
        ListingState.DEFERRED,
        "http://webpubcontent.raycommedia.com/wbrc/closings.html",
        9159,
    )
    assert [row.raw_name for row in result.rows] == _orgnames("wbrc-file-20190129043208.html")
    assert result.rows[0].raw_name == "A G GASTON BOYS AND GIRLS CLUB"
    assert {row.fetched_at for row in result.rows} == {datetime(2019, 1, 29, 4, 32, 8, tzinfo=UTC)}


def test_blox_page_is_read_through_the_xml_its_script_loads(tmp_path: Path) -> None:
    # gray-blox-script: KAKE's BLOX page captured 2025-02-19 14:28:59; its script
    # fetches /app/closings/closings.xml, captured one second earlier.
    page = "https://www.kake.com/weather/closings-and-delays/"
    file = "https://www.kake.com/app/closings/closings.xml"
    result = _followed(
        tmp_path,
        [
            ("20250219142859", page, body("kake-20250219142859.html")),
            ("20250219142858", file, body("kake-newsticker-20250219142858.xml")),
        ],
    )
    read = _only_read(result)
    assert (read.url, read.variant, read.rows, read.declared_count) == (
        file,
        "gray-file-newsticker-xml",
        251,
        251,
    )
    (hop,) = read.via
    assert (hop.variant, hop.follows, hop.gap_seconds) == ("gray-blox-script", file, -1)
    names = _xml_names("kake-newsticker-20250219142858.xml", "RECORD", "FORCED_ORGANIZATION_NAME")
    assert [row.raw_name for row in result.rows] == names
    assert len(names) == 251


def test_gdm_script_page_is_read_through_the_export_it_names(tmp_path: Path) -> None:
    # gray-gdm-script: KVLY's page captured 2020-03-24 21:07:25 names the export URL
    # with its query (r=2421206147); the export was captured 22 s later.
    page = "https://www.valleynewslive.com/weather/closings/?r=2421206145&c=n"
    file = (
        "https://s3.amazonaws.com/grayfilestore-kvly/closingsData/closings_KVLY.json"
        "?c=n&r=2421206147"
    )
    listing = gray.parse(body("kvly-20200324210725.html"))
    assert listing.follows == (file,)
    result = _followed(
        tmp_path,
        [
            ("20200324210725", page, body("kvly-20200324210725.html")),
            ("20200324210747", file, body("kvly-export-20200324210747.json")),
        ],
    )
    read = _only_read(result)
    assert (read.source_id, read.variant, read.rows) == ("gray-kvly", "gray-s3-json", 25)
    (hop,) = read.via
    assert (hop.variant, hop.gap_seconds, hop.count_matches) == ("gray-gdm-script", 22, None)
    names = _export_names("kvly-export-20200324210747.json")
    assert [row.raw_name for row in result.rows] == names
    assert names[:2] == [
        "Valley City Public Schools",
        "Dakota Magic Casino &amp; Hotel, Dakota Connection Bingo &amp; Casino and "
        "Dakota Sioux Casino &amp; Hotel",
    ]


def test_count_page_is_read_through_its_export_and_its_count_checked(tmp_path: Path) -> None:
    # gray-fusion-count: KOLN's page captured 2025-03-19 14:26:07 counts 397 as of
    # 14:24:00 (its cache entry's lastModified); the export captured at 14:26:08
    # lists 398. The count was made 128 s before the list, outside the two-minute
    # window in which a difference is a failure, so it is recorded, not failed.
    page = "https://www.1011now.com/weather/closings/"
    file = (
        "https://s3.amazonaws.com/grayfilestore-koln/closingsData/closings_KOLN.json"
        "?rnd=796659&arc-site=koln"
    )
    result = _followed(
        tmp_path,
        [
            ("20250319142607", page, body("koln-20250319142607.html")),
            ("20250319142608", file, body("koln-export-20250319142608.json")),
        ],
    )
    read = _only_read(result)
    assert (read.variant, read.rows, read.declared_count) == ("gray-s3-json", 398, 398)
    (hop,) = read.via
    assert (hop.variant, hop.state, hop.declared_count) == (
        "gray-fusion-count",
        ListingState.COUNT_ONLY,
        397,
    )
    assert hop.count_at == datetime(2025, 3, 19, 14, 24, 0, tzinfo=UTC)
    assert hop.count_matches is False
    assert result.failures == []
    assert archive.count_differences(result.reads) == [
        "gray-koln 2025-03-19T14:26:07Z: the page counts 397 as of 2025-03-19T14:24:00Z; "
        "the list captured 128 s later (2025-03-19T14:26:08Z) holds 398"
    ]
    assert [row.raw_name for row in result.rows] == _export_names("koln-export-20250319142608.json")


def test_synthetic_count_made_as_the_list_was_captured_must_match(tmp_path: Path) -> None:
    # The same real bodies, with the export moved (synthetically) to 14:25:00, one
    # minute after the page's count was made: 397 against 398 is now a failure.
    page = "https://www.1011now.com/weather/closings/"
    file = "https://s3.amazonaws.com/grayfilestore-koln/closingsData/closings_KOLN.json"
    result = archive.parse_snapshots(
        load_registry(),
        _artifact(
            tmp_path,
            [
                ("20250319142607", page, body("koln-20250319142607.html")),
                ("20250319142500", file, body("koln-export-20250319142608.json")),
            ],
        ),
    )
    assert len(result.failures) == 1
    assert "the page counts 397" in result.failures[0]


def test_lazy_page_is_followed_to_its_station_export(tmp_path: Path) -> None:
    # gray-fusion-lazy: WBBJ's page (2026-05-05) names no export; the reader follows the
    # station's registered data_url. The only archived WBBJ export was captured
    # 2026-07-18, far outside six hours, so the page stays unread and says why, and
    # the export is read on its own.
    page = "https://www.wbbjtv.com/weather/closings/"
    export = (
        "https://s3.amazonaws.com/grayfilestore-wbbj/closingsData/closings_WBBJ.json"
        "?rnd=418335&arc-site=wbbj"
    )
    empty_export = b'[{"locations":[],"num_closings":0,"export_type":"L1","source":"GSync"}]'
    result = archive.parse_snapshots(
        load_registry(),
        _artifact(
            tmp_path,
            [
                ("20260505153048", page, body("wbbj-20260505153048.html")),
                ("20260718134049", export, empty_export),
            ],
        ),
    )
    by_url = {entry.url: entry for entry in result.health}
    unread = by_url[page]
    assert unread.status is HealthStatus.ERROR
    assert "no list and no count" in (unread.reason or "")
    assert "grayfilestore-wbbj" in (unread.reason or "")
    assert by_url[export].status is HealthStatus.EMPTY


def test_arc_page_framing_a_file_is_read_through_it(tmp_path: Path) -> None:
    # gray-fusion-frame: WFSB's Arc page and the NewsTicker file it frames, both
    # captured 2026-02-23 19:20:16 (the blizzard): 931 rows. The page's own cache
    # entry says totalResults 0; the page does not show it, so it counts nothing.
    page = "https://www.wfsb.com/weather/closings/"
    file = "https://webpubcontent.gray.tv/wfsb/xml/WFSBclosings.html"
    listing = gray.parse(body("wfsb-20260223192016.html"))
    assert (listing.variant, listing.declared_count, listing.follows) == (
        "gray-fusion-frame",
        None,
        (file,),
    )
    result = _followed(
        tmp_path,
        [
            ("20260223192016", page, body("wfsb-20260223192016.html")),
            ("20260223192016", file, body("wfsb-file-20260223192016.html")),
        ],
    )
    read = _only_read(result)
    assert (read.variant, read.rows) == ("gray-file-newsticker", 931)
    (hop,) = read.via
    assert (hop.variant, hop.gap_seconds, hop.count_matches) == ("gray-fusion-frame", 0, None)
    assert [row.raw_name for row in result.rows] == _orgnames("wfsb-file-20260223192016.html")


def test_allen_media_frame_names_its_ftp2_file() -> None:
    listing = gray.parse(body("wlfi-20250124122656.html"))
    assert (listing.variant, listing.follows) == (
        "gray-frame",
        ("https://ftp2.wlfi.com/SC/WLFI_schools.HTM",),
    )


# Pages that write their list in, and the files new this round ------------------------


def test_heartland_page_with_its_sc_list_written_in() -> None:
    listing = gray.parse(body("wlfi-20210217071503.html"))
    assert (listing.variant, listing.state) == ("gray-heartland-sc-para", ListingState.POPULATED)
    names = _bold_names("wlfi-20210217071503.html")
    assert [row.name for row in listing.rows] == names
    assert len(names) == 39
    first, last = listing.rows[0], listing.rows[-1]
    assert (first.name, first.status, first.updated_text) == (
        "Attica Consolidated School Corp.",
        "Closed - Tomorrow E-Learning Day",
        "2:13am on 2/17/2021",
    )
    assert first.extra == {"updated_scope": "page", "group": "Schools"}
    assert (last.name, last.status) == ("West Lafayette Community School Corp.", "2 Hour Delay")


def test_heartland_page_with_a_newsticker_export_written_in() -> None:
    listing = gray.parse(body("wthi-20210131041322.html"))
    assert (listing.variant, listing.state) == ("gray-heartland-newsticker", ListingState.EMPTY)


def test_synthetic_heartland_pages_that_do_not_read() -> None:
    page = body("wlfi-20210217071503.html")
    unclosed = page.replace(b"</div>\n</body>", b"\n</body>")
    with pytest.raises(ShapeError, match="not closed"):
        gray.parse(unclosed)
    button = b">Refresh Data</a></div>"
    other = page.replace(button, button + b"<p>something else</p>").replace(
        b"Last Updated at", b"Updated"
    )
    with pytest.raises(ShapeError):
        gray.parse(other)
    assert gray_legacy.heartland(b"<html>no button</html>") is None
    assert gray_legacy.slice_heartland(b"<html>no button</html>") is None


def test_wlfi_sc_paragraph_file_name_by_name() -> None:
    listing = gray_files.parse(body("wlfi-file-20220201164300.htm"))
    assert listing.variant == "gray-file-sc-para"
    assert [(r.name, r.status, r.updated_text, r.extra) for r in listing.rows] == [
        (
            "Leggett & Platt",
            "Closed Wendesday - Friday C Shift Resumes Production Saturday",
            "11:42am on 2/01/2022",
            {"updated_scope": "page", "group": "Small Business"},
        ),
        (
            "West Lafayette Public Library",
            "Closed Wednesday and Thursday",
            "11:42am on 2/01/2022",
            {"updated_scope": "page", "group": "Government"},
        ),
    ]
    empty = gray_files.parse(body("wlfi-file-20241223230957.htm"))
    assert (empty.variant, empty.state) == ("gray-file-sc-para", ListingState.EMPTY)


def test_synthetic_sc_paragraph_files_that_do_not_read() -> None:
    real = body("wlfi-file-20220201164300.htm")
    with pytest.raises(ShapeError, match="says none"):
        gray_files.parse(real + b"<P>No Closings Reported</P>")
    with pytest.raises(ShapeError, match="no name"):
        gray_files.parse(real.replace(b"<b>Leggett & Platt</b>", b"<b> </b>"))
    with pytest.raises(ShapeError, match="neither a heading nor a row"):
        gray_files.parse(real.replace(b"<br>Closed Wednesday", b"Closed Wednesday"))
    headings_only = b"Last Updated at 1:00am on 1/01/2022\r\n<P><B><h2>---- Schools</h2></B><br>"
    with pytest.raises(ShapeError, match="no rows"):
        gray_files.parse(headings_only)
    assert gray_files.parse_para("Last Updated at 1:00am\n<P>No Closings Reported</P>").rows == ()
    with pytest.raises(ShapeError, match="Last Updated"):
        gray_files.parse_para("<P>No Closings Reported</P>")


def test_cgs_page_reads_its_empty_state_and_refuses_anything_else() -> None:
    listing = gray_files.parse(body("wtva-file-20210318215932.html"))
    assert (listing.variant, listing.state) == ("gray-file-cgs", ListingState.EMPTY)
    real = body("wtva-file-20210318215932.html")
    rows = real.replace(
        b"There are no 'All Active' closings to report.", b"Some School</td><td>Closed"
    )
    with pytest.raises(ShapeError, match="not in its empty state"):
        gray_files.parse(rows)
    with pytest.raises(ShapeError, match="time stamp"):
        gray_files.parse(real.replace(b'<div class="msg">', b"<div>"))


def test_sc_files_with_and_without_an_xml_declaration() -> None:
    wnem = gray_files.parse(body("wnem-sc-20201210023135.xml"))
    assert not body("wnem-sc-20201210023135.xml").startswith(b"<?xml")
    (row,) = wnem.rows
    assert (row.name, row.status, row.updated_text) == (
        "SS.Francis & Clare Birch Run",
        "Masses Canceled due to Covid",
        "12/09/2020 09:32pm",
    )
    assert (row.extra["County"], row.extra["State"], row.extra["Status2"]) == (
        "Saginaw",
        "MI",
        "Events Canceled",
    )
    wsmv = gray_files.parse(body("wsmv-sc-20190203210606.xml"))
    assert [row.name for row in wsmv.rows] == _xml_names(
        "wsmv-sc-20190203210606.xml", "Closing", "Name1"
    )
    assert [row.name for row in wsmv.rows] == ["Smith County Schools"]


def test_western_mass_newsticker_xml_on_the_december_2020_noreaster() -> None:
    listing = gray_files.parse(body("wggb-newsticker-20201217133722.xml"))
    assert (listing.variant, listing.state, listing.declared_count) == (
        "gray-file-newsticker-xml",
        ListingState.POPULATED,
        228,
    )
    names = _xml_names("wggb-newsticker-20201217133722.xml", "RECORD", "FORCED_ORGANIZATION_NAME")
    assert [row.name for row in listing.rows] == names
    assert names[:3] == ["Agawam, Town of", "Chicopee, City of", "East Longmeadow, Town of"]


def test_every_new_list_file_is_kept_whole_as_a_fixture() -> None:
    for name in (
        "wlfi-file-20220201164300.htm",
        "wtva-file-20210318215932.html",
        "wnem-sc-20201210023135.xml",
        "wggb-newsticker-20201217133722.xml",
    ):
        assert gray.slice_page_v4(body(name)) == body(name)
    assert unescape("&amp;") == "&"


class _Cells(HTMLParser):
    """(tab, name, status, second line) of WDBJ's mobile closing cells (stdlib parser)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tabs: dict[str, str] = {}
        self.found: list[tuple[str, str, str, str]] = []
        self._pane = ""
        self._field: str | None = None
        self._link: str | None = None
        self._cell: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if tag == "a" and (found.get("rel") or "").startswith("country"):
            self._link = found["rel"]
        elif tag == "div" and (found.get("class") or "") == "tabcontent":
            self._pane = self.tabs[found.get("id") or ""]
        elif tag == "li" and found.get("id") == "closing_cell":
            self._cell = {}
        elif tag == "div" and (found.get("id") or "").startswith("closing_"):
            self._field = (found.get("id") or "").removeprefix("closing_")
            self._cell[self._field] = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            self._field = None
        elif tag == "a":
            self._link = None
        elif tag == "li" and "name" in self._cell:
            cell = {key: " ".join(value.split()) for key, value in self._cell.items()}
            if not cell["name"].startswith("There are no"):
                row = (self._pane, cell["name"], cell["desc"], cell.get("desc2", ""))
                self.found.append(row)
            self._cell = {}

    def handle_data(self, data: str) -> None:
        if self._link is not None:
            self.tabs[self._link] = data.strip()
        elif self._field is not None:
            self._cell[self._field] += data


def test_wdbj_mobile_page_after_the_january_2016_blizzard() -> None:
    listing = gray_files.parse(body("wdbj-mobile-20160126183408.html"))
    assert (listing.variant, listing.state) == ("gray-file-mobile-cells", ListingState.POPULATED)
    parser = _Cells()
    parser.feed(body("wdbj-mobile-20160126183408.html").decode("utf-8"))
    got = [
        (str(r.extra["tab"]), r.name, r.status, str(r.extra.get("status2", "")))
        for r in listing.rows
    ]
    assert got == parser.found
    assert got[:3] == [
        ("School Closings", "Amherst County Schools", "Closed Wednesday", "Employee Code 1"),
        ("School Closings", "Lynchburg City Schools", "Closed Wednesday", ""),
        (
            "School Closings",
            "Virginia Western Community College",
            "Opening 2 hours late",
            "Opening at 10:00 a.m.",
        ),
    ]
    assert len(got) == 11
    # A blank first line is kept blank; the second line says what is cancelled.
    assert (
        "Other Closings",
        "Church of Holy Spirit - Roanoke",
        "",
        "All Activities Canceled",
    ) in got
    empty = gray_files.parse(body("wdbj-mobile-20160307171830.html"))
    assert (empty.variant, empty.state) == ("gray-file-mobile-cells", ListingState.EMPTY)


def test_synthetic_mobile_pages_that_do_not_read() -> None:
    real = body("wdbj-mobile-20160126183408.html")
    with pytest.raises(ShapeError, match="no name"):
        gray_files.parse(real.replace(b">Amherst County Schools<", b"> <"))
    with pytest.raises(ShapeError, match="lacks its name or its status"):
        gray_files.parse(real.replace(b"id='closing_desc' class='radius'> Closed Wednesday", b">"))
    empty = body("wdbj-mobile-20160307171830.html")
    none_and_rows = empty.replace(
        b"There are no SCHOOL closings</div> <div id='closing_desc' class='radius'> </div></li>",
        b"There are no SCHOOL closings</div> <div id='closing_desc' class='radius'> </div></li>"
        b"<li id='closing_cell'><div id='closing_name'>A</div><div id='closing_desc'>B</div></li>",
    )
    with pytest.raises(ShapeError, match="says there are none"):
        gray_files.parse(none_and_rows)
    with pytest.raises(ShapeError, match="has no name"):
        gray_files.parse(empty.replace(b'rel="country2">Other Closings', b'rel="country3">Other'))


def test_heartland_page_with_a_populated_newsticker_export() -> None:
    listing = gray.parse(body("wthi-20210211052211.html"))
    assert (listing.variant, listing.state) == ("gray-heartland-newsticker", ListingState.POPULATED)
    assert [row.name for row in listing.rows] == _orgnames("wthi-20210211052211.html")
    assert len(listing.rows) == 33
    empty = gray.parse(body("wlfi-20210307095801.html"))
    assert (empty.variant, empty.state) == ("gray-heartland-sc-para", ListingState.EMPTY)
