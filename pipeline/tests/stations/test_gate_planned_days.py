"""A district channel is proven only by a closing for weather or an emergency.

Rows quoted here are REAL: each is the row a station's proof rested on before the
critics' round of 2026-10-13, read from the live read or the archived capture named
beside it (rows.jsonl of ``stations fetch`` or ``stations archive parse``). The
scheduled days off, stale board statuses and pandemic notices among them prove nothing.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from snowlight.sources.stations import notices
from snowlight.sources.stations.registry import load_registry
from snowlight.sources.stations.storms import WarningDay

FINALSITE_PAGE_POPS = "finalsite-page-pops"
WCM = "wcm-announcements"
APPTEGY_NUXT2 = "apptegy-nuxt2-state"

# finalsite-idaho-falls-id, capture 20240226134125 of www.ifschools.org (a testing day)
IDAHO_FALLS_SAT = (
    "SAT Day is March 13 March 13 is SAT in D91. Juniors at Compass Academy, and Skyline and "
    "Idaho Falls high schools will take the SAT that day, and there will be NO school for "
    "freshmen, sophomores and seniors. The SAT gauges college and career readiness and many "
    "colleges and universities use it as an entrance requirement."
)
# the same channel, capture 20230131000230 (a weather closing)
IDAHO_FALLS_COLD = (
    "D91 Schools Closed Jan. 30 D91 is cancelling school on Monday, Jan. 30, because of "
    "extreme weather and cold."
)
# finalsite-sharyland-tx, live read 2026-09-29T10:37:42Z (a staff planning day)
SHARYLAND = (
    "No classes - Friday, October 2",
    "Sharyland ISD Family, There will be no classes on Friday, October 2, as this day is "
    "dedicated to planning and preparation for our teachers and staff. Classes will resume at "
    "their normal time on Monday, October 5.",
)
# finalsite-volusia-fl, capture 20241014005904 of www.vcsedu.org (after Milton)
VOLUSIA = (
    "Hurricane Milton Update",
    "Dear Volusia County Schools Family, It is our sincere hope that you and your loved ones "
    "stayed safe during Hurricane Milton and that our community will begin to recover as soon "
    "as possible. Our dedicated crews are visiting all school and district sites, as well as "
    "bus stops and routes, to assess each situation and ensure a safe return to school next "
    "week. Monday, Oct. 14, will still be a Student Holiday/Teacher Duty Day. There is no "
    "school for students on this day. Classes for students will resume on Tuesday, Oct. 15.",
)
# finalsite-hellgate-mt, capture 20231118173949 (Thanksgiving break)
HELLGATE = "No School Wednesday, November 22 - Friday, November 24th"
# apptegy-florence-carlton-mt, capture 20230202181601 (no reason, six days old)
FLORENCE_CARLTON = "No School on January 27th."
# smartsites-alvord-ca, capture 20200318132148 of www.alvordschools.org (the 2020 shutdown)
ALVORD_REMOTE = (
    "On-Line Learning Enrichment Resources Find Learning Enrichment resources here. This page "
    "will be updated daily. Spectrum Broadband is partnering with school districts to help "
    "students learn remotely by opening WiFi hotspots across their footprint for public use. "
    "They are also offering Spectrum Internet Assist , a high-speed broadband program to "
    "eligible low-income households during school closure."
)
ALVORD_ORDER = (
    "Alvord School District Takes Action on School Closures View Video Here... ORDER OF THE "
    "HEALTH OFFICER OF THE COUNTY OF RIVERSIDE Order of the Health Officer RIVERSIDE "
    "UNIVERSITY HEALTH SYSTEM PUBLIC HEALTH Riverside County NEWS RELEASE"
)
ALVORD_READ = datetime(2020, 3, 18, 13, 21, 48, tzinfo=UTC)
# apptegy-duval-fl, capture 20240926131427 of dcps.duvalschools.org (a headline, no closing)
DUVAL = "Potential Hurricane Helene: Closure Information and Updates"


def test_a_testing_day_never_proves_and_the_weather_closing_does() -> None:
    assert not notices.row_qualifies("Idaho Falls School District 91", IDAHO_FALLS_SAT, WCM)
    assert notices.row_qualifies("Idaho Falls School District 91", IDAHO_FALLS_COLD, WCM)


def test_a_staff_planning_day_never_proves() -> None:
    name, status = SHARYLAND
    assert not notices.row_qualifies(name, status, FINALSITE_PAGE_POPS)
    assert not notices.announces_closing(status, name)


def test_a_storm_letter_whose_only_no_school_is_a_student_holiday_does_not_prove() -> None:
    name, status = VOLUSIA
    assert not notices.announces_closing(status, name)
    # what is left once the planned day and the sentence about it are struck
    left = notices.strike_planned(status)
    assert "Student Holiday" not in left
    assert "no school" not in left.lower()
    # a storm letter that closes the schools still proves, a student holiday beside it or not
    assert notices.announces_closing(
        "All schools will be closed Thursday and Friday due to Hurricane Milton. Monday, Oct. "
        "14, will still be a Student Holiday.",
        "Hurricane Milton Update",
    )


@pytest.mark.parametrize("status", [HELLGATE, FLORENCE_CARLTON])
def test_a_bare_no_school_names_no_reason_and_does_not_prove(status: str) -> None:
    assert not notices.row_qualifies("A district", status, WCM)
    assert not notices.row_qualifies("A district", status, APPTEGY_NUXT2)
    # with a reason it does
    assert notices.announces_closing("No School Monday due to the snow storm")


def test_a_bare_no_school_is_left_to_the_weather_service() -> None:
    # Hellgate's names a run of days (Thanksgiving week), which no warning corroborates
    hellgate = datetime(2023, 11, 18, 17, 39, 49, tzinfo=UTC)
    november = {
        day: WarningDay(day, 1.0, "30063")
        for day in (datetime(2023, 11, 22).date(), datetime(2023, 11, 24).date())
    }
    assert notices.dated_closing(HELLGATE, None, hellgate, november) is None
    # Florence-Carlton's day lay six days before the capture, outside the dated window
    florence = datetime(2023, 2, 2, 18, 16, 1, tzinfo=UTC)
    january = {datetime(2023, 1, 27).date(): WarningDay(datetime(2023, 1, 27).date(), 1.0, "30081")}
    assert notices.dated_closing(FLORENCE_CARLTON, None, florence, january) is None


def test_the_2020_shutdown_never_proves_though_it_names_no_virus() -> None:
    name = "Alvord Unified School District"
    for status in (ALVORD_REMOTE, ALVORD_ORDER):
        assert not notices.row_qualifies(name, status, WCM, when=ALVORD_READ)
    # the health officer's order is a pandemic's whenever it was read, naming no weather
    assert notices.pandemic(ALVORD_ORDER)
    # a health officer's order for wildfire smoke is that emergency's
    assert not notices.pandemic(
        "Schools closed today by order of the health officer due to wildfire smoke"
    )
    # learning remotely outside the shutdown is a remote day like any other
    assert not notices.pandemic(ALVORD_REMOTE, datetime(2024, 1, 16, tzinfo=UTC))


def test_a_closure_information_headline_is_not_a_closing() -> None:
    assert not notices.row_qualifies("Duval County Public Schools", DUVAL, APPTEGY_NUXT2)
    assert notices.announces_closing("Hurricane Debby Closure")


@pytest.mark.parametrize(
    "status",
    [
        "No school closures or delays today, January 12, due to weather.",
        "There will be no school delay or closure today due to weather.",
        "We are not cancelling school today despite the icy roads.",
    ],
)
def test_a_notice_that_the_schools_keep_their_day_is_no_closing(status: str) -> None:
    # SYNTHETIC rows, in the forms a district writes them
    assert not notices.announces_closing(status)
    assert not notices.weather_closing(status)
    assert not notices.page_text_closing(status)


# A status board's row and a channel's alert carry their own stamp ---------------------


def _row(status: str, stamp: str | None) -> notices.GateRow:
    return notices.GateRow("Black Butte Elementary", status, None, stamp)


def test_a_board_status_long_after_its_own_stamp_is_a_leftover() -> None:
    # coesheet-shasta: "Closing at 12:45", stamped "9/10 9:45", read 2026-09-29 to 10-13
    row = _row("Closing at 12:45", "9/10 9:45")
    assert notices.board_status_announces(row.status)
    for read in (
        datetime(2026, 9, 29, 10, 21, 30, tzinfo=UTC),
        datetime(2026, 10, 13, 13, 58, 44, tzinfo=UTC),
    ):
        assert not notices.stamp_current(row, read)
    assert notices.stamp_current(row, datetime(2026, 9, 10, 18, 0, tzinfo=UTC))


def test_a_board_closure_dated_months_before_the_read_is_a_leftover() -> None:
    # gohsep-parish-schools: "Ascension | Closed", closure_date 2026-06-18, read 2026-10-05
    row = notices.GateRow("Ascension", "Closed", None, "2026-06-18")
    assert not notices.stamp_current(row, datetime(2026, 10, 5, 1, 21, 54, tzinfo=UTC))
    assert notices.stamp_current(row, datetime(2026, 6, 18, 12, 0, tzinfo=UTC))
    # and its "Planned Closure" rows never announce a closing
    assert not notices.board_status_announces("Planned Closure")


@pytest.mark.parametrize(
    ("stamp", "read", "day"),
    [
        ("September 25, 26 8:11 AM", datetime(2026, 9, 29, 10, 41, tzinfo=UTC), (2026, 9, 25)),
        ("Monday, June 23rd, 2025", datetime(2025, 8, 10, 0, 59, tzinfo=UTC), (2025, 6, 23)),
        ("01/05/2026 8:47 AM", datetime(2026, 1, 5, 16, 0, tzinfo=UTC), (2026, 1, 5)),
        ("2024-01-15T21:20:00Z", datetime(2024, 1, 16, 12, 0, tzinfo=UTC), (2024, 1, 15)),
        ("2026-10-12T17:00:02.270-06:00", datetime(2026, 10, 13, tzinfo=UTC), (2026, 10, 12)),
        ("59 days ago", datetime(2026, 9, 27, 12, 0, tzinfo=UTC), (2026, 7, 30)),
    ],
)
def test_a_stamp_is_read_as_its_page_writes_it(
    stamp: str, read: datetime, day: tuple[int, int, int]
) -> None:
    assert notices.stamp_day(stamp, read) == datetime(*day).date()


def test_an_unstamped_row_passes_the_stamp_rule() -> None:
    assert notices.stamp_current(_row("Closed", None), datetime(2026, 10, 13, tzinfo=UTC))


# The proof a gated station records ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Proof:
    source_id: str
    mode: str
    url: str
    captured_at: datetime
    variant: str
    basis: str


def test_a_station_records_its_earliest_weather_proof(tmp_path: Path) -> None:
    registry = load_registry(Path(__file__).resolve().parents[2] / "config" / "sources")
    sat = datetime(2024, 2, 26, 13, 41, 25, tzinfo=UTC)
    cold = datetime(2023, 1, 31, 0, 2, 30, tzinfo=UTC)
    repeat = datetime(2023, 2, 1, 0, 0, tzinfo=UTC)  # SYNTHETIC: a later read of the same row
    reads = ((sat, IDAHO_FALLS_SAT), (cold, IDAHO_FALLS_COLD), (repeat, IDAHO_FALLS_COLD))
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        "".join(
            json.dumps(
                {
                    "source_id": "finalsite-idaho-falls-id",
                    "fetched_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "raw_name": "Idaho Falls School District 91",
                    "raw_status": status,
                    "raw_updated_text": None,
                    "raw_extra": {},
                }
            )
            + "\n"
            for at, status in reads
        ),
        encoding="utf-8",
    )
    url = "https://www.ifschools.org/"
    proofs = {
        "finalsite-idaho-falls-id": [
            _Proof("finalsite-idaho-falls-id", "archive", url, at, WCM, "archive reads")
            for at in (sat, repeat, cold)
        ]
    }
    chosen: dict[str, _Proof] = {}
    report = notices.gate_proofs(
        proofs,
        registry,
        live_rows=[],
        archive_rows=[rows],
        fixtures=None,
        warnings={},
        chosen=chosen,
    )
    entry = report["finalsite-idaho-falls-id"]
    assert isinstance(entry, dict)
    assert entry["kept"] == 2  # the SAT day's read is dropped
    assert chosen["finalsite-idaho-falls-id"].captured_at == cold


def test_a_storm_notice_stays_current_through_its_closing() -> None:
    # finalsite-gulf-shores-al: a hurricane closing and fall break through 12 October, posted
    # 2026-10-07T13:20:05-05:00 and read the morning of the 13th (six days on)
    row = notices.GateRow("School Closure - Fall Break - eLearning Day Reminder", "x", None)
    stamped = row._replace(stamp="2026-10-07T13:20:05-05:00")
    assert notices.stamp_current(stamped, datetime(2026, 10, 13, 8, 54, 46, tzinfo=UTC))
    assert not notices.stamp_current(stamped, datetime(2026, 10, 16, 12, 0, tzinfo=UTC))
