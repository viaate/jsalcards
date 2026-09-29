"""The proof gate: a district's alert channel is proven only by a closing notice, a status
board only by a status other than open.

The texts below are real rows of this part's sources (live reads of 2026-09-27 and
archived storm-day captures; the fixtures named are in fixtures/gaps/, and every
populated fixture of a gated source is checked against its pinned verdict). Texts,
proofs, rows files and names marked ``SYNTHETIC`` are made up here, confined to
these tests.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from snowlight.output import JSONValue
from snowlight.sources.stations import notices
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures"
GAPS = FIXTURES / "gaps"
REGISTRY = load_registry()

CLOSINGS = [
    (
        "apptegy-nuxt2-state",
        "MARTIN COUNTY SCHOOL DISTRICT",
        "🌀HURRICANE MILTON UPDATE: All MCSD-operated schools and offices will be closed "
        "Wednesday, October 9 - Friday, October 11.",
    ),
    (
        "schoolwires-important-announcements",
        "School District of Manatee County",
        "All SDMC schools are closed to students through Friday 10/9/24. All school "
        "activities, including athletics, are canceled.",
    ),
    (
        "apptegy-nuxt2-state",
        "Brevard Public Schools",
        "BPS will be observing an early release schedule tomorrow, Tuesday, 10/8.",
    ),
    (
        "apptegy-nuxt2-state",
        "Brevard Public Schools",
        "Schools/offices will remain closed on today, Friday, 10/11. For more information "
        "click HERE .",
    ),
    (
        "schoolwires-important-announcements",
        "Monroe County School District",
        "Monroe County School District staff is monitoring the progress of Hurricane Milton "
        "in the Gulf of Mexico. All schools and offices will be open for normal operations on "
        "Tuesday, October 8th.",
    ),
    (
        "apptegy-nuxt-state",
        "Lake County Schools",
        "The State Emergency Operations Center notified Lake County Schools late Monday "
        "afternoon that the district is one of several that have been designated to host "
        "evacuees from Hurricane Milton.",
    ),
    (
        "apptegy-nuxt2-state",
        "Sarasota County Schools",
        "All traditional public schools will be closed for normal school operations from "
        "Wednesday, September 25 through Friday, September 27 due to the storm.",
    ),
    (
        "dadeschools-alerts",
        "Hurricane Milton",
        "All M-DCPS schools, as well as Region and District offices will be CLOSED on "
        "Wednesday, October 9 and Thursday, October 10.",
    ),
    (
        "pasco-red-rectangle",
        "Pasco County Schools",
        "All Pasco County schools and offices will reopen on Monday, October 3rd. Power has "
        "been fully restored to the schools that lost power during the storm.",
    ),
    (
        "pasco-emergency-banner",
        "Pasco County Schools",
        "Schools will be open on Wednesday, September 25, but all activities and events are "
        "canceled, except for before-and-after-school PLACE/ASEP programs. District Offices "
        "and Schools will be CLOSED on Thursday, September 26,",
    ),
    (
        "schoolwires-important-announcements",
        "The School District of Osceola County, Florida",
        "Schools To Be Closed September 27, September 28, September 29, 2022, and "
        "September 30, 2022 ... Click to Read More!",
    ),
    (
        "smartsites-popup-alerts",
        "School Closure",
        "Due to current weather conditions, all North Gem schools are closed today. We will "
        "shift to an online learning day.",
    ),
    # Hardin's (MT) Campus Suite alert banner before its Apptegy site (run 36409494144).
    (
        "campussuite-alert-banner",
        "Hardin School District 17H&1",
        "School Closure Wednesday, Dec. 21st 2022: Good Afternoon, Due to the potential of "
        "extreme cold temperatures, snowfall and frigid wind chills that could easily exceed "
        "-30 degrees below zero, Hardin School Districts 17H & 1 will not be able to run any "
        "route or activity buses this coming Wednesday",
    ),
    # Edlio homepage alerts archived on the January 2025 South Texas snow (runs 36383349206
    # and 36409494144): Mission CISD's and Hidalgo ISD's.
    (
        "edlio-homepage-alert",
        "Weather Advisory",
        "No School - Jan 21, 2025 Delayed Start - Jan 22, 2025",
    ),
    (
        "edlio-homepage-alert",
        "Delayed Start at Hidalgo ISD",
        "Click on the link for more information regarding the delayed start coming up this "
        "week; January 21-23, 2025.",
    ),
]

NOT_CLOSINGS = [
    (
        "apptegy-nuxt-state",
        "Lake County Schools",
        "School Board names Chad Farnsworth next Superintendent",
    ),
    (
        "schoolwires-important-announcements",
        "Alachua County Public Schools",
        "NOW HIRING SUBSTITUTE TEACHERS!",
    ),
    (
        "apptegy-nuxt-state",
        "Fremont County School District 6",
        "We are hiring! See Job Openings HERE!",
    ),
    (
        "finalsite-page-pops",
        "Notice",
        "Learn more about the Secure the Next Generation Referendum at "
        "browardschools.com/referendum2026 .",
    ),
    ("finalsite-page-pops", "FHS Bond Information - Election Day, September 29, 2026", ""),
    (
        "finalsite-page-pops",
        "September 28, 2026- Staff Development- NO SCHOOL FOR STUDENTS",
        "Hellgate Elementary School District has a Staff Development Day on September 28, "
        "2026. There is NO school for students on this day.",
    ),
    (
        "apptegy-nuxt2-state",
        "Brevard Public Schools",
        "BPS schools and offices will be OPEN tomorrow, Friday 9/27.",
    ),
    (
        "schoolwires-important-announcements",
        "Monroe County School District",
        "All Monroe County School District schools and offices will be OPEN Friday, "
        "September 27th.",
    ),
    (
        "smartsites-popup-alerts",
        "Fingerprinting Appointments",
        "Want to volunteer and need a background check with fingerprinting?",
    ),
    (
        "smartsites-popup-alerts",
        "Attention: Parents/Guardians of Special Education Students Born in 1999 or 2000",
        "Were you (or your student) born in 1999 or 2000 and received special education "
        "services through Belgrade School District?",
    ),
    ("finalsite-page-pops", "We\u2019re Counting Down to Better Health!", ""),
    ("finalsite-page-pops", "Hendry County School District Clinic", ""),
    (
        "finalsite-page-pops",
        "Important Notice Regarding Settlement Agreement between MT OPI and ACLU of MT",
        "Please review the attached Class Notice and settlement agreement for important "
        "information about the litigation, settlement, and any rights or options available "
        "to class members.",
    ),
    (
        "finalsite-page-pops",
        "Notice of Trustee Vacancy",
        "NOTICE IS HEREBY GIVEN that a vacancy exists on the Board of Trustees of Havre "
        "Public Schools, Hill County, Montana, following the resignation of Timothy Scheele.",
    ),
    (
        "apptegy-nuxt-state",
        "St. Ignatius Public Schools",
        "Mission Forward Academy is accepting enrollment for any homeschool students "
        "interested in working with our school district.",
    ),
    (
        "apptegy-nuxt-state",
        "Sweetwater County School District #2",
        "If your family is new to the District, email registration@swcsd2.org to receive a "
        "link to our on-line registration system.",
    ),
    # A planned break: Grace School District #148's live SchoolBlocks alert of 2026-09-28.
    (
        "schoolblocks-org-alerts",
        "Grace School District #148",
        "Grace School District will be closed from September 11-October 4 for potato harvest "
        "break. We will return to school on October 5.",
    ),
    (
        "apptegy-nuxt2-state",
        "Frenchtown School District",
        "Winter Break Early out 12/21/2022 thru 1/2/2023",
    ),
    ("edlio-homepage-alert", "School Picture Days", "Information About School Picture Days"),
    # A headline alone that names no closing (Los Fresnos CISD, 2025-01-21): the story
    # behind its link is not read, so it does not prove the channel.
    ("edlio-homepage-alert", "Weather Notice - Monday, January, 20", ""),
]


@pytest.mark.parametrize(("variant", "name", "status"), CLOSINGS)
def test_closing_and_weather_notices_qualify(variant: str, name: str, status: str) -> None:
    assert notices.row_qualifies(name, status, variant)


@pytest.mark.parametrize(("variant", "name", "status"), NOT_CLOSINGS)
def test_hiring_board_and_calendar_notices_do_not(variant: str, name: str, status: str) -> None:
    assert not notices.row_qualifies(name, status, variant)


def test_a_districts_own_name_never_proves_it() -> None:
    # SYNTHETIC: a district named for the weather posting a hiring banner.
    assert not notices.row_qualifies(
        "Storm Lake Community School District", "We are hiring!", "apptegy-nuxt-state"
    )
    # SYNTHETIC: a notice's own title does count.
    assert notices.row_qualifies("Snow Day", "", "finalsite-page-pops")


@pytest.mark.parametrize(
    "text",
    [
        # SYNTHETIC near misses: closings that are not a school's, and weather words
        # that are not weather.
        "School Board workshop (Closed Session) at 9:00 AM",
        "Indian River Virtual School enrollment closes October 1",
        "Registration for the fall session closes Friday",
        "Our high school is a closed campus during lunch",
        "The district is committed to closing the achievement gap",
        "District offices will be closed Monday for Labor Day",
        "Schools closed November 24-28 for Thanksgiving Break",
        "Early release every Wednesday for PLC collaboration",
        "Early Release Day on Wednesday, November 25",
        "Minimum day schedule on Friday: students are dismissed at 12:30",
        "Ice cream social on Friday!",
        "Snow White Jr. auditions are open to all students",
        "Go Hurricanes! Homecoming is Friday night",
        "Weather permitting, the parade starts at 5 PM",
        "Tornado drill on Tuesday at 10 AM",
        "Indian River Virtual School enrollment is open",
        "The district is under a hiring freeze",
    ],
)
def test_near_misses_do_not_qualify(text: str) -> None:
    assert not notices.announces_closing(text)


@pytest.mark.parametrize(
    "text",
    [
        # SYNTHETIC: weather or an emergency qualifies even on a planned day.
        "Due to inclement weather, all schools will operate on a 2-hour delay",
        "Winter storm warning: classes are cancelled tomorrow",
        "Schools are closed today because of a water main break",
        "Extreme cold: all buses will run two hours late",
    ],
)
def test_weather_and_emergency_notices_qualify(text: str) -> None:
    assert notices.announces_closing(text)


@pytest.mark.parametrize(
    ("text", "announces"),
    [
        # SYNTHETIC: Spanish, as South Texas' districts post it (often beside the English).
        ("Debido al mal tiempo, todas las escuelas estarán cerradas el martes", True),
        ("Las clases están canceladas mañana por la tormenta invernal", True),
        ("Huracán Hanna: se suspenden las clases", True),
        ("Salida temprana hoy a las 12:30 por condiciones del clima", True),
        ("Horario retrasado: inicio tardío de dos horas", True),
        ("Las oficinas del distrito permanecerán cerradas por el apagón", True),
        # Real: the Spanish half of Rio Grande City Grulla ISD's live enrollment banner
        # (www.myrgcgisd.org, read 2026-09-28T01:45Z).
        ("RGCGISD Ahora esta inscribiendo nuevos estudiantes para el proximo ano escolar", False),
        # SYNTHETIC near misses in Spanish: hiring, a planned holiday, staff development.
        ("¡Estamos contratando maestros!", False),
        ("Escuelas cerradas por el Día de Acción de Gracias", False),
        ("No hay clases: día de desarrollo profesional", False),
    ],
)
def test_spanish_notices(text: str, announces: bool) -> None:
    assert notices.announces_closing(text) is announces


@pytest.mark.parametrize(
    ("status", "announces"),
    [
        # Real statuses: Flathead County's, GOHSEP's and the Shasta office's boards.
        ("Closed", True),
        ("CLOSED", True),
        ("Remote", True),
        ("Early Dismissal", True),
        ("Planned Closure", True),
        ("Closing at 12:45", True),
        ("Open", False),
        ("OPEN", False),
        ("0PEN", False),
        ("", False),
        # SYNTHETIC: a delay on a board.
        ("2 Hour Delay", True),
    ],
)
def test_a_status_board_row_counts_only_when_not_open(status: str, announces: bool) -> None:
    assert notices.board_status_announces(status) is announces
    assert notices.row_qualifies("KILA", status, "any", board=True) is announces


def test_the_gated_stations_are_the_district_channels_and_the_status_boards() -> None:
    gated = notices.gated_adapters(REGISTRY)
    assert gated["apptegy-lake-fl"] is False
    assert gated["finalsite-hendry-fl"] is False
    assert gated["dadeschools-miami-dade-fl"] is False
    assert gated["pasco-county-fl"] is False
    assert gated["smartsites-belgrade-mt"] is False
    assert gated["edlio-mission-tx"] is False
    assert gated["schoolblocks-grace-id"] is False
    assert gated["flathead-county"] is True
    assert gated["gohsep-parish-schools"] is True
    assert gated["coesheet-trinity"] is True
    assert "cowles-kulr" not in gated  # a closings list: any row proves it


FIXTURE_VERDICTS = {
    # (file under fixtures/gaps/): whether a row of it proves its source.
    "apptegy/alachua-20241009.html": False,  # "NOW HIRING SUBSTITUTE TEACHERS!"
    "apptegy/alpena-live-20260928.html": False,  # a meal-benefits form
    "apptegy/brevard-20241011.html": True,  # "Schools/offices will remain closed"
    "apptegy/brownsville-live-20260928.html": False,  # three hiring calls
    "apptegy/corpus-christi-live-20260928.html": False,  # the district's mobile app
    "apptegy/fremont-6-live-20260927.html": False,  # "We are hiring!"
    "apptegy/hamilton-20250216.html": False,  # a phone carrier's trouble
    "apptegy/hardin-20221221.html": True,  # Campus Suite: "School Closure ... extreme cold"
    "apptegy/lake-live-20260927.html": False,  # the superintendent's appointment
    "apptegy/manatee-20241009.html": True,  # "All SDMC schools are closed"
    "apptegy/martin-20220928.html": True,  # Hurricane Ian
    "apptegy/martin-20241009.html": True,  # Hurricane Milton
    "apptegy/monroe-20241007.html": True,  # Hurricane Milton
    "apptegy/santa-rosa-live-20260928.html": False,  # a Title I parent survey
    "apptegy/sarasota-20240924.html": True,  # "closed ... due to the storm"
    "apptegy/st-ignatius-live-20260927.html": False,  # enrollment
    "apptegy/sweetwater-2-live-20260927.html": False,  # registration
    "dadeschools/alerts-20241009.json": True,  # Hurricane Milton
    "edlio/hidalgo-20250120.html": True,  # "Delayed Start at Hidalgo ISD"
    "edlio/lake-elsinore-live-20260928.html": False,  # a new website is coming
    "edlio/los-fresnos-20250121.html": False,  # a headline alone, "Weather Notice - Monday"
    "edlio/mission-20250121.html": True,  # "Weather Advisory": "No School - Jan 21"
    "edlio/sublette-9-live-20260928.html": False,  # school picture days
    "finalsite/broward-page-pops-live-20260927.html": False,  # a referendum
    "finalsite/chickasaw-page-pops-live-20260928.html": False,  # Parent University, an event
    "finalsite/great-falls-page-pops-live-20260927.html": False,  # a settlement notice
    "finalsite/havre-page-pops-live-20260927.html": False,  # a trustee vacancy
    "finalsite/hellgate-page-pops-live-20260927.html": False,  # staff development
    "finalsite/hendry-page-pops-live-20260927.html": False,  # a clinic, a health event
    "finalsite/lewistown-page-pops-live-20260927.html": False,  # a bond election
    "finalsite/palm-beach-home-20241010.html": True,  # Milton: the storm, shelters, the EOC
    "finalsite/south-texas-page-pops-live-20260928.html": False,  # enrollment, a CTE guide
    "finalsite/volusia-home-20241014.html": True,  # "Hurricane Milton Update"
    "pasco/home-20221003.html": True,  # reopening after the storm's power losses
    "pasco/home-20241009.html": True,  # Milton closure
    "schoolblocks/grace-live-20260928.html": False,  # closed for the potato harvest break: planned
    "smartsites/belgrade-popup-alerts-20260814.json": False,  # records, fingerprinting
    "smartsites/belgrade-popup-alerts-live-20260927.json": False,
    "smartsites/coachella-valley-popup-alerts-live-20260928.json": False,  # a menu app
    "smartsites/leon-home-20240805.html": True,  # "closed ... Due to TS Debby"
    "smartsites/osceola-home-20220928.html": True,  # "Schools To Be Closed"
    "smartsites/tuloso-midway-popup-alerts-live-20260928.json": False,  # a public meeting
    "coesheet/shasta-sheet-live-20260927.csv": True,  # "Closing at 12:45"
    "coesheet/shasta-tab-live-20260927.html": True,
    "coesheet/trinity-sheet-live-20260927.html": False,  # every school "Open"
    "flathead/closures-20250427.html": False,  # every school "Open"
    "flathead/closures-20260119.html": True,
    "flathead/closures-20260412.html": True,  # five schools "Closed"
    "flathead/closures-20260815.html": False,
    "flathead/closures-live-20260927.html": True,  # one school "Closed"
    "flathead/closures-oldsite-20230103.html": True,
    "flathead/closures-oldsite-20240209.html": True,
    "flathead/closures-oldsite-20250227.html": True,
    "gohsep/query-live-20260927.json": True,  # 11 parishes "Closed"
}


def _gated_fixtures() -> list[dict[str, JSONValue]]:
    entries = json.loads((GAPS / "PROVENANCE.json").read_text(encoding="utf-8"))
    gated = notices.GENERAL_CHANNEL_ADAPTERS | notices.STATUS_BOARD_ADAPTERS
    return [
        entry
        for entry in entries
        if entry["adapter"] in gated
        and entry["expected"]["state"] == "populated"
        and entry["expected"]["rows"] > 0
    ]


def test_every_populated_fixture_of_a_gated_source_has_its_verdict_pinned() -> None:
    assert sorted(str(entry["file"]) for entry in _gated_fixtures()) == sorted(FIXTURE_VERDICTS)


@pytest.mark.parametrize("entry", _gated_fixtures(), ids=lambda entry: str(entry["file"]))
def test_the_rule_on_every_real_populated_fixture(entry: dict[str, JSONValue]) -> None:
    adapter = str(entry["adapter"])
    listing = adapter_for(adapter)((GAPS / str(entry["file"])).read_bytes())
    board = adapter in notices.STATUS_BOARD_ADAPTERS
    proves = any(
        notices.row_qualifies(row.name, row.status, listing.variant, board=board)
        for row in listing.rows
    )
    assert proves is FIXTURE_VERDICTS[str(entry["file"])]


@dataclass(frozen=True)
class _Proof:
    """SYNTHETIC: the fields of a proof the gate reads."""

    source_id: str
    mode: str
    url: str
    captured_at: datetime
    variant: str
    basis: str


def _rows_file(path: Path, rows: list[tuple[str, datetime, str, str]]) -> Path:
    lines = [
        json.dumps(
            {
                "source_id": source,
                "fetched_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "raw_name": name,
                "raw_status": status,
                "raw_updated_text": None,
                "raw_extra": {},
            }
        )
        for source, at, name, status in rows
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


LIVE = datetime(2026, 9, 27, 15, 26, 47, tzinfo=UTC)
STORM = datetime(2024, 10, 9, 18, 38, 31, tzinfo=UTC)
FLATHEAD_STORM = datetime(2024, 2, 9, 10, 42, 52, tzinfo=UTC)


def test_the_gate_drops_a_superintendent_banner_and_keeps_a_storm_banner(tmp_path: Path) -> None:
    live = _rows_file(
        tmp_path / "live.jsonl",
        [
            ("apptegy-lake-fl", LIVE, "Lake County Schools", NOT_CLOSINGS[0][2]),
            ("flathead-county", LIVE, "KILA", "Open"),
            ("flathead-county", LIVE, "SWAN RIVER", "Open"),
        ],
    )
    archive = _rows_file(
        tmp_path / "archive.jsonl",
        [
            ("apptegy-martin-fl", STORM, "MARTIN COUNTY SCHOOL DISTRICT", CLOSINGS[0][2]),
            ("flathead-county", FLATHEAD_STORM, "KILA", "Open"),
            ("flathead-county", FLATHEAD_STORM, "SWAN RIVER", "Closed"),
        ],
    )
    lake = _Proof(
        "apptegy-lake-fl",
        "live",
        "https://www.lake.k12.fl.us/",
        LIVE,
        "apptegy-nuxt-state",
        "live reads",
    )
    martin = _Proof(
        "apptegy-martin-fl",
        "archive",
        "https://www.martinschools.org/",
        STORM,
        "apptegy-nuxt2-state",
        "archive reads",
    )
    flathead_open = _Proof(
        "flathead-county",
        "live",
        "https://flatheadcounty.gov/x",
        LIVE,
        "flathead-closure-tables",
        "live reads",
    )
    flathead_storm = _Proof(
        "flathead-county",
        "archive",
        "https://flatheadcounty.gov/x",
        FLATHEAD_STORM,
        "flathead-closure-tables",
        "archive reads",
    )
    cowles = _Proof(
        "cowles-kulr",
        "live",
        "https://company-wide-tickers.s3.us-west-2.amazonaws.com/x",
        LIVE,
        "cowles-ticker",
        "live reads",
    )
    proofs = {
        "apptegy-lake-fl": [lake],
        "apptegy-martin-fl": [martin],
        "flathead-county": [flathead_open, flathead_storm],
        "cowles-kulr": [cowles],
    }
    report = notices.gate_proofs(
        proofs, REGISTRY, live_rows=[live], archive_rows=[archive], fixtures=None
    )
    assert proofs["apptegy-lake-fl"] == []
    assert proofs["apptegy-martin-fl"] == [martin]
    assert proofs["flathead-county"] == [flathead_storm]  # a board: only the non-open read
    assert proofs["cowles-kulr"] == [cowles]  # a closings list: not gated
    assert "cowles-kulr" not in report
    lake_report = report["apptegy-lake-fl"]
    assert isinstance(lake_report, dict)
    assert lake_report["kind"] == "channel"
    assert lake_report["kept"] == 0
    assert lake_report["dropped_count"] == 1
    martin_report = report["apptegy-martin-fl"]
    assert isinstance(martin_report, dict)
    kept = martin_report["kept_proofs"]
    assert isinstance(kept, list)
    assert isinstance(kept[0], dict)
    assert str(kept[0]["row"]).startswith("MARTIN COUNTY SCHOOL DISTRICT | 🌀HURRICANE MILTON")
    board_report = report["flathead-county"]
    assert isinstance(board_report, dict)
    assert board_report["kind"] == "board"
    dropped = board_report["dropped"]
    assert isinstance(dropped, list)
    assert isinstance(dropped[0], dict)
    assert dropped[0]["reason"] == "every row's status is open"


def test_the_gate_reads_a_fixtures_rows_and_drops_a_read_without_rows(tmp_path: Path) -> None:
    hiring = _Proof(
        "apptegy-lake-fl",
        "live",
        "https://www.lake.k12.fl.us/",
        LIVE,
        "apptegy-nuxt-state",
        "fixture gaps/apptegy/lake-live-20260927.html",
    )
    storm = _Proof(
        "apptegy-martin-fl",
        "archive",
        "https://www.martinschools.org/",
        STORM,
        "apptegy-nuxt2-state",
        "fixture gaps/apptegy/martin-20241009.html",
    )
    trinity = _Proof(
        "coesheet-trinity",
        "live",
        "https://docs.google.com/x",
        LIVE,
        "coesheet-html",
        "fixture gaps/coesheet/trinity-sheet-live-20260927.html",
    )
    missing = _Proof(
        "finalsite-hendry-fl",
        "live",
        "https://www.hendry-schools.org/fs/pages/2/page-pops",
        LIVE,
        "finalsite-page-pops",
        "live reads",
    )
    proofs = {
        "apptegy-lake-fl": [hiring],
        "apptegy-martin-fl": [storm],
        "coesheet-trinity": [trinity],
        "finalsite-hendry-fl": [missing],
    }
    report = notices.gate_proofs(
        proofs, REGISTRY, live_rows=[tmp_path / "none.jsonl"], archive_rows=[], fixtures=FIXTURES
    )
    assert proofs == {
        "apptegy-lake-fl": [],
        "apptegy-martin-fl": [storm],
        "coesheet-trinity": [],
        "finalsite-hendry-fl": [],
    }
    hendry = report["finalsite-hendry-fl"]
    assert isinstance(hendry, dict)
    dropped = hendry["dropped"]
    assert isinstance(dropped, list)
    assert isinstance(dropped[0], dict)
    assert dropped[0]["reason"] == "rows not found"


def test_unproven_entries_say_what_the_gate_dropped() -> None:
    # SYNTHETIC: a coverage result's unproven list and a gate report.
    result: dict[str, JSONValue] = {
        "unproven": [
            {"id": "apptegy-lake-fl", "checked": {"live": {"count": 1, "items": []}}},
            {"id": "cowles-kulr", "checked": {"live": {"count": 1, "items": []}}},
        ]
    }
    report: dict[str, JSONValue] = {
        "apptegy-lake-fl": {"kind": "channel", "kept": 0, "dropped_count": 2, "dropped": []}
    }
    notices.annotate_unproven(result, report)
    unproven = result["unproven"]
    assert isinstance(unproven, list)
    lake, cowles = unproven
    assert isinstance(lake, dict)
    assert isinstance(cowles, dict)
    lake_checked = lake["checked"]
    assert isinstance(lake_checked, dict)
    gate = lake_checked["notice_gate"]
    assert isinstance(gate, dict)
    assert gate["populated_reads_dropped"] == 2
    cowles_checked = cowles["checked"]
    assert isinstance(cowles_checked, dict)
    assert "notice_gate" not in cowles_checked


def test_hiring_and_superintendent_banners_leave_a_source_unproven(tmp_path: Path) -> None:
    """End to end through the proof evidence (skipped where that module is not present)."""
    proof = pytest.importorskip("snowlight.sources.stations.proof")
    reads = tmp_path / "reads.jsonl"
    lines = []
    for source, url, at in [
        ("apptegy-lake-fl", "https://www.lake.k12.fl.us/", LIVE),
        ("apptegy-fremont-6-wy", "https://www.fremont6.org/", LIVE),
        ("apptegy-martin-fl", "https://www.martinschools.org/", STORM),
    ]:
        lines.append(
            json.dumps(
                {
                    "source_id": source,
                    "mode": "live",
                    "url": url,
                    "fetched_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "retrieved_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sha256": "0" * 64,
                    "bytes": 10,
                    "variant": "apptegy-nuxt-state",
                    "state": "populated",
                    "rows": 1,
                    "declared_count": None,
                    "skipped_rows": 0,
                }
            )
        )
    reads.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = [
        ("apptegy-lake-fl", LIVE, "Lake County Schools", NOT_CLOSINGS[0][2]),
        ("apptegy-fremont-6-wy", LIVE, "FCSD6", NOT_CLOSINGS[2][2]),
        ("apptegy-martin-fl", STORM, "MARTIN", CLOSINGS[0][2]),
    ]
    _rows_file(tmp_path / "rows.jsonl", rows)
    evidence = proof.gather(
        live_reads=reads, archive_reads=None, archive_health=None, fixtures=None
    )
    notices.gate_proofs(
        evidence.proofs,
        REGISTRY,
        live_rows=[reads.with_name("rows.jsonl")],
        archive_rows=[],
        fixtures=None,
    )
    assert evidence.best(REGISTRY.stations["apptegy-lake-fl"]) is None
    assert evidence.best(REGISTRY.stations["apptegy-fremont-6-wy"]) is None
    assert evidence.best(REGISTRY.stations["apptegy-martin-fl"]) is not None


def test_the_rule_agrees_with_the_status_reader() -> None:
    """Every notice the gate accepts, the status reader (f5) reads as a status or a weather notice.

    Skipped where the status reader is not in the checkout.
    """
    classify = pytest.importorskip("snowlight.classify")
    posted = datetime(2024, 10, 9, 12, tzinfo=UTC)
    for variant, name, status in CLOSINGS:
        text = status if variant in notices.ORG_NAMED_VARIANTS else f"{name}: {status}"
        # Read each notice as of its own season (Osceola's names the days of 2022).
        when = datetime(2022, 9, 26, 12, tzinfo=UTC) if "2022" in status else posted
        parsed = classify.parse_status(text, posted_at=when, tz="America/New_York")
        assert parsed.kind != "other" or parsed.reason is not None, status
    for _, _, status in NOT_CLOSINGS[:4]:
        parsed = classify.parse_status(status, posted_at=posted, tz="America/New_York")
        assert parsed.kind == "other", status
        assert parsed.reason is None, status
