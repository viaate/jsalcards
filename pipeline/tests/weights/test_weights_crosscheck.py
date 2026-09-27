"""The cross-checks: school-year files against the day-file client, and zone names.

Day files, school-year rows, correlation lines and UGC names are real slices
(``fixtures/provenance.json``). The day-file slices hold the Rhode Island rows of
2025-01-30 to 2025-02-08, the school-year slice the Rhode Island rows of 2024-25.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from snowlight.weights import archive, crosscheck, zones

if TYPE_CHECKING:
    from weights.conftest import Kit

WINDOW = (date(2025, 2, 6), date(2025, 2, 7))


def _mapper(kit: "Kit") -> crosscheck.CountyMapper:
    releases = zones.load_releases(kit.cache(), kit.releases)
    counties = zones.read_counties(kit.path("c_16ap26.zip"))
    return crosscheck.CountyMapper(zones.ZoneCountyCatalog(releases, counties.state_fips), counties)


def _day_rows(kit: "Kit") -> list[archive.EventRow]:
    days = crosscheck.make_day_archive(kit.cache())
    raw = [row for day in kit.days for row in days.day(day).rows]
    rows, missing = crosscheck.event_rows_from_day_files(raw)
    assert missing == 0
    return rows


def test_day_file_rows_become_event_rows(kit: "Kit") -> None:
    rows = _day_rows(kit)
    assert {row.event_key for row in rows} == {"BOX.WW.Y.0004.2025", "BOX.WW.Y.0005.2025"}
    row = next(r for r in rows if r.event_key == "BOX.WW.Y.0005.2025" and r.ugc == "RIZ001")
    assert row.begin == datetime(2025, 2, 6, 12, 0, tzinfo=UTC)
    # The product time comes from the head of the product id, as the CSV's utc_prodissue.
    assert row.product_issued == datetime(2025, 2, 4, 19, 27, tzinfo=UTC)
    csv_rows, _ = archive.read_rows(kit.text("iem-2024-2025.csv"))
    same = next(r for r in csv_rows if r.event_key == row.event_key and r.ugc == "RIZ001")
    assert (same.begin, same.end, same.product_issued) == (row.begin, row.end, row.product_issued)


def test_compare_days_on_real_files(kit: "Kit") -> None:
    files = archive.load_years(kit.cache(), [2024])
    archive_days = crosscheck.make_day_archive(kit.cache())
    (check,) = crosscheck.compare_days(archive_days, files, _mapper(kit), (WINDOW,))
    assert check.day_files == 10
    assert check.rows_csv == check.rows_day_files == check.rows_matched == 9
    assert check.only_csv == check.only_day_files == []
    assert check.county_days == 2 * len(crosscheck.CHECK_COUNTIES)
    assert check.county_days_agree == check.county_days
    assert check.counties["44007"] == {"days": 2, "agree": 2, "with_events": 1}
    record = check.as_json()
    assert record["first_day"] == "2025-02-06"
    assert record["disagreements"] == []


def test_compare_window_reports_differences(kit: "Kit") -> None:
    """The real rows, with one day-file row dropped and one moved (synthetic edits)."""
    csv_rows, _ = archive.read_rows(kit.text("iem-2024-2025.csv"))
    day_rows = _day_rows(kit)
    target = next(r for r in day_rows if r.event_key == "BOX.WW.Y.0005.2025" and r.ugc == "RIZ001")
    edited = [r for r in day_rows if r is not target]
    moved = replace(target, ugc="RIZ008")
    check = crosscheck.compare_window(WINDOW, csv_rows, [*edited, moved], _mapper(kit), ("44007",))
    assert check.rows_matched == check.rows_csv - 1
    assert check.only_csv == ["BOX.WW.Y.0005.2025 RIZ001 2025-02-06T12:00Z..2025-02-07T00:00Z"]
    assert check.only_day_files == [
        "BOX.WW.Y.0005.2025 RIZ008 2025-02-06T12:00Z..2025-02-07T00:00Z"
    ]
    # RIZ002 still covers Providence County on the 6th: the county days agree.
    assert check.county_days_agree == 2
    alone = [r for r in edited if not (r.event_key == "BOX.WW.Y.0005.2025" and r.ugc == "RIZ002")]
    check = crosscheck.compare_window(WINDOW, csv_rows, alone, _mapper(kit), ("44007",))
    assert check.disagreements == ["44007 2025-02-06: csv ['WW.Y'] day files []"]


def test_compare_days_needs_the_school_year(kit: "Kit") -> None:
    files = archive.load_years(kit.cache(), [2018])
    with pytest.raises(ValueError, match="no school-year file"):
        crosscheck.compare_days(
            crosscheck.make_day_archive(kit.cache()), files, _mapper(kit), (WINDOW,)
        )


@pytest.mark.parametrize(
    ("ours", "theirs", "counties", "reason"),
    [
        ("Northwest Providence", "Northwest Providence", ["Providence"], "same name"),
        ("Chester", "Western Chester", ["Western Chester"], "one name holds the other"),
        (
            "Uncompahgre Plateu/Dallas Divide",
            "Uncompahgre Plateau/Dallas Divide",
            ["Delta", "Mesa", "Montrose", "Ouray", "San Miguel"],
            "spelling",
        ),
        (
            "West Slopes North Central Cascdes",
            "West Slopes North Central Cascades and Passes",
            ["King", "Snohomish"],
            "spelling",
        ),
        ("Inland Pasco", "Coastal Pasco", ["Pasco"], "names the same counties"),
        (
            "Blackfoot Region",
            "Potomac/Seeley Lake Region",
            ["Granite", "Lake", "Missoula", "Powell"],
            None,
        ),
        ("Caribou Range", "Wood River Foothills", ["Blaine"], None),
    ],
)
def test_names_agree(ours: str, theirs: str, counties: list[str], reason: str | None) -> None:
    """Names bp02ap19 and IEM gave one zone code, with the release's county names (all real)."""
    assert crosscheck.names_agree(ours, theirs, counties) == reason


def test_compare_zone_names(kit: "Kit") -> None:
    release = zones.ZoneRelease.from_records(
        "bp02ap19", zones.read_release(kit.bytes("bp02ap19.dbx").decode("latin-1"), "bp02ap19")
    )
    (check,) = crosscheck.compare_zone_names(
        kit.cache(), {2018: {"RIZ001", "RIZ008", "MTZ043", "IDZ075", "WYZ198"}}, release
    )
    assert check.valid == "2019-01-15T12:00Z"
    assert check.zones == 5
    assert check.same == 2
    assert check.left_out_zones == ["IDZ075", "MTZ043"]
    assert check.missing_in_iem == ["WYZ198"]
    assert check.as_json()["left_out"] == check.left_out


def test_read_ugc_names_rejects_other_documents() -> None:
    assert crosscheck.read_ugc_names('{"data": [{"ugc": "RIZ001", "name": null}, 3]}') == {
        "RIZ001": ""
    }
    with pytest.raises(ValueError, match="no data table"):
        crosscheck.read_ugc_names('{"rows": []}')
    assert crosscheck.ugcs_url(datetime(2019, 1, 15, 12, tzinfo=UTC)) == (
        "https://mesonet.agron.iastate.edu/api/1/nws/ugcs.json?valid=2019-01-15T12:00Z"
    )
