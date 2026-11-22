"""Blocks, and one BTS month reduced to its compact tables."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from flights.synth import bts_rows, write_csv, zipped
from snowlight.flights import bts
from snowlight.flights.blocks import Block, block_day, block_of_hour, hhmm_hour


@pytest.mark.parametrize(
    ("hour", "block"),
    [
        (5, Block.EARLY),
        (8, Block.EARLY),
        (9, Block.MORNING),
        (12, Block.AFTERNOON),
        (17, Block.EVENING),
        (21, Block.NIGHT),
        (0, Block.NIGHT),
        (4, Block.NIGHT),
    ],
)
def test_block_of_hour(hour: int, block: Block) -> None:
    assert block_of_hour(hour) is block


def test_block_of_hour_refuses_a_non_hour() -> None:
    with pytest.raises(ValueError, match="hour"):
        block_of_hour(24)


def test_the_night_belongs_to_the_day_it_starts() -> None:
    assert block_day(date(2026, 1, 6), 0) == date(2026, 1, 5)
    assert block_day(date(2026, 1, 6), 5) == date(2026, 1, 6)
    assert hhmm_hour(2400) == 0
    assert hhmm_hour(1640) == 16
    with pytest.raises(ValueError, match="clock"):
        hhmm_hour(2500)


def test_month_helpers() -> None:
    month = bts.Month.parse("2026-09")
    assert month == bts.Month.parse("2026_9")
    assert month.key == "2026_9"
    assert month.next() == bts.Month(2026, 10)
    assert bts.Month(2026, 12).next() == bts.Month(2027, 1)
    assert month.back(9) == bts.Month(2025, 12)
    assert month.first == date(2026, 9, 1)
    assert month.url().endswith("_2026_9.zip")
    assert [m.key for m in bts.months(bts.Month(2025, 11), bts.Month(2026, 2))] == [
        "2025_11",
        "2025_12",
        "2026_1",
        "2026_2",
    ]
    with pytest.raises(ValueError, match="month"):
        bts.Month.parse("2026-13")


DAY = date(2026, 1, 5)
FLIGHTS = [
    {"carrier": "ZZ", "number": 10, "dep": "AAA", "arr": "BBB", "dep_time": 600, "arr_time": 900},
    {
        "carrier": "ZZ",
        "number": 11,
        "dep": "AAA",
        "arr": "BBB",
        "dep_time": 610,
        "arr_time": 905,
        "cancelled": True,
        "dep_delay": "",
        "arr_delay": "",
    },
    {
        "carrier": "YY",
        "number": 20,
        "dep": "AAA",
        "arr": "BBB",
        "dep_time": 2330,
        "arr_time": 130,
        "dep_delay": "50.00",
        "arr_delay": "60.00",
    },
    {"carrier": "YY", "number": 21, "dep": "BBB", "arr": "AAA", "dep_time": 30, "arr_time": 200},
]


def test_a_month_reduces_to_its_tables(tmp_path: Path) -> None:
    rows = bts_rows(DAY, FLIGHTS)
    rows.append({**rows[0], "Flight_Number_Reporting_Airline": "", "CRSDepTime": ""})
    tables = bts.reduce_csv(write_csv(tmp_path / "m.csv", rows))
    dep = tables["dep"]
    early = dep.filter((pl.col("apt") == "AAA") & (pl.col("block") == int(Block.EARLY)))
    assert early.select("carrier", "n", "canc", "late").rows() == [("ZZ", 2, 1, 0)]
    night = dep.filter((pl.col("apt") == "AAA") & (pl.col("block") == int(Block.NIGHT)))
    assert night.select("day", "n", "late").rows() == [(DAY, 1, 1)]
    # 00:30 on the 5th is the night of the 4th.
    bbb = dep.filter(pl.col("apt") == "BBB")
    assert bbb.select("day", "block").rows() == [(date(2026, 1, 4), int(Block.NIGHT))]
    arr = tables["arr"]
    # 23:30 to 01:30 lands the next calendar day, still the night of the 5th.
    late_night = arr.filter((pl.col("apt") == "BBB") & (pl.col("block") == int(Block.NIGHT)))
    assert late_night.select("day", "n", "late").rows() == [(DAY, 1, 1)]
    sched = tables["sched"]
    assert sched.height == 4
    assert set(tables["places"]["apt"]) == {"AAA", "BBB"}
    legs = tables["legs"]
    assert legs.height == 4
    assert legs.filter(pl.col("cancelled")).height == 1


def test_the_usual_flights_leave_out_a_non_weather_span(tmp_path: Path) -> None:
    # Nov 2025: the 10th (inside the FAA's ordered cuts) and the 17th (after them).
    cut, after = date(2025, 11, 10), date(2025, 11, 17)
    rows = bts_rows(cut, [{**FLIGHTS[1]}]) + bts_rows(after, [{**FLIGHTS[1], "cancelled": False}])
    tables = bts.reduce_csv(write_csv(tmp_path / "m.csv", rows))
    sched = tables["sched"].filter(pl.col("number") == 11)
    assert sched.select("days", "canc").rows() == [(1, 0)]
    # Every other table keeps the span (the fit and the records leave it out themselves).
    assert tables["dep"].filter(pl.col("day") == cut).height == 1


def test_months_are_kept_whole(tmp_path: Path) -> None:
    archive = tmp_path / "2026_1.zip"
    archive.write_bytes(zipped(bts_rows(DAY, FLIGHTS)))
    tables = bts.reduce_zip(archive, tmp_path)
    assert not list(tmp_path.glob("*.csv"))
    root = tmp_path / "bts"
    month = bts.Month(2026, 1)
    assert not bts.has_month(root, month)
    bts.write_month(root, month, tables)
    assert bts.has_month(root, month)
    assert bts.kept_months(root) == [month]
    assert bts.scan(root, "dep").collect().height == tables["dep"].height


def test_a_zip_without_one_csv_is_refused(tmp_path: Path) -> None:
    import zipfile  # noqa: PLC0415

    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("readme.html", "x")
    with pytest.raises(ValueError, match="one CSV"):
        bts.reduce_zip(archive, tmp_path)
