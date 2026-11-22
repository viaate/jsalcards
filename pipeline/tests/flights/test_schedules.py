"""The usual flights' order: every row has one place, so the routes files repeat byte for byte."""

import polars as pl

from snowlight.flights import schedules


def _sched() -> pl.DataFrame:
    # One flight number flown twice from the same airport at the same time, to the same place,
    # landing at two times on different weekdays: the rows the old sort left tied (R4-S2).
    rows = (
        [("AA", 892, "MCI", "MIA", 600, 1010, weekday, 4, 0, 1) for weekday in (1, 2, 3)]
        + [("AA", 892, "MCI", "MIA", 600, 1020, weekday, 4, 1, 0) for weekday in (5, 6)]
        + [("WN", 10, "MCI", "DEN", 700, 800, 1, 4, 0, 0)]
    )
    return pl.DataFrame(
        rows,
        schema=[
            "carrier",
            "number",
            "dep_apt",
            "arr_apt",
            "dep_time",
            "arr_time",
            "weekday",
            "days",
            "canc",
            "late",
        ],
        orient="row",
    )


def test_the_usual_flights_come_out_in_one_order_whatever_the_rows_order() -> None:
    sched = _sched()
    first = schedules.month_flights(sched)
    for seed in range(8):
        again = schedules.month_flights(sched.sample(fraction=1.0, shuffle=True, seed=seed))
        assert again.write_csv() == first.write_csv()
    assert first.get_column("arr_time").to_list()[:2] == [1010, 1020]
