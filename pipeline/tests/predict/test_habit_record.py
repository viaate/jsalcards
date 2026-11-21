"""Each district's complete record (records-mo MO-3): charter LEAs' own classes, the counts, the
same-day share of the districts near it and its rounding, the verdict, and the committed file."""

from datetime import date, timedelta
from fractions import Fraction

import polars as pl
import pytest

from snowlight.predict import habit_record, state_records, train
from snowlight.predict.alerts_history import district_day_classes
from snowlight.predict.habit_record import FullRecordError, FullRow, full_rows, half_up, verdict
from snowlight.predict.open_days import AlertDay

DAY = date(2025, 1, 14)


def day(leaid: str, outcome: str, on: date = DAY, kind: str = "advisory") -> AlertDay:
    return AlertDay(leaid, on, kind, outcome)  # type: ignore[arg-type]


def test_a_charter_lea_gets_its_own_class_and_the_districts_classes_do_not_move() -> None:
    schools = pl.DataFrame(
        {
            "index": [0, 1, 2, 3],
            "kind": ["public", "public", "public", "private"],
            "district_id": ["2900001", "2900001", "2900002", None],
            "kind_flags": [0, train.CHARTER_FLAG, train.CHARTER_FLAG, 0],
        }
    )
    charter = train.charter_lea_schools(schools)
    assert charter["index"].to_list() == [2]  # only the LEA with no eligible school
    eligible = train.eligible_schools(schools)
    classes = pl.DataFrame(
        {"school": [0, 1, 2], "day": [DAY] * 3, "weather": [1, 5, 5]},
        schema={"school": pl.Int64, "day": pl.Date, "weather": pl.Int8},
    )
    of = eligible.select(
        pl.col("index").cast(pl.Int64).alias("school"), pl.col("district_id").alias("district")
    )
    found = district_day_classes(classes, of, 0.5)
    assert found.rows() == [("2900001", DAY, 1)]  # the charter school 1 never counts
    of_charter = charter.select(
        pl.col("index").cast(pl.Int64).alias("school"), pl.col("district_id").alias("district")
    )
    assert district_day_classes(classes, of_charter, 0.5).rows() == [("2900002", DAY, 5)]


def test_the_share_of_districts_near_it_counts_home_as_no_school() -> None:
    area = {"a": "EAX", "b": "EAX", "c": "EAX", "d": "LSX"}
    kept = [day("a", "open"), day("b", "remote"), day("c", "open"), day("d", "closed")]
    rows = {r.leaid: r for r in full_rows(kept, area, {"a": 5}, near=1)}
    # a's peers near it: b (home) and c (open): 1 of 2; d's peers: none, so d has no row
    assert rows["a"] == FullRow("a", "advisory", 1, 0, 0, 0, 50, 5, "EAX")
    assert rows["b"].same100 == 0  # a and c had school
    assert rows["b"].home == rows["b"].no_school == 1
    assert "d" not in rows


def test_some_and_unknown_days_are_left_out_and_kinds_are_apart() -> None:
    area = dict.fromkeys("abc", "EAX")
    kept = [
        day("a", "short"),
        day("b", "some"),
        day("c", "closed"),
        day("a", "makeup", DAY + timedelta(days=1)),
        day("c", "closed", DAY + timedelta(days=1), "warning"),
    ]
    rows = full_rows(kept, area, {}, near=1)
    by = {(r.leaid, r.kind): r for r in rows}
    assert by["a", "advisory"] == FullRow("a", "advisory", 1, 0, 0, 1, 100, 0, "EAX")
    assert ("b", "advisory") not in by
    assert ("c", "warning") not in by  # no district near it had a warning day that date
    assert by["c", "advisory"].same100 == 0


def test_same100_is_rounded_half_up_over_the_sum_of_the_shares() -> None:
    assert half_up(Fraction(1, 2)) == 1
    assert half_up(Fraction(5, 2)) == 3
    assert half_up(Fraction(249, 100)) == 2
    # three days with peer shares 1/3, 1/3 and 1/2: 100 x 7/6 = 116.67 -> 117
    area = dict.fromkeys("abcdefg", "EAX")
    d2, d3 = DAY + timedelta(days=1), DAY + timedelta(days=2)
    kept = [
        day("a", "open"), day("b", "closed"), day("c", "open"), day("d", "open"),
        day("a", "open", d2), day("e", "closed", d2), day("f", "open", d2), day("g", "open", d2),
        day("a", "closed", d3), day("b", "closed", d3), day("c", "open", d3),
    ]  # fmt: skip
    rows = {r.leaid: r for r in full_rows(kept, area, {}, near=1)}
    assert rows["a"].same100 == 117
    assert rows["a"].days == 3


def test_a_day_with_fewer_than_five_districts_near_it_is_left_out() -> None:
    area = dict.fromkeys("abcdefg", "EAX")
    d2 = DAY + timedelta(days=1)
    kept = [day(u, "closed") for u in "abcde"] + [day(u, "closed", d2) for u in "abcdef"]
    rows = {r.leaid: r for r in full_rows(kept, area, {})}
    assert habit_record.HABIT_NEAR == 5
    # DAY: 4 districts near each, left out; d2: 5 near each, counted (f only has d2)
    assert {u: r.days for u, r in rows.items()} == dict.fromkeys("abcdef", 1)
    assert "g" not in rows


def test_a_row_that_does_not_add_up_is_refused() -> None:
    for bad in (
        FullRow("a", "advisory", 5, 3, 4, 0, 100, 1, "EAX"),
        FullRow("a", "advisory", 5, 3, 0, 3, 100, 1, "EAX"),
        FullRow("a", "advisory", 5, 3, 0, 0, 501, 1, "EAX"),
        FullRow("a", "advisory", 0, 0, 0, 0, 0, 1, "EAX"),
    ):
        with pytest.raises(FullRecordError, match="does not add up"):
            bad.check()
    good = FullRow("2900001", "warning", 6, 6, 2, 0, 595, 5, "EAX")
    data = habit_record.record_file([good])
    assert habit_record.read_record_file(data) == [good]
    with pytest.raises(FullRecordError, match="twice"):
        habit_record.read_record_file(data + data.split(b"\n", 1)[1])


def test_the_verdict_matches_the_panel_and_a_holds_out_on_one_school_day_is_no_verdict() -> None:
    assert verdict(8, 11, 0.433) == "close"
    assert verdict(7, 13, 0.552) == "like"
    assert verdict(4, 4, 0.5) is None  # under 5 days
    assert verdict(1, 11, 0.598) == "hold"
    # 6 of 7 when the districts near it had no school 99.7% of the time: one day with school
    assert habit_record.tails(7, 6, 0.997)[0] < habit_record.HABIT_LUCK
    assert verdict(6, 7, 0.997) is None  # the test says it is not like them: never "like"
    assert verdict(5, 7, 0.997) == "hold"


def test_the_stored_share_gives_the_exact_shares_verdict_on_a_boundary() -> None:
    # 3 no-school days of 11 (spec same-round.txt's case): a sum of peer shares near where the
    # verdict turns, where tenths (same10) would flip it and hundredths (same100) do not
    days, no = 11, 3
    found = []
    for thousandths in range(5000, 8000):
        exact = Fraction(thousandths, 1000)
        tenths = Fraction(half_up(10 * exact), 10)
        if verdict(no, days, float(exact / days)) != verdict(no, days, float(tenths / days)):
            found.append(exact)
    assert found  # same10 would flip a verdict here
    for exact in found:
        row = FullRow("a", "advisory", days, no, 0, 0, half_up(100 * exact), 1, "EAX")
        assert verdict(no, days, float(exact / days)) == verdict(
            no, days, habit_record.stored_share(row)
        ) or abs(100 * exact - row.same100) == Fraction(1, 2)


def test_the_committed_record_file_holds_kansas_city_33s_rows() -> None:
    mo = state_records.load().states["mo"]
    assert mo.full_record is not None
    rows = habit_record.read_record_file(state_records.read_derived(mo, mo.full_record.name))
    assert len(rows) == mo.full_record.rows == 1522  # 556 + 533 + 433
    kc33 = {r.kind: r for r in rows if r.leaid == "2916400"}
    assert kc33["advisory"] == FullRow("2916400", "advisory", 13, 7, 2, 1, 720, 5, "EAX")
    assert (kc33["warning"].days, kc33["warning"].no_school, kc33["warning"].home) == (6, 6, 2)
    assert {r.area for r in rows if r.leaid in {"2916400", "2922800", "2918300"}} == {"EAX"}
    assert set(mo.ids.values()) >= {r.leaid for r in rows}


def test_each_countys_office_is_the_one_of_most_of_its_zones() -> None:
    line = "MO|{z}|{cwa}|Zone|MO{z}|County|{fips}|C|C|39.0|-94.5"
    text = "\n".join(
        line.format(z=z, cwa=cwa, fips=fips)
        for z, cwa, fips in (
            ("001", "EAX", "29095"),
            ("002", "EAX", "29095"),
            ("003", "SGF", "29095"),
            ("004", "LSX", "29510"),
            ("005", "DMX", "19001"),
        )
    )
    assert state_records.office_of_county(text, "bp", "29") == {"29095": "EAX", "29510": "LSX"}
