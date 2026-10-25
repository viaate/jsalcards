"""The label-night forecast extract: nights, files as of 21:00, values (synthetic GRIB)."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from predict import grib
from snowlight.predict import ndfd
from snowlight.predict.forecast_history import Schools
from snowlight.predict.ndfd import Element, Host, Listed
from snowlight.predict.night_extract import (
    NIGHTS_PATH,
    VALUE_COLUMNS,
    WX_UNKNOWN,
    ExtractError,
    Night,
    available_at,
    check_runs,
    choose_files,
    district_mode,
    extract_night,
    load_nights,
    local_times,
    night_districts,
    own_file,
    row_counts,
    runs_frame,
    write_frames,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "label-night-forecast-extract.yml"
NIGHT = Night(date(2024, 1, 16), "America/New_York")
"""Its snapshot is 02:00 UTC on 2024-01-16 (21:00 EST on the 15th)."""


def listed(element: Element, stamp: str, written: str | None = None) -> Listed:
    when = grib.utc(stamp)
    return Listed(
        element,
        when,
        f"https://example.invalid/{element.heading}_{when:%Y%m%d%H%M}",
        Host.AWS,
        None if written is None else grib.utc(written),
    )


def test_nights_read_from_the_list_and_the_committed_list_reads() -> None:
    text = (
        "nights:\n  - {day: 2024-01-16, zone: America/New_York}\n"
        "  - {day: 2023-02-28, zone: America/New_York}\n"
    )
    nights = load_nights(text)
    assert nights == [Night(date(2023, 2, 28), "America/New_York"), NIGHT]
    assert NIGHT.snapshot == datetime(2024, 1, 16, 2, 0, tzinfo=UTC)
    # Daylight time: 21:00 EDT on 2023-03-13 is 01:00 UTC.
    assert Night(date(2023, 3, 14), "America/New_York").snapshot == datetime(
        2023, 3, 14, 1, 0, tzinfo=UTC
    )
    for bad in (
        "nights: []",
        "nights:\n  - {day: 2024-01-16}",
        "nights:\n  - {day: 2024-01-16, zone: Mars/Base}",
        "nights:\n  - {day: 2024-01-16, zone: UTC}\n  - {day: 2024-01-16, zone: UTC}",
    ):
        with pytest.raises(ExtractError):
            load_nights(bad)
    committed = load_nights(NIGHTS_PATH.read_text(encoding="utf-8"))
    assert len(committed) == 56
    assert min(night.day for night in committed) >= date(2018, 8, 15)
    # Only days and zones: nothing in it names a district.
    assert set(yaml.safe_load(NIGHTS_PATH.read_text())["nights"][0]) == {"day", "zone"}


def test_a_nights_districts_are_those_whose_own_21_is_the_same_instant() -> None:
    schools = Schools(
        np.array([40.0, 33.4, 39.7, 34.0]),
        np.array([-74.0, -112.0, -105.0, -118.2]),
        np.array([0, 1, 2, 3]),
        ("nj", "az", "co", "ca"),
        ("America/New_York", "America/Phoenix", "America/Denver", "America/Los_Angeles"),
    )
    winter = night_districts(Night(date(2024, 1, 16), "America/Denver"), schools)
    assert winter.tolist() == [1, 2]  # Phoenix keeps Denver's time in winter
    spring = night_districts(Night(date(2023, 3, 14), "America/Los_Angeles"), schools)
    assert spring.tolist() == [1, 3]  # and Los Angeles's in daylight time


def test_a_file_counts_from_its_stamp_and_delay_and_never_before_it_was_written() -> None:
    on_time = listed(Element.TEMP, "2024-01-16T01:16", "2024-01-16T01:18")
    late = listed(Element.TEMP, "2024-01-16T01:46", "2024-01-16T02:05")
    assert available_at(on_time) == grib.utc("2024-01-16T01:26")
    assert available_at(late) == grib.utc("2024-01-16T02:05")
    at = NIGHT.snapshot
    assert own_file([on_time, late], Element.TEMP, at) == on_time
    assert own_file([on_time], Element.QPF, at) is None
    old = listed(Element.TEMP, "2024-01-15T22:46")
    assert own_file([old], Element.TEMP, at) is None  # over 3 hours old


def test_run_elements_come_from_the_run_and_the_others_from_their_own_files() -> None:
    files = [
        listed(Element.SNOW, "2024-01-16T01:46", "2024-01-16T01:50"),
        listed(Element.ICE, "2024-01-16T01:46", "2024-01-16T01:50"),
        # Apparent temperature of the 01:46 run is written late: the run counts at 02:05.
        listed(Element.APT, "2024-01-16T01:47", "2024-01-16T02:05"),
        listed(Element.SNOW, "2024-01-16T01:16", "2024-01-16T01:20"),
        listed(Element.ICE, "2024-01-16T01:16", "2024-01-16T01:20"),
        listed(Element.APT, "2024-01-16T01:16", "2024-01-16T01:20"),
        listed(Element.TEMP, "2024-01-16T01:47", "2024-01-16T01:50"),
        listed(Element.POP12, "2024-01-16T01:46", "2024-01-16T01:50"),
    ]
    chosen, missing = choose_files(NIGHT, files)
    assert {e: c.listed.stamp for e, c in chosen.items()} == {
        Element.SNOW: grib.utc("2024-01-16T01:16"),
        Element.ICE: grib.utc("2024-01-16T01:16"),
        Element.APT: grib.utc("2024-01-16T01:16"),
        Element.TEMP: grib.utc("2024-01-16T01:47"),
        Element.POP12: grib.utc("2024-01-16T01:46"),
    }
    assert missing == ["qpf: no file", "wx: no file"]
    assert all(c.available <= NIGHT.snapshot for c in chosen.values())


def test_local_hours_and_the_most_common_string() -> None:
    times = local_times(date(2024, 1, 16), "America/Chicago", (-3, 7))
    assert times == {grib.utc("2024-01-16T03:00"): -3, grib.utc("2024-01-16T13:00"): 7}
    groups = ndfd.groups_of(np.array([0, 0, 0, 1, 1, 2]))
    found = district_mode(np.array([2, 1, 2, 3, 1, -1]), groups)
    assert found.tolist() == [2, 1, WX_UNKNOWN]  # a tie goes to the smaller code


def night_files() -> tuple[list[Listed], dict[str, bytes]]:
    """Every element of the 01:46 UTC run of 2024-01-16 (reference time 01:50; it counts from
    01:56, before the 02:00 snapshot), as synthetic files."""
    reference = grib.utc("2024-01-16T01:50")
    store: dict[str, bytes] = {}
    files: list[Listed] = []

    def add(element: Element, messages: list[bytes]) -> None:
        item = listed(element, "2024-01-16T01:46", "2024-01-16T01:48")
        files.append(item)
        store[item.url] = grib.framed(messages, f"{element.heading} KWBN 160146")

    def hours_to(end: datetime) -> float:
        return (end - reference).total_seconds() / 3600

    def periods(parameter: tuple[int, int, int], value: float) -> list[bytes]:
        ends = [grib.utc(f"2024-01-16T{h:02d}:00") for h in (6, 12, 18)]
        ends.append(grib.utc("2024-01-17T00:00"))
        first = grib.message(parameter, reference, lead_hours=0, end=ends[0], values=value)
        rest = [
            grib.message(parameter, reference, lead_hours=hours_to(end) - 6, end=end, values=value)
            for end in ends[1:]
        ]  # fmt: skip
        return [first, *rest]

    def hourly(parameter: tuple[int, int, int], value: float, hours: int) -> list[bytes]:
        return [
            grib.message(parameter, reference, lead_hours=lead + 10 / 60, values=value)
            for lead in range(1, hours)
        ]

    add(Element.SNOW, periods(Element.SNOW.parameter, 0.0254))  # 1 inch a period
    add(Element.ICE, periods(Element.ICE.parameter, 2.54))  # a tenth of an inch
    add(Element.QPF, periods(Element.QPF.parameter, 5.08))  # 0.2 inch of liquid
    pop = [
        grib.as_probability(
            grib.message(Element.POP12.parameter, reference, lead_hours=0,
                         end=grib.utc("2024-01-16T12:00"), values=80.0),
            grib.utc("2024-01-16T12:00"), 10 + 10 / 60,
        ),
        grib.as_probability(
            grib.message(Element.POP12.parameter, reference, lead_hours=10 + 10 / 60,
                         end=grib.utc("2024-01-17T00:00"), values=40.0),
            grib.utc("2024-01-17T00:00"), 12,
        ),
    ]  # fmt: skip
    add(Element.POP12, pop)
    add(Element.TEMP, hourly(Element.TEMP.parameter, 272.15, 11))  # 30.2 F, to 12 UTC
    add(Element.APT, hourly(Element.APT.parameter, 263.15, 11))  # 14 F
    strings = ["<NoCov>:<NoWx>:<NoInten>:<NoVis>:", "Lkly:S:-:<NoVis>:"]
    wx = [
        grib.with_strings(grib.message(Element.WX.parameter, reference, lead_hours=lead + 10 / 60,
                                       values=1.0, bits=8), strings)
        for lead in range(1, 16)
    ]  # fmt: skip
    add(Element.WX, wx)
    return files, store


def test_a_night_reads_every_element_for_every_district_of_its_time() -> None:
    files, store = night_files()
    schools = Schools(
        np.array([41.0, 41.1, 40.7, 33.4]),
        np.array([-73.5, -73.4, -74.0, -112.0]),
        np.array([0, 0, 1, 2]),
        ("ct", "nj", "az"),
        ("America/New_York", "America/New_York", "America/Phoenix"),
    )

    def opener(item: Listed) -> ndfd.Ranged:
        return ndfd.bytes_reader(store[item.url])

    found = extract_night(NIGHT, schools, files, opener, 0.5)
    assert found.errors == []
    values = found.values
    assert values is not None
    assert values["district"].to_list() == ["ct", "nj"]  # Phoenix's 21:00 is another instant
    assert values.columns == ["day", "zone", "district", *VALUE_COLUMNS]
    row = values.row(0, named=True)
    assert np.isnan(row["snow_e00"])  # over before the run
    assert row["snow_e06"] == pytest.approx(1.0)
    assert row["snow_e24"] == pytest.approx(1.0)
    assert row["snow_window"] == pytest.approx(3.0)  # 06, 12 and 18 UTC
    assert row["ice_window"] == pytest.approx(0.3)
    assert row["qpf_e12"] == pytest.approx(0.2)
    assert row["pop_e12"] == pytest.approx(80.0)
    assert row["pop_e24"] == pytest.approx(40.0)
    assert np.isnan(row["pop_e00"])
    assert row["temp_h07"] == pytest.approx(30.2, abs=0.01)
    assert row["apt_h05"] == pytest.approx(14.0, abs=0.01)
    assert np.isnan(row["temp_h08"])  # 13 UTC is past the file's hours
    wx = found.wx
    assert wx is not None
    first = wx.filter(pl.col("district") == "ct")
    assert set(first["wx"]) == {"Lkly:S:-:<NoVis>:"}
    assert first["local_hour"].to_list() == list(range(-2, 13))  # 21:00 is the run's own hour
    runs = runs_frame(found.runs)
    assert runs.height == 7
    assert check_runs(runs) == []
    assert set(runs["messages"].to_list()) >= {2, 3}
    counts = row_counts(values)
    assert counts["2024-01-16 America/New_York"] == {
        "apt": 2, "ice": 2, "pop": 2, "qpf": 2, "snow": 2, "temp": 2,
    }  # fmt: skip


def test_an_element_that_does_not_read_stays_unknown_and_the_others_count() -> None:
    files, store = night_files()
    pop = next(item for item in files if item.element is Element.POP12)
    store[pop.url] = b"not a GRIB file at all" * 100
    schools = Schools(
        np.array([41.0]), np.array([-73.5]), np.array([0]), ("ct",), ("America/New_York",)
    )
    found = extract_night(
        NIGHT, schools, files, lambda item: ndfd.bytes_reader(store[item.url]), 0.5
    )
    assert any(error.startswith("pop12:") for error in found.errors)
    assert found.values is not None
    row = found.values.row(0, named=True)
    assert np.isnan(row["pop_e12"])
    assert row["snow_e06"] == pytest.approx(1.0)


def test_a_file_that_counts_after_its_snapshot_is_named() -> None:
    late = {
        "day": NIGHT.day, "zone": NIGHT.zone, "snapshot": NIGHT.snapshot, "element": "temp",
        "stamp": NIGHT.snapshot, "run_time": NIGHT.snapshot, "host": "aws",
        "last_modified": NIGHT.snapshot, "available_at": NIGHT.snapshot + timedelta(minutes=1),
        "url": "u", "reference": None, "messages": 0, "error": None,
    }  # fmt: skip
    assert len(check_runs(runs_frame([late]))) == 1


def test_frames_are_written_sorted(tmp_path: Path) -> None:
    parts = [
        pl.DataFrame({"day": [NIGHT.day], "zone": ["z"], "district": ["b"]}),
        pl.DataFrame({"day": [NIGHT.day], "zone": ["z"], "district": ["a"]}),
    ]
    path = write_frames(tmp_path, "values.parquet", parts)
    assert pl.read_parquet(path)["district"].to_list() == ["a", "b"]


def test_the_workflow_runs_only_when_its_own_file_changes_and_keeps_an_artifact() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert workflow["name"] == "label-night forecast extract"
    triggers = workflow[True]
    assert triggers == {"push": {"paths": [".github/workflows/label-night-forecast-extract.yml"]}}
    assert workflow["permissions"]["contents"] == "read"
    (job,) = workflow["jobs"].values()
    runs = " ".join(str(step.get("run", "")) for step in job["steps"])
    assert "uv sync --locked --no-dev" in runs
    assert "snowlight predict night-extract" in runs
    assert "git push" not in runs
    assert "git commit" not in runs
    (upload,) = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/upload")]
    assert upload["with"]["retention-days"] == 90
    assert upload["with"]["name"] == "label-night-forecast-extract"


def test_a_tie_in_the_weather_strings_goes_to_the_first_in_that_messages_own_table() -> None:
    files, store = night_files()
    reference = grib.utc("2024-01-16T01:50")
    lat, lon = np.array([41.0, 41.1]), np.array([-73.5, -73.4])  # ct's two schools
    where = ndfd.cells(lat, lon)
    assert where.inside.all()
    assert (int(where.row[0]), int(where.col[0])) != (int(where.row[1]), int(where.col[1]))
    grid = np.zeros(ndfd.NY * ndfd.NX)
    grid[int(where.row[1]) * ndfd.NX + int(where.col[1])] = 1.0  # school 2 reads index 1
    snow, rain = "Lkly:S:-:<NoVis>:", "Chc:R:-:<NoVis>:"
    # The first hour's table lists snow first; every later hour's lists rain first. Each hour
    # the two schools disagree, one each: a tie, so the string first in that message wins.
    wx = [
        grib.with_strings(
            grib.message(Element.WX.parameter, reference, lead_hours=lead + 10 / 60,
                         values=grid, bits=8),
            [snow, rain] if lead == 1 else [rain, snow],
        )
        for lead in range(1, 16)
    ]  # fmt: skip
    item = next(item for item in files if item.element is Element.WX)
    store[item.url] = grib.framed(wx, f"{Element.WX.heading} KWBN 160146")
    schools = Schools(lat, lon, np.array([0, 0]), ("ct",), ("America/New_York",))
    found = extract_night(NIGHT, schools, files, lambda f: ndfd.bytes_reader(store[f.url]), 0.5)
    assert found.wx is not None
    by_hour = dict(zip(found.wx["local_hour"].to_list(), found.wx["wx"].to_list(), strict=True))
    assert by_hour[-2] == snow  # 03 UTC, the first message: snow first in its table
    assert {by_hour[hour] for hour in range(-1, 13)} == {rain}  # rain first in theirs
