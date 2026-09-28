"""Part 3b's fixtures: bytes, provenance, and exactly what the adapters read from them.

fixtures/regional/PROVENANCE.json pins each fixture's SHA-256 and the adapter's exact
output (variant, state, row count and every row name); README.md is generated from it
and PROVENANCE.errors.json. Every fixture is a real body (live or archived); the
capture and add commands are exercised against a synthetic server that serves real
fixture bodies.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from snowlight.sources.stations import regional_fixtures
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.fixtures import FixtureEntry, Origin
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import Listing, ListingState, ReadMode, ShapeError
from snowlight.sources.stations.registry import load_registry

FOLDER = regional_fixtures.DEFAULT_FOLDER
ENTRIES = regional_fixtures.load_entries(FOLDER)
ERRORS = regional_fixtures.load_errors(FOLDER)
REGISTRY = load_registry()

VARIANTS = {
    ("sinclair", "sinclair-next-page", ListingState.DEFERRED),
    ("sinclair", "sinclair-chameleon-page", ListingState.DEFERRED),
    ("sinclair", "newsticker-html", ListingState.POPULATED),
    ("sinclair", "newsticker-html", ListingState.EMPTY),
    ("sinclair", "closings-grid", ListingState.EMPTY),
    ("allen", "allen-blox-page", ListingState.DEFERRED),
    ("allen", "newsticker-html", ListingState.EMPTY),
    ("allen", "allen-header-table", ListingState.EMPTY),
    ("allen", "cgs-all-active", ListingState.EMPTY),
    ("allen", "allen-counter", ListingState.EMPTY),
    ("cox", "cox-arc-content", ListingState.EMPTY),
    ("cox", "cox-arc-page", ListingState.EMPTY),
    ("graham", "graham-arc-content", ListingState.EMPTY),
    ("graham", "graham-arc-page", ListingState.EMPTY),
    ("heritage", "heritage-arc-content", ListingState.EMPTY),
    ("heritage", "heritage-arc-page", ListingState.EMPTY),
    ("hubbard", "hubbard-schoolalert", ListingState.EMPTY),
    ("hubbard", "hubbard-page", ListingState.DEFERRED),
    ("wtop", "wtop-page", ListingState.EMPTY),
    ("whdh", "whdh-closings-block", ListingState.EMPTY),
    ("whdh", "whdh-closings-block", ListingState.POPULATED),
    ("spectrum", "spectrum-json", ListingState.EMPTY),
    ("spectrum", "spectrum-page", ListingState.DEFERRED),
    ("news12", "news12-jsp", ListingState.POPULATED),
    ("news12", "news12-jsp", ListingState.EMPTY),
    ("townsquare", "townsquare-closings-table", ListingState.EMPTY),
    ("townsquare", "townsquare-page", ListingState.DEFERRED),
    ("delaware", "delaware-portal-xml", ListingState.EMPTY),
    ("wveis", "wveis-rss", ListingState.EMPTY),
    ("wveis", "wveis-page", ListingState.EMPTY),
    ("ncpr", "ncpr-storm-page", ListingState.EMPTY),
    ("newsticker", "newsticker-html", ListingState.POPULATED),
    ("wral", "wral-api", ListingState.EMPTY),
    ("wral", "wral-app-page", ListingState.DEFERRED),
    ("lockwood", "lockwood-json", ListingState.EMPTY),
    ("eventdelay", "eventdelay-widget", ListingState.EMPTY),
    ("eventdelay", "eventdelay-list", ListingState.EMPTY),
    ("eventdelay", "eventdelay-page", ListingState.DEFERRED),
    ("weatherthreat", "weatherthreat-js", ListingState.EMPTY),
    ("blox", "blox-script-page", ListingState.DEFERRED),
    ("blox", "blox-frame-page", ListingState.DEFERRED),
    ("blox", "blox-closings-cards", ListingState.POPULATED),
    ("blox", "blox-weather-closings", ListingState.EMPTY),
    ("santacruzcoe", "santacruzcoe-page", ListingState.DEFERRED),
    ("santacruzcoe", "santacruzcoe-widget", ListingState.DEFERRED),
    ("santacruzcoe", "santacruzcoe-sheet", ListingState.EMPTY),
    ("hcoe", "hcoe-alerts-posts", ListingState.POPULATED),
    ("hcoe", "hcoe-alerts-feed", ListingState.POPULATED),
}
# Variants seen populated only in storm-day captures (archive-captures run 36299187602).
ARCHIVED_VARIANTS = {
    ("sinclair", "closings-grid", ListingState.POPULATED),
    ("allen", "newsticker-html", ListingState.POPULATED),
    ("allen", "allen-header-table", ListingState.POPULATED),
    ("cox", "cox-arc-page", ListingState.POPULATED),
    ("graham", "graham-arc-page", ListingState.POPULATED),
    ("wtop", "wtop-page", ListingState.POPULATED),
    ("spectrum", "spectrum-json", ListingState.POPULATED),
    ("sinclair", "sinclair-facade-page", ListingState.DEFERRED),
    # Archive-captures run 36317643857 (round 2a):
    ("lockwood", "lockwood-json", ListingState.POPULATED),
    ("ncpr", "ncpr-storm-page", ListingState.POPULATED),
    ("wveis", "wveis-rss", ListingState.POPULATED),
    ("townsquare", "townsquare-closings-table", ListingState.POPULATED),
    ("news12", "news12-jsp", ListingState.POPULATED),
    ("spectrum", "spectrum-json", ListingState.POPULATED),
    ("blox", "sinclair-next-page", ListingState.DEFERRED),
    ("blox", "sinclair-frame-page", ListingState.DEFERRED),
    # Archive-captures run 36324857670 (round 2e):
    ("hubbard", "hubbard-schoolalert", ListingState.POPULATED),
    ("hubbard", "hubbard-frame-page", ListingState.DEFERRED),
    ("delaware", "delaware-portal-xml", ListingState.POPULATED),
    ("delaware", "delaware-page", ListingState.DEFERRED),
    ("heritage", "heritage-arc-content", ListingState.POPULATED),
    ("heritage", "heritage-arc-page", ListingState.POPULATED),
    ("heritage", "heritage-bti-table", ListingState.POPULATED),
    ("wral", "wral-page-table", ListingState.POPULATED),
    ("wveis", "wveis-page", ListingState.POPULATED),
    ("blox", "blox-cgs-xml", ListingState.POPULATED),
    ("weatherthreat", "weatherthreat-js", ListingState.POPULATED),
    ("sinclair", "chameleon-json", ListingState.POPULATED),
    # Archive-captures run 36324857670, WDEL's SnoWatch page before EventDelay:
    ("eventdelay", "eventdelay-page", ListingState.DEFERRED),
    # Archive-captures run 36345392102 (round 2i): the SnoWatch list and WHEC's files.
    ("eventdelay", "snowatch-index", ListingState.EMPTY),
    ("eventdelay", "snowatch-index", ListingState.DEFERRED),
    ("eventdelay", "snowatch-category", ListingState.POPULATED),
    ("hubbard", "hubbard-banner", ListingState.COUNT_ONLY),
    # Archive-captures run 36347638809 (round 2j): KATV's and WBFF's earlier files.
    ("sinclair", "allen-header-table", ListingState.POPULATED),
    ("sinclair", "allen-header-table", ListingState.EMPTY),
    ("sinclair", "closings-paragraphs", ListingState.POPULATED),
    ("sinclair", "closings-paragraphs", ListingState.EMPTY),
    # Archive-captures run 36349462045 (round 2k): pages of WCIV, KXLY and KNEB.
    ("sinclair", "sinclair-frame-page", ListingState.DEFERRED),
    ("blox", "heritage-bti-table", ListingState.POPULATED),
    ("blox", "heritage-bti-table", ListingState.EMPTY),
    ("weatherthreat", "weatherthreat-banner", ListingState.POPULATED),
    ("weatherthreat", "weatherthreat-page", ListingState.DEFERRED),
    # Archive-captures run 36352967678 (round 3a): WDEL's list-mode widget on the storm
    # days of January 2025 and the station page that framed it.
    ("eventdelay", "eventdelay-list", ListingState.POPULATED),
    ("eventdelay", "eventdelay-list", ListingState.EMPTY),
    ("eventdelay", "eventdelay-widget", ListingState.EMPTY),
    # Runs 36354877675 and 36357297115 (rounds 3b, 3c): KXXO's page and the FlashAlert
    # report it frames (the site does not answer from the build environment).
    ("radio", "kxxo-page", ListingState.DEFERRED),
    ("radio", "flashalert-copy", ListingState.POPULATED),
    ("radio", "flashalert-copy", ListingState.EMPTY),
    ("santacruzcoe", "santacruzcoe-page", ListingState.DEFERRED),
    ("hcoe", "hcoe-alerts-posts", ListingState.POPULATED),
    ("hcoe", "hcoe-alerts-feed", ListingState.POPULATED),
    # Run 36363837899 (round 4b): KIMT's file as a CGS page with entries (2020 to 2024).
    ("allen", "cgs-all-active", ListingState.POPULATED),
}


def test_every_variant_seen_live_has_a_fixture() -> None:
    seen = {(e.adapter, e.expected.variant, e.expected.state) for e in ENTRIES}
    assert seen >= VARIANTS
    archived = {
        (e.adapter, e.expected.variant, e.expected.state)
        for e in ENTRIES
        if e.mode is ReadMode.ARCHIVE
    }
    assert archived >= ARCHIVED_VARIANTS


@pytest.mark.parametrize("entry", ENTRIES, ids=[entry.file for entry in ENTRIES])
def test_fixture_matches_its_provenance(entry: FixtureEntry) -> None:
    body = (FOLDER / entry.file).read_bytes()
    assert hashlib.sha256(body).hexdigest() == entry.sha256
    assert len(body) == entry.bytes
    listing = adapter_for(entry.adapter)(body)
    assert listing.variant == entry.expected.variant
    assert listing.state is entry.expected.state
    assert tuple(row.name for row in listing.rows) == entry.expected.names
    assert len(listing.rows) == entry.expected.rows
    assert regional_fixtures.SLICERS[entry.slice](body) == body
    station = REGISTRY.stations[entry.source_id]
    assert REGISTRY.platform_of(station).adapter == entry.adapter
    assert entry.file.split("/", 1)[0] == entry.adapter
    if entry.mode is ReadMode.LIVE:
        assert entry.archive_url is None
        assert entry.captured_at == entry.retrieved_at
    else:
        assert entry.mode is ReadMode.ARCHIVE
        assert entry.archive_url == (
            f"https://web.archive.org/web/{entry.captured_at:%Y%m%d%H%M%S}id_/{entry.url}"
        )
        assert entry.retrieved_at > entry.captured_at


def test_readme_is_generated_from_the_provenance() -> None:
    readme = (FOLDER / "README.md").read_text()
    assert readme == regional_fixtures.render_readme(ENTRIES, ERRORS)


@pytest.mark.parametrize("item", ERRORS, ids=[item.file for item in ERRORS])
def test_refused_bodies_are_refused(item: regional_fixtures.ErrorFixture) -> None:
    body = (FOLDER / item.file).read_bytes()
    assert hashlib.sha256(body).hexdigest() == item.sha256
    with pytest.raises(ShapeError):
        adapter_for(item.adapter)(body)


def test_exact_rows_of_live_populated_lists() -> None:
    def rows(file: str, adapter: str) -> list[tuple[str, str]]:
        listing = adapter_for(adapter)((FOLDER / file).read_bytes())
        return [(row.name, row.status) for row in listing.rows]

    assert rows("sinclair/wcti-live-20260927.html", "sinclair") == [
        ("ARAPAHOE CHARTER", "Closed to Students; Staff Remote Work Day"),
        ("HYDE COUNTY SCHOOL SYSTEM", "Remote Learning Day for Ocracoke School ONLY"),
        ("PAMLICO COMMUNITY COLLEGE", "Opening at 10 a.m. Friday"),
    ]
    assert rows("sinclair/wtvc-live-20260927.html", "sinclair") == [
        (
            "Sequatchie Co. Schools",
            "Dismissing early; Thursday and Friday early dismissal car riders at 11:30 buses "
            "at 11:40",
        )
    ]
    wwmt = adapter_for("sinclair")((FOLDER / "sinclair/wwmt-live-20260927.html").read_bytes())
    assert wwmt.rows[0].name == "KENT Michigan Works in Kent Co"
    assert wwmt.rows[0].extra["homepage"] == "http://http://www.westmiworks.org"
    riba = adapter_for("newsticker")((FOLDER / "newsticker/riba-live-20260927.html").read_bytes())
    assert riba.rows[0].extra == {
        "updated_scope": "page",
        "group": "COMMUNITY GROUPS",
        "location": "Providence",
    }
    news12 = adapter_for("news12")((FOLDER / "news12/li-live-20260927.html").read_bytes())
    assert news12.rows[3].name == "Suffolk Community College"
    assert news12.rows[3].extra["city"] == "Selden"
    assert rows("blox/wrde-live-20260927.html", "blox")[0][0] == "ATLANTIC UMC OCEAN CITY"
    assert rows("news12/wc-live-20260927.html", "news12") == [
        ("Westchester Community College", "Delayed start at 10:00 AM")
    ]
    assert rows("whdh/whdh-live-20260927-1350.html", "whdh") == [
        ("Cong.Sha'Aray Shalom", "Current Status: Closed Today")
    ]


def test_exact_rows_of_archived_populated_lists() -> None:
    def read(file: str, adapter: str) -> Listing:
        return adapter_for(adapter)((FOLDER / file).read_bytes())

    wsb = read("cox/wsb-page-20250110.html", "cox")
    assert (len(wsb.rows), wsb.declared_count) == (222, 222)
    assert wsb.declared_at == datetime(2025, 1, 10, 11, 54, 47, tzinfo=UTC)
    first = wsb.rows[0]
    assert (first.name, first.status, first.updated_text) == (
        "ABC-Another Bright Creation Douglasville",
        "Closed Today",
        None,
    )
    assert first.extra == {
        "county": None,
        "status_code": "1",
        "status_code_display": "Closed",
        "comments": "Closed Today",
        "start_date": "Jan 10",
        "end_date": "Jan 10",
    }
    wpxi = read("cox/wpxi-page-20250104.html", "cox")
    assert [(row.name, row.status) for row in wpxi.rows][2] == (
        "Uniontown Area School District",
        "No Transportation Services",
    )
    kiro = read("cox/kiro-page-20260219.html", "cox")
    assert kiro.rows[1].name == "Port Angeles SD"
    assert kiro.rows[1].extra["status_code"] is None
    wdiv = read("graham/wdiv-page-20250212.html", "graham")
    bethany = wdiv.rows[1]
    assert (bethany.name, bethany.status, bethany.updated_text) == (
        "Bethany Christian",
        "Closed Thu",
        "2025-02-12 12:26:51",
    )
    assert bethany.extra["name_two"] is None
    assert bethany.extra["county"] == "Oakland"
    assert bethany.extra["updated_zone"] == "UTC"
    wsls = read("graham/wsls-page-20250211.html", "graham")
    assert (wsls.rows[0].name, wsls.rows[0].status, wsls.rows[0].updated_text) == (
        "Adult Care Center-Roanoke",
        "Closed Tuesday",
        "2/10/2025 5:28:51 PM",
    )
    assert wsls.rows[0].extra["status_two_name_one"] == (
        "Schools: Adult Care Center-Roanoke - Closed Tuesday"
    )
    wtop = read("wtop/wtop-20260303.html", "wtop")
    fairfax = wtop.rows[0]
    assert (fairfax.name, fairfax.status, fairfax.updated_text) == (
        "Fairfax County Public Schools",
        "2 Hour Delay on Tuesday 3/3",
        "2026-03-03 00:41:38",
    )
    assert fairfax.extra["state_code"] == "VA"
    assert fairfax.extra["org_city"] == "Falls Church"
    storm = read("wtop/wtop-20250106.html", "wtop")
    # Two postings name WTOP's placeholder organization ("Unknown organization").
    assert (len(storm.rows), storm.skipped_rows) == (217, 2)
    assert "Unknown" not in {row.name for row in storm.rows}
    kimt = read("allen/kimt-20260317.html", "allen")
    assert [(row.name, row.status) for row in kimt.rows][-1] == ("West Hancock", "Delayed 2 hours")
    assert kimt.rows[0].updated_text == "March 16, 2026 10:35 pm CDT"
    wcyb = read("sinclair/wcyb-20260223.html", "sinclair")
    assert (wcyb.rows[0].name, wcyb.rows[0].status, wcyb.rows[0].updated_text) == (
        "BUCHANAN CO. SCHOOLS",
        "Virtual Learning",
        "12:10am on 2/23/2026",
    )
    wkrc = read("sinclair/wkrc-20260126.html", "sinclair")
    assert (len(wkrc.rows), wkrc.rows[-1].name) == (438, "Zion Temple Christian Academy")
    syracuse = read("spectrum/syracuse-20241204.json", "spectrum")
    assert (syracuse.rows[0].name, syracuse.rows[0].status) == (
        "Adirondack CSD",
        "No Afterschool Activities",
    )


def test_exact_rows_of_lists_first_read_in_round_two() -> None:
    # Storm-day captures of archive-captures run 36317643857: the first lists with rows
    # seen from WCAV's Lockwood file, NCPR's page, the WVEIS feed and NJ 101.5's file.
    def read(file: str, adapter: str) -> Listing:
        return adapter_for(adapter)((FOLDER / file).read_bytes())

    wcav = read("lockwood/wcav-20260127.json", "lockwood")
    assert (len(wcav.rows), wcav.declared_count) == (17, 17)
    first = wcav.rows[1]
    assert (first.name, first.status, first.updated_text) == (
        "Madison County Public Schools",
        "Closed Wednesday, 12-Month Employees Code 2",
        "01-27-2026 at 12:40 pm",
    )
    assert first.extra["category_name"] == "Schools - Public"
    assert wcav.rows[-1].name == "Virginia National Bank"
    ncpr = read("ncpr/storm-20241216.html", "ncpr")
    assert [(r.name, r.status, r.extra.get("details")) for r in ncpr.rows] == [
        (
            "Corinth Central School District, Corinth, NY",
            "2 Hour Delay (Monday)",
            "No morning BOCES. No breakfast.",
        )
    ]
    assert ncpr.rows[0].updated_text == "Last updated Monday, December 16th, 2024 at 9:31 am"
    wv = read("wveis/statewide-20260129.xml", "wveis")
    assert len(wv.rows) == 55
    assert (wv.rows[0].name, wv.rows[0].status, wv.rows[0].updated_text) == (
        "All schools in Marion County",
        "As of Jan 28, 11:08am: All schools in Marion County will be non-traditional learning"
        " on Thu. Jan. 29, 2026 due to Weather.",
        "Wed, 28 Jan 2026 11:08:31 -0500",
    )
    assert wv.rows[0].extra == {
        "link": "https://wveis.k12.wv.us/closings/county.php?id=47",
        "guid": "11677-1769616511",
    }
    nj = read("townsquare/wkxw-20251227.html", "townsquare")
    assert [(r.name, r.status, r.updated_text) for r in nj.rows] == [
        (
            "Amboy Bank-Old Bridge",
            "All Branches will be closed Saturday Dec 27",
            "11:30pm on 12/26/2025",
        )
    ]
    assert nj.rows[0].extra == {
        "updated_scope": "page",
        "city": "Old Bridge",
        "message": "Due to weather. Normal hours on Monday Dec 29",
        "group": "Middlesex County",
    }
    wham = read("sinclair/wham-20240229.html", "sinclair")
    assert (len(wham.rows), wham.rows[0].name, wham.rows[0].extra["group"]) == (
        11,
        "Candy Apple Childrens Ctr",
        "County",
    )
    # WZTV's report.html was a NewsTicker export before it became a Chameleon page.
    wztv = read("sinclair/wztv-20230131.html", "sinclair")
    assert (len(wztv.rows), wztv.rows[0].name, wztv.rows[0].status) == (
        31,
        "Austin Peay State University",
        "CLOSED",
    )
    krcg = read("sinclair/krcg-20250206.html", "sinclair")
    assert [(r.name, r.status, r.extra.get("comment")) for r in krcg.rows] == [
        ("Crocker R-II Schools", "Closed Friday", "Classes Canceled"),
        ("Jamestown C-1", "Closed Thursday", "AMI Day"),
        ("First Assembly of God Fulton", "Closed Wednesday", None),
    ]
    assert len(read("news12/nj-20260223.html", "news12").rows) == 213
    austin = read("spectrum/austin-20260127.json", "spectrum")
    assert (len(austin.rows), austin.rows[0].name, austin.rows[0].status) == (
        37,
        "IDEA Public Schools",
        "Closed on Tuesday",
    )


def test_exact_rows_of_lists_first_read_in_round_two_e() -> None:
    # Captures of archive-captures run 36324857670: the first lists with rows seen from
    # Hubbard's School Alert file, Delaware's PortalFeed, 9&10's Arc source, WRAL's and
    # WVEIS's pages, a CGS Mercury export, WeatherThreat's script and a Chameleon query.
    def rows(file: str, adapter: str) -> list[tuple[str, str, str | None]]:
        listing = adapter_for(adapter)((FOLDER / file).read_bytes())
        return [(r.name, r.status, r.updated_text) for r in listing.rows]

    assert rows("hubbard/kstp-20250403.html", "hubbard") == [
        ("ASHBY PUBLIC SCHOOL DISTRICT", "E Learning Thursday April 3", "2025-04-03 13:36:14"),
        ("CLINTON-GRACEVILLE-BEARDSLEY", "E Learning Day", "2025-04-03 13:36:14"),
        ("DAWSON-BOYD", "E-Learning Day Daycare open 8 am - 4 pm.", "2025-04-03 13:36:14"),
        ("NEW YORK MILLS PUBLIC SCHOOLS", "eLearning Day", "2025-04-03 13:36:14"),
    ]
    delaware = rows("delaware/doe-20190220.xml", "delaware")
    assert (len(delaware), delaware[0]) == (
        185,
        (
            "ALFRED G. WATERS MIDDLE SCHOOL",
            "Feb. 20: ASD Schools/Offices will be closed",
            "02/19/2019 19:37:30",
        ),
    )
    live = adapter_for("delaware")((FOLDER / "delaware/doe-live-20260928.xml").read_bytes())
    assert [(r.name, r.status, r.updated_text, r.extra) for r in live.rows] == [
        (
            "Indian River School District CLosed on Monday",
            "Due to inclement weather, all Indian River School District schools will be closed"
            " on Monday, September 28. Students are NOT required to participate in remote"
            " learning activities. Administrators, custodians and 12-month non-instructional"
            " support specialists should report two hours late. All other employees, including"
            " administrative assistants, should not report to work.",
            "Sun, 27 Sep 2026 23:22:37 GMT",
            {
                "district": "Indian River School District CLosed on Monday",
                "note": "Sun, 27 Sep 2026 23:22:37 GMT",
                "cell_5": "https://rss.finalsiteconnect.com/197765/DEEDU/79164771.xml",
                "id": "1",
                "updated_scope": "row",
            },
        )
    ]
    assert live.declared_count == 1
    content = rows("heritage/wwtv-content-20230207.json", "heritage")
    assert (len(content), content[0]) == (
        130,
        ("Alanson Public Schools", "Closed", "02/07/2023 05:19am"),
    )
    assert len(rows("heritage/wwtv-page-20241212.html", "heritage")) == 40
    assert rows("heritage/wwtv-page-20210205.html", "heritage")[1] == (
        "Bay Mills Medical Center",
        "Opening at 10:00 AM - 2/5",
        "02/04/2021 09:55pm",
    )
    wral = rows("wral/wral-page-20210217.html", "wral")
    assert (len(wral), wral[:2]) == (
        111,
        [
            ("Access Healthcare of Apex", "Opening Later", None),
            ("Alamance Burlington Schools", "Closed", None),
        ],
    )
    assert rows("wveis/statewide-page-20250105.html", "wveis")[0] == (
        "Berkeley",
        "Closings: All; Delays: None; Dismissals: None; Non-traditional: None; Bus info: None",
        "Jan 5, 2:23pm",
    )
    assert rows("wveis/private-page-20260223.html", "wveis")[0] == (
        "Boone: Christian Faith Academy",
        "Closed: Yes; Delayed: No; Early out: None",
        "Feb 23, 4:34am",
    )
    koam = rows("blox/koam-cgs-20230201.xml", "blox")
    assert (len(koam), koam[0]) == (
        24,
        ("BEARSKIN HEALTH CLINIC", "Closed Monday", "1/30/2023 7:24:21 AM"),
    )
    ntv = rows("weatherthreat/ntv-20210214.js", "weatherthreat")
    assert (len(ntv), ntv[1]) == (
        44,
        (
            "YORK FIRST UMC",
            "Closed Sunday - No in person worship- video available",
            "updated 02/14 02:43 Central",
        ),
    )
    assert [r[0] for r in rows("sinclair/wztv-chameleon-20250131.json", "sinclair")] == [
        "Heritage Christian Academy KY",
        "Lewis County Schools",
    ]


def test_exact_rows_of_lists_first_read_in_round_two_f() -> None:
    # Captures of archive-captures run 36338052203: School Alert files of four more
    # Hubbard stations, NCPR's page under several headings, NJ 101.5's file of 2015 and
    # the NewsTicker files of Sinclair and Allen stations never seen with a row before.
    def rows(file: str, adapter: str) -> list[tuple[str, str]]:
        listing = adapter_for(adapter)((FOLDER / file).read_bytes())
        return [(r.name, r.status) for r in listing.rows]

    wdio = rows("hubbard/wdio-20260123.html", "hubbard")
    assert (len(wdio), wdio[0]) == (
        67,
        ("Aitkin Public Schools", "CLOSED - 1/23 E-LEARNING, NO KIDS CLUB OR WRAP AROUND"),
    )
    wnyt = rows("hubbard/wnyt-20250209.html", "hubbard")
    assert (len(wnyt), wnyt[0]) == (
        106,
        (
            "Abounding Grace Christian Church, Schenectady County, NY",
            "Closed, Service Cancelled see website for previous services",
        ),
    )
    assert rows("hubbard/kaal-20250213.html", "hubbard") == [
        ("First Baptist Church - Forest City", "Activities Canceled"),
        ("North Union Community Schools", "Opening 2 Hrs late"),
    ]
    assert rows("hubbard/kob-20250307.html", "hubbard")[:2] == [
        ("Ch'ooshgai Community School", "2 Hour Delay"),
        ("City of Gallup Municipal Court", "Open at 9 a.m."),
    ]
    ncpr = rows("ncpr/storm-20250206.html", "ncpr")
    assert (len(ncpr), ncpr[0]) == (54, ("Adirondack Christian School, Wilmington, NY", "Closed"))
    assert {status for _name, status in ncpr} >= {"Early Dismissal", "2 Hour Delay (Thursday)"}
    nj = rows("townsquare/wkxw-20150305.html", "townsquare")
    assert (len(nj), nj[0][0]) == (185, "ESTELL MANOR PUBLIC SCHOOLS")
    assert rows("sinclair/wtov-20250129.html", "sinclair")[0][0] == "HANCOCK COUNTY SCHOOLS"
    assert len(rows("sinclair/wgme-20250206.html", "sinclair")) == 223
    assert len(rows("sinclair/wjac-20241216.html", "sinclair")) == 67
    assert rows("sinclair/wjla-20250108.html", "sinclair")[0][0] == "AL-HUDA SCHOOL"
    assert rows("allen/waow-20221219.html", "allen")[0][0] == (
        "Minocqua-Hazelhurst-Lake Tomahwak School District"
    )
    # WCIV's list at its earlier address (not the file the page frames today).
    wciv = rows("sinclair/wciv-20170910.html", "sinclair")
    assert (len(wciv), wciv[0][0]) == (49, "Ashley Oaks OBGYN")


def test_exact_rows_of_lists_first_read_in_round_four() -> None:
    def read(file: str) -> Listing:
        return adapter_for("allen")((FOLDER / file).read_bytes())

    cgs = read("allen/kimt-cgs-20230223.html")
    assert (cgs.variant, len(cgs.rows)) == ("cgs-all-active", 90)
    schools = [(r.name, r.status) for r in cgs.rows if r.extra["category"] == "Schools"]
    assert len(schools) == 60
    assert schools[:3] == [
        ("AGWSR", "2 Hour Delay - No AM preschool"),
        ("Albert Lea", "Closed - E-learning day"),
        ("Belmond-Klemme", "2 Hour Delay"),
    ]
    assert {r.updated_text for r in cgs.rows} == {"2/23/2023 12:08:31 AM"}
    assert [len(read(f"allen/kimt-cgs-{day}.html").rows) for day in ("20200327", "20221221")] == [
        85,
        61,
    ]
    later = read("allen/kimt-20260122.html")
    assert (later.variant, len(later.rows), later.rows[0].updated_text) == (
        "allen-header-table",
        61,
        "January 22, 2026 5:15 pm CST",
    )
    wkow = adapter_for("allen")((FOLDER / "allen/wkow-20221210.html").read_bytes())
    assert [r.name for r in wkow.rows][:3] == [
        "Aging and Disability Resource Center Columbia County",
        "Cuba City Schools",
        "Madison Public Schools",
    ]


def test_pages_name_the_files_they_load() -> None:
    def follows(file: str, adapter: str) -> tuple[str, ...]:
        return adapter_for(adapter)((FOLDER / file).read_bytes()).follows

    assert follows("sinclair/wham-page-live-20260927.html", "sinclair") == (
        "/resources/ftptransfer/wham/closings/closings.html",
    )
    assert follows("sinclair/wbff-page-live-20260927.html", "sinclair") == (
        "https://ftptransfer.sinclairstoryline.com/wbff/closings/closings.html",
    )
    display = follows("sinclair/katv-display-live-20260927.html", "sinclair")
    assert display[0].startswith("https://ticker.news.sinclairinc.cloud/chameleon/blade/query/28/")
    assert follows("allen/kwwl-page-live-20260927.html", "allen") == (
        "https://ftp2.kwwl.com/closings.html",
    )
    assert follows("hubbard/kstp-page-live-20260927.html", "hubbard") == (
        "/wp-content/uploads/dynamic-assets/schoolalert.html",
    )
    assert follows("spectrum/albany-page-live-20260927.html", "spectrum") == (
        "/services/closings.54e4ffc9ceafc43649b4dae9.json",
    )
    assert follows("wral/wral-page-live-20260927.html", "wral") == (
        "https://api.wral.com/closings/v1/",
    )
    assert follows("blox/koam-page-live-20260927.html", "blox") == (
        "/app/closings/KOAM-closingsC.xml",
    )
    # The embed's html as a reference to a text chunk of the page's server stream;
    # the frames inside an HTML comment there are not read.
    assert follows("sinclair/wcti-page-20260311.html", "sinclair") == (
        "https://wcti12.com/resources/ftptransfer/wcti/closings/closings.html",
    )
    # The list file's frame, not the sign-up form framed before it.
    assert follows("sinclair/ktul-page-20260125.html", "sinclair") == (
        "/resources/ftptransfer/ktul/closings/closings.html",
    )
    # The Sinclair partner stations' pages while Sinclair ran them.
    assert follows("blox/khqa-page-20250211.html", "blox") == (
        "/resources/ftptransfer/khqa/closings/closings01.htm",
    )
    assert follows("blox/wrsp-page-20260126.html", "blox") == (
        "/resources/ftptransfer/wics/closings/closings.html",
    )
    assert follows("hubbard/kstp-page-20220218.html", "hubbard") == (
        "/wp-content/uploads/wx/schoolalert.html",
    )
    assert follows("delaware/doe-page-20260223.html", "delaware") == ("/XML/PortalFeed",)
    assert follows("sinclair/wham-page-20220204.html", "sinclair") == (
        "/resources/ftptransfer/wham/closings/closings.html",
    )
    # The 2025 page shell: the frame is in its facade's base64 injected markup.
    assert follows("sinclair/wstm-page-20251202.html", "sinclair") == (
        "/resources/ftptransfer/wstm/closings/closings.htm",
    )


class Ticker:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 27, 7, 0, tzinfo=UTC)
        self.mono = 0.0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


def test_capture_and_add_commands(tmp_path: Path) -> None:
    body = (FOLDER / "sinclair/wach-live-20260927.html").read_bytes()
    url = "https://wach.com/resources/ftptransfer/wach/closings/closings.html"

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, content=b"User-agent: *\nDisallow: /resources/ftptransfer/\n"
            )
        if str(request.url) == url:
            return httpx.Response(200, content=body)
        return httpx.Response(403)

    ticker = Ticker()
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(serve), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )
    out = tmp_path / "log"
    assert (
        regional_fixtures.main(["capture", "--out", str(out), url, url + "?x"], client=client) == 0
    )
    lines = [json.loads(line) for line in (out / "captures.jsonl").read_text().splitlines()]
    assert lines[0]["robots"][0][2] is False  # recorded: robots.txt disallows the file
    assert lines[1]["status"] == 403
    folder = tmp_path / "fixtures"
    log = str(out / "captures.jsonl")
    common = ["--log", log, "--url", url, "--source", "sinclair-wach", "--folder", str(folder)]
    assert (
        regional_fixtures.main(
            ["add", *common, "--file", "sinclair/a.html", "--slice", "sinclair-v1"]
        )
        == 0
    )
    (entry,) = regional_fixtures.load_entries(folder)
    assert (entry.expected.variant, entry.expected.rows) == ("newsticker-html", 1)
    assert "sinclair/a.html" in (folder / "README.md").read_text()
    # A body the adapter reads is not a refused body.
    refused = ["add-error", *common, "--file", "errors/a.html", "--reason", "x"]
    assert regional_fixtures.main(refused) == 1
    missing = ["add", "--log", log, "--url", url + "?y", "--source", "sinclair-wach"]
    assert regional_fixtures.main([*missing, "--file", "sinclair/b.html"]) == 1


def test_make_entry_refuses_a_slice_that_reads_differently() -> None:
    body = (FOLDER / "sinclair/wach-live-20260927.html").read_bytes()
    origin = Origin(
        source_id="sinclair-wach",
        adapter="sinclair",
        mode=ReadMode.LIVE,
        url="https://wach.com/resources/ftptransfer/wach/closings/closings.html",
        captured_at="2026-09-27T07:05:07Z",
        archive_url=None,
        retrieved_at="2026-09-27T07:05:07Z",
    )
    saved = regional_fixtures.SLICERS
    try:
        regional_fixtures.SLICERS = {**saved, "none": lambda _b: b"<html></html>"}
        with pytest.raises(ShapeError):
            regional_fixtures.make_entry("sinclair/x.html", origin, body, "none")
    finally:
        regional_fixtures.SLICERS = saved


def test_add_archived_and_add_error_commands(tmp_path: Path) -> None:
    # A SYNTHETIC artifact folder in the workflow's layout, holding a real body (the
    # WACH file read live), to exercise the command's bookkeeping.
    body = (FOLDER / "sinclair/wach-live-20260927.html").read_bytes()
    url = "https://wach.com/resources/ftptransfer/wach/closings/closings.html"
    snapshots = tmp_path / "artifacts" / "snapshots-1" / "snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / "a.html").write_bytes(body)
    record = {
        "timestamp": "20250122120000",
        "url": url,
        "requested": f"https://web.archive.org/web/20250122120000id_/{url}",
        "retrieved_at": "2026-09-27T09:00:00Z",
        "final_timestamp": "20250122113000",
        "final_original": url,
        "http_status": 200,
        "file": "snapshots/a.html",
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    (snapshots / "manifest.jsonl").write_text(json.dumps(record) + "\n")
    folder = tmp_path / "fixtures"
    args = ["--artifacts", str(tmp_path / "artifacts"), "--timestamp", "20250122120000"]
    args += ["--url", url, "--source", "sinclair-wach", "--folder", str(folder)]
    assert regional_fixtures.main(["add-archived", *args, "--file", "sinclair/b.html"]) == 0
    (entry,) = regional_fixtures.load_entries(folder)
    assert entry.archive_url == f"https://web.archive.org/web/20250122113000id_/{url}"
    assert entry.mode is ReadMode.ARCHIVE
    # The same capture is not a refused body; a missing one is an error.
    assert (
        regional_fixtures.main(
            ["add-archived-error", *args, "--file", "errors/b.html", "--reason", "x"]
        )
        == 1
    )
    wrong = [*args[:3], "20250122120001", *args[4:]]
    assert regional_fixtures.main(["add-archived", *wrong, "--file", "sinclair/c.html"]) == 1
    # A capture whose body is not the manifest's is refused.
    (snapshots / "a.html").write_bytes(body + b" ")
    assert regional_fixtures.main(["add-archived", *args, "--file", "sinclair/d.html"]) == 1
    # A real refused body: KYUU-LD's empty file, logged as a capture.
    log = tmp_path / "log"
    log.mkdir()
    (log / "e.body").write_bytes(b"")
    empty = {
        "url": "https://cwtreasurevalley.com/resources/ftptransfer/kboi/closings/closings.html",
        "fetched_at": "2026-09-27T07:06:23Z",
        "sha256": hashlib.sha256(b"").hexdigest(),
        "file": "e.body",
    }
    (log / "captures.jsonl").write_text(json.dumps(empty) + "\n")
    refused = ["add-error", "--log", str(log / "captures.jsonl"), "--url", empty["url"]]
    refused += ["--source", "sinclair-kyuu-ld", "--folder", str(folder), "--file", "errors/e.html"]
    assert regional_fixtures.main([*refused, "--reason", "empty body"]) == 0
    (item,) = regional_fixtures.load_errors(folder)
    assert (item.adapter, item.bytes, item.archive_url) == ("sinclair", 0, None)
    readme = (folder / "README.md").read_text()
    assert "errors/e.html" in readme
    assert "empty body" in readme
