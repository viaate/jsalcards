"""The long history pull (FL-1b.2) and the non-weather spans of FL-1b.0, on made-up data only."""

import bz2
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import polars as pl
import pytest

from flights.synth import AIRPORTS
from snowlight.flights import airports, bts, monthly, pull, records, spans, train
from snowlight.flights.bts import Month
from snowlight.schemas.flights import FlightsMonthScore, FlightsTarget

MOS_CSV = (
    "runtime,ftime,model,tmp,vis,cig,station\n"
    "2019-01-27 00:00:00,2019-01-27 06:00:00,NBS,20,10,888,KAAA\n"
    "2019-01-27 00:00:00,2019-01-27 09:00:00,NBS,19,4,9,KAAA\n"
    "2019-01-27 07:00:00,2019-01-27 12:00:00,NBS,18,2,5,KAAA\n"
    "2019-01-28 00:00:00,2019-01-28 06:00:00,NBS,15,1,3,KAAA\n"
)


# --- the tasks -----------------------------------------------------------------------------------


def test_the_iem_queue_runs_the_overlap_then_nbs_then_mav_then_reports(tmp_path: Path) -> None:
    tasks = pull.iem_tasks(AIRPORTS, tmp_path, date(2026, 11, 23))
    sources = [task.source for task in tasks]
    order = [sources.index(s) for s in ("nbsx", "nbs", "mav", "asos")]
    assert order == sorted(order)
    assert sources.count("nbs") == 2 * len(AIRPORTS)
    assert sources.count("nbsx") == len(AIRPORTS)
    first = tasks[sources.index("nbs")]
    assert "model=NBS" in first.url
    assert "sts=2018-11-07T00:00Z" in first.url
    assert "ets=2019-06-30T23:00Z" in first.url  # IEM's end is included: the day before
    keys = [task.key for task in tasks]
    assert len(keys) == len(set(zip(sources, keys, strict=True)))
    # Every task keeps its table at its own path, so a run skips what it has.
    assert len({task.path for task in tasks}) == len(tasks)


def test_mav_is_avn_before_2003_12_16_and_gfs_from_it() -> None:
    spans_ = pull.mav_spans(date(2005, 3, 1))
    assert spans_[0] == ("AVN", date(2000, 6, 1), date(2001, 1, 1))
    assert ("AVN", date(2003, 1, 1), date(2003, 12, 16)) in spans_
    assert ("GFS", date(2003, 12, 16), date(2004, 1, 1)) in spans_
    assert spans_[-1] == ("GFS", date(2005, 1, 1), date(2005, 3, 1))
    assert all(first < end for _, first, end in spans_)
    assert pull.mav_spans(date(2000, 6, 1)) == []


def test_reports_are_months_of_twenty_stations(tmp_path: Path) -> None:
    stations = [f"S{i:02d}" for i in range(45)]
    tasks = pull.asos_tasks(stations, tmp_path)
    months = len(list(bts.months(pull.ASOS_FIRST, pull.ASOS_LAST)))
    assert len(tasks) == months * 3
    assert tasks[0].url.count("station=") == 20
    assert tasks[2].url.count("station=") == 5


# --- reducing ------------------------------------------------------------------------------------


def test_a_mos_table_keeps_only_the_00z_runs_as_iem_wrote_them() -> None:
    frame = pull.reduce_mos(MOS_CSV.encode())
    assert frame.height == 3
    assert frame.get_column("runtime").dt.hour().unique().to_list() == [0]
    assert frame.get_column("cig").to_list() == ["888", "9", "3"]
    assert frame.schema["ftime"] == pl.Datetime("us", "UTC")


@pytest.mark.parametrize(
    "body",
    [b"", b"ERROR: Too many requests from your IP\n", b"<html>busy</html>", b"station,x\n1,2\n"],
)
def test_a_body_that_is_not_the_table_is_never_kept(body: bytes) -> None:
    with pytest.raises(pull.NotTableError):
        pull.reduce_mos(body)


def test_reports_reduce_to_the_hourly_flags() -> None:
    body = (
        b"station,valid,sknt,gust,vsby,skyc1,skyc2,skyc3,skyl1,skyl2,skyl3,wxcodes\n"
        b"AAA,2005-01-22 06:53,10,M,0.5,OVC,M,M,800,M,M,SN\n"
    )
    task = pull.Task("asos", "2005_1_00", "x", Path("x"))
    frame = pull.reduce_task(task, body)
    assert frame.get_column("snow").to_list() == [True]
    with pytest.raises(pull.NotTableError):
        pull.reduce_task(task, b"#ERROR: no\n")


# --- the polite client ---------------------------------------------------------------------------


def test_the_us_day_asks_for_three_seconds_between_requests() -> None:
    assert pull.gap_at(datetime(2026, 11, 23, 12, 59, tzinfo=UTC)) == 2.0
    assert pull.gap_at(datetime(2026, 11, 23, 13, 0, tzinfo=UTC)) == 3.0
    assert pull.gap_at(datetime(2026, 11, 23, 0, 59, tzinfo=UTC)) == 3.0
    assert pull.gap_at(datetime(2026, 11, 23, 1, 0, tzinfo=UTC)) == 2.0


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def time(self) -> float:
        return self.now


def test_requests_wait_their_pause_and_a_busy_server_stretches_it(tmp_path: Path) -> None:
    clock = Clock()
    pacer = pull.Pacer(tmp_path / "last", lambda _m: 2.0, sleep=clock.sleep, clock=clock.time)
    pacer.wait()
    pacer.wait()
    assert clock.slept == [pytest.approx(2.0)]
    # A second process reads the same file and waits too.
    other = pull.Pacer(tmp_path / "last", lambda _m: 2.0, sleep=clock.sleep, clock=clock.time)
    other.wait()
    assert clock.slept[-1] == pytest.approx(2.0)
    pacer.slower()
    assert pacer.pause() == pytest.approx(4.0)
    for _ in range(pull.FASTER_AFTER):
        pacer.calm()
    assert pacer.pause() == pytest.approx(4.0 * 0.85)
    for _ in range(40):
        pacer.slower()
    assert pacer.pause() == pull.SLOW_MAX
    # A file that does not read starts again from the least pause.
    (tmp_path / "last").write_text("not json")
    assert pacer.pause() == 2.0


def test_a_busy_reply_backs_off_hard_and_doubles(tmp_path: Path) -> None:
    clock = Clock()
    pacer = pull.Pacer(tmp_path / "last", lambda _m: 2.0, sleep=clock.sleep, clock=clock.time)
    replies = [
        (429, b"slow down"),
        (200, b"Too many requests from your IP address"),
        (503, b""),
        (200, MOS_CSV.encode()),
    ]
    lines: list[str] = []
    body = pull.get_politely(lambda _u: replies.pop(0), "u", pacer, lines.append, sleep=clock.sleep)
    assert body == MOS_CSV.encode()
    backoffs = [s for s in clock.slept if s >= pull.BACKOFF_FIRST]
    assert backoffs == [60.0, 120.0, 240.0]
    assert len(lines) == 3
    assert pacer.pause() > 2.0


def test_a_missing_file_is_none_and_endless_failures_raise(tmp_path: Path) -> None:
    clock = Clock()
    pacer = pull.Pacer(tmp_path / "last", lambda _m: 2.0, sleep=clock.sleep, clock=clock.time)
    assert pull.get_politely(lambda _u: (404, b""), "u", pacer, print, sleep=clock.sleep) is None

    def refused(_u: str) -> tuple[int, bytes]:
        raise httpx.ConnectError("refused")

    with pytest.raises(pull.PullError):
        pull.get_politely(refused, "u", pacer, lambda _l: None, tries=3, sleep=clock.sleep)
    with pytest.raises(pull.PullError):
        pull.get_politely(
            lambda _u: (400, b"bad"), "u", pacer, lambda _l: None, tries=2, sleep=clock.sleep
        )
    assert max(clock.slept) <= pull.BACKOFF_MAX


def test_only_one_run_of_a_queue_at_a_time(tmp_path: Path) -> None:
    lock = tmp_path / "q.lock"
    with pull.only_one(lock), pytest.raises(pull.PullError), pull.only_one(lock):
        pass
    with pull.only_one(tmp_path / "q.lock"):
        pass


# --- the queue -----------------------------------------------------------------------------------


def test_the_queue_keeps_tables_holes_and_asks_failures_again(tmp_path: Path) -> None:
    tasks = [
        pull.Task("nbs", "a", "u/a", tmp_path / "nbs" / "a.parquet"),
        pull.Task("nbs", "b", "u/b", tmp_path / "nbs" / "b.parquet"),
        pull.Task("nbs", "c", "u/c", tmp_path / "nbs" / "c.parquet"),
    ]
    bodies: dict[str, bytes | None] = {"u/a": MOS_CSV.encode(), "u/b": None, "u/c": b"oops"}
    asked: list[str] = []

    def get(url: str) -> bytes | None:
        asked.append(url)
        return bodies[url]

    index = tmp_path / "done.jsonl"
    lines: list[str] = []
    assert pull.run_tasks(tasks, get, index, lines.append) == 2
    assert pl.read_parquet(tasks[0].path).height == 3
    assert pl.read_parquet(tasks[1].path).height == 0  # a hole, kept as one
    assert not tasks[2].path.exists()
    assert any("c failed" in line for line in lines)
    # Again: only the failed one is asked.
    asked.clear()
    bodies["u/c"] = MOS_CSV.encode()
    assert pull.run_tasks(tasks, get, index, lines.append) == 1
    assert asked == ["u/c"]
    notes = [json.loads(line) for line in index.read_text().splitlines()]
    assert [n["key"] for n in notes] == ["a", "b", "c", "c"]
    assert "failed" in notes[2]
    assert not list(tmp_path.rglob("*.part"))


def test_the_status_counts_done_holes_failures_and_hours_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(airports, "load", lambda: AIRPORTS)
    records_ = [
        {"source": "nbs", "key": "KAAA_201811", "rows": 10, "seconds": 4, "at": "2026-11-23T03:00"},
        {"source": "nbs", "key": "KBBB_201811", "rows": 0, "seconds": 4, "at": "2026-11-23T03:01"},
        {"source": "mav", "key": "KAAA_20000601", "failed": "HTTP 500"},
        {"source": "bts", "key": "2000_1", "rows": 5, "seconds": 8, "at": "2026-11-23T03:02"},
    ]
    (tmp_path / "iem-done.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records_[:3]) + "\nnot json\n"
    )
    (tmp_path / "bts-done.jsonl").write_text(json.dumps(records_[3]) + "\n")
    lines = pull.status_lines(tmp_path, date(2026, 11, 23), datetime(2026, 11, 23, 4, tzinfo=UTC))
    text = "\n".join(lines)
    assert f"nbs: 2 of {2 * len(AIRPORTS)} done, 10 rows kept, 1 holes, 0 failed" in text
    assert "mav: 0 of" in text
    assert "1 failed" in text
    assert "bts: 1 of 180 done" in text
    assert "last request kept: 2026-11-23T03:02" in text
    assert "est. hours left: IEM" in text


# --- BTS old years -------------------------------------------------------------------------------

EXPO = (
    "Year,Month,DayofMonth,DayOfWeek,DepTime,CRSDepTime,ArrTime,CRSArrTime,UniqueCarrier,"
    "FlightNum,TailNum,ActualElapsedTime,CRSElapsedTime,AirTime,ArrDelay,DepDelay,Origin,Dest,"
    "Distance,TaxiIn,TaxiOut,Cancelled,CancellationCode,Diverted\n"
    "1997,10,1,3,705,700,900,855,DL,1,NA,NA,NA,NA,5,5,AAA,BBB,500,NA,NA,0,NA,0\n"
    "1997,10,1,3,NA,800,NA,1000,DL,2,NA,NA,NA,NA,NA,NA,AAA,BBB,500,NA,NA,1,NA,0\n"
    "1997,11,2,7,1000,900,1300,1100,UA,3,NA,NA,NA,NA,120,60,BBB,AAA,500,NA,NA,0,NA,0\n"
)


def test_a_data_expo_month_reads_into_the_same_tables(tmp_path: Path) -> None:
    csv = tmp_path / "1997.csv"
    pull.unbzip(bz2.compress(EXPO.encode()), csv)
    tables = pull.reduce_expo_month(csv, Month(1997, 10))
    dep = tables["dep"]
    assert dep.get_column("n").sum() == 2
    assert dep.get_column("canc").sum() == 1
    assert tables["legs"].height == 2
    november = pull.reduce_expo_month(csv, Month(1997, 11))
    assert november["dep"].get_column("late").sum() == 1
    pull.write_tables(tmp_path / "bts", Month(1997, 10), tables)
    assert pull.has_tables(tmp_path / "bts", Month(1997, 10))
    assert not bts.has_month(tmp_path / "bts", Month(1997, 10))  # no sched for old years


# --- the non-weather spans (FL-1b.0) -------------------------------------------------------------


def test_a_carrier_day_span_drops_only_that_carriers_rows_on_those_days() -> None:
    code, first, last, _ = spans.CARRIER_NOT_WEATHER[0]
    rows = pl.DataFrame(
        {
            "carrier": [code, code, code, "DL", "DL"],
            "day": [first, last, date(last.year + 1, 1, 1), first, last],
        }
    )
    kept = rows.filter(spans.carrier_weather())
    assert kept.to_dicts() == [
        {"carrier": code, "day": date(last.year + 1, 1, 1)},
        {"carrier": "DL", "day": first},
        {"carrier": "DL", "day": last},
    ]
    covid = spans.NOT_WEATHER[0]
    assert covid[:2] == (date(2020, 3, 10), date(2020, 6, 7))
    both = pl.DataFrame({"carrier": ["DL", "DL"], "day": [date(2020, 4, 1), first]})
    assert both.filter(spans.weather_rows()).height == 1


def _dep(tmp_path: Path, rows: list[tuple[str, date, str, int, int]]) -> Path:
    root = tmp_path / "bts"
    frame = pl.DataFrame(
        rows, schema=["apt", "day", "carrier", "n", "canc"], orient="row"
    ).with_columns(pl.lit(1, dtype=pl.Int8).alias("block"), pl.lit(0).alias("late"))
    path = bts.table_path(root, "dep", Month(2022, 12))
    path.parent.mkdir(parents=True)
    frame.write_parquet(path)
    return root


def test_every_count_leaves_out_the_new_spans(tmp_path: Path) -> None:
    # LR-F2 for the new spans: the fit's outcomes, the own records' carrier lines and the usual
    # flights all leave out Southwest on its meltdown days and every flight in the COVID span.
    day = date(2022, 12, 26)
    root = _dep(tmp_path, [("AAA", day, "WN", 100, 80), ("AAA", day, "DL", 100, 2)])
    summed = train.outcomes(root, "dep").collect()
    assert summed.select("n", "canc").row(0) == (100, 2)
    kinds = pl.DataFrame(
        {"apt": ["AAA"], "day": [day], "block": [1], "kind": [2]},
        schema_overrides={"block": pl.Int8},
    )
    dep = pl.read_parquet(bts.table_path(root, "dep", Month(2022, 12)))
    lines = records.carrier_lines(dep.lazy(), kinds.lazy())
    assert ("AAA", "WN") not in lines
    raw = pl.DataFrame(
        {
            "FlightDate": ["2022-12-26", "2022-12-26", "2020-04-02", "2023-01-05"],
            "Reporting_Airline": ["WN", "DL", "DL", "WN"],
            "Flight_Number_Reporting_Airline": ["1", "2", "3", "4"],
            "Origin": ["AAA"] * 4,
            "OriginCityName": ["A"] * 4,
            "OriginState": ["AA"] * 4,
            "Dest": ["BBB"] * 4,
            "DestCityName": ["B"] * 4,
            "DestState": ["BB"] * 4,
            "CRSDepTime": ["0900"] * 4,
            "DepDelay": ["0"] * 4,
            "CRSArrTime": ["1100"] * 4,
            "ArrDelay": ["0"] * 4,
            "Cancelled": ["1", "0", "1", "0"],
            "Diverted": ["0"] * 4,
        }
    )
    sched = bts.reduce_rows(bts.read_rows(raw.lazy()))["sched"]
    assert sorted(zip(sched["carrier"], sched["number"], strict=True)) == [("DL", 2), ("WN", 4)]


# --- the gates on the validation year (LR-H1) ----------------------------------------------------


def test_the_validation_year_is_the_twelve_months_before_the_test_year() -> None:
    cut = train.split(Month(2026, 9))
    window = train.validation_of(cut)
    assert (window.test_first, window.test_last) == (date(2024, 10, 1), date(2025, 9, 30))


# --- IEM's NBS in the bulletins' rows (FL-1b.1) --------------------------------------------------

IEM_NBS = (
    "runtime,ftime,model,tmp,wsp,gst,p06,pzr,psn,t03,s06,i06,vis,cig,station\n"
    "2019-01-27 00:00:00,2019-01-27 06:00:00,NBS,20,8,15,58.0,2,96,0,5.0,0.0,11,888,KAAA\n"
    "2019-01-27 00:00:00,2019-01-27 09:00:00,NBS,19,9,17,,3,97,0,,,1,9,KAAA\n"
    "2019-01-27 00:00:00,2019-01-27 09:00:00,NBS,19,9,17,,3,97,0,,,1,9,KAAA\n"
    "2019-01-27 00:00:00,2019-01-30 03:00:00,NBS,10,1,2,,0,0,0,,,999,999,KAAA\n"
    "2019-01-27 07:00:00,2019-01-27 12:00:00,NBS,18,9,17,,3,97,0,,,2,5,KAAA\n"
    "2020-02-21 00:00:00,2020-02-21 12:00:00,NBS,18,9,17,,3,97,0,,,40,5,KAAA\n"
)


def test_iem_nbs_reads_into_the_bulletins_rows_and_units() -> None:
    from snowlight.flights import nbs_iem  # noqa: PLC0415
    from snowlight.flights.live import rows_of  # noqa: PLC0415

    rows = nbs_iem.to_rows(pull.reduce_mos(IEM_NBS.encode()))
    assert rows.schema == rows_of([]).schema
    assert rows.height == 3  # the duplicate once, the 07Z run and the hour past 72 left out
    first, second, newer = rows.to_dicts()
    assert newer["VIS"] == 40  # from NBM 3.2 on, IEM keeps the bulletin's tenths
    assert (first["TMP"], first["WSP"], first["GST"], first["P06"]) == (20, 8, 15, 58)
    assert (first["PSN"], first["S06"], first["I06"]) == (96, 5, 0)
    assert first["VIS"] == 100  # 11 miles, capped at the bulletin's 10.0
    assert first["CIG"] == -88  # no ceiling
    assert (second["VIS"], second["CIG"], second["P06"]) == (10, 9, None)
    assert nbs_iem.to_rows(pl.DataFrame()).height == 0


def test_iem_nbs_converts_each_kept_table_once(tmp_path: Path) -> None:
    from snowlight.flights import nbs_iem  # noqa: PLC0415

    source = tmp_path / "nbs"
    source.mkdir()
    pull.reduce_mos(IEM_NBS.encode()).write_parquet(source / "KAAA_201811.parquet")
    pl.DataFrame(schema={"station": pl.String()}).write_parquet(source / "KBBB_201811.parquet")
    assert nbs_iem.convert(source, tmp_path / "rows") == 2
    assert nbs_iem.convert(source, tmp_path / "rows") == 0
    assert pl.read_parquet(tmp_path / "rows" / "KAAA_201811.parquet").height == 3
    assert pl.read_parquet(tmp_path / "rows" / "KBBB_201811.parquet").height == 0


def test_the_history_fetches_iem_nbs_per_station_winter_and_says_what_is_missing(
    tmp_path: Path,
) -> None:
    from snowlight.flights import history  # noqa: PLC0415

    root = tmp_path / "nbs-iem"
    stations = ["KAAA", "KBBB"]
    assert len(history.iem_nbs_missing(root, stations)) == 4
    asked: list[str] = []

    def get(url: str) -> bytes | None:
        asked.append(url)
        if "KBBB" in url and "2019-07-01" in url:
            raise pull.PullError("busy")
        return None if "KBBB" in url else IEM_NBS.encode()

    lines: list[str] = []
    assert history.fetch_iem_nbs(get, root, stations, lines.append) == 3
    assert history.iem_nbs_missing(root, stations) == ["KBBB_201907.parquet"]
    assert any("failed" in line for line in lines)
    asked.clear()
    assert history.fetch_iem_nbs(get, root, stations, lines.append, out_of_time=lambda: True) == 0
    assert asked == []
    assert "nbs-iem/KAAA_201811.parquet" in history.kept_files(tmp_path)


def test_the_fit_reads_iem_nbs_up_to_its_last_00z_run(tmp_path: Path) -> None:
    from snowlight.flights import build, nbs_iem  # noqa: PLC0415

    (tmp_path / "nbs").mkdir()
    (tmp_path / "nbs-iem").mkdir()
    rows = nbs_iem.to_rows(pull.reduce_mos(IEM_NBS.encode()))
    rows.write_parquet(tmp_path / "nbs-iem" / "KAAA_201811.parquet")
    late = rows.with_columns(pl.col("run").dt.offset_by("2y"), pl.col("valid").dt.offset_by("2y"))
    late.write_parquet(tmp_path / "nbs-iem" / "KAAA_202102.parquet")
    rows.with_columns(
        pl.col("run").dt.offset_by("3y"), pl.col("valid").dt.offset_by("3y")
    ).write_parquet(tmp_path / "nbs" / "2022-01-27.parquet")
    years = build.nbs_rows(tmp_path).select(pl.col("run").dt.year()).collect().to_series()
    assert sorted(years.to_list()) == [2019, 2019, 2020, 2022, 2022, 2023]
    only = tmp_path / "only"
    (only / "nbs").mkdir(parents=True)
    rows.write_parquet(only / "nbs" / "2019-01-27.parquet")
    assert build.nbs_rows(only).collect().height == 3


# --- the IEM queue's manners (critic r1: RB-B1, RB-B2, RB-S1 to RB-S4) ----------------------------


def test_the_pause_counts_from_the_end_of_the_last_reply(tmp_path: Path) -> None:
    clock = Clock()
    pacer = pull.Pacer(tmp_path / "last", lambda _m: 2.0, sleep=clock.sleep, clock=clock.time)

    def slow(_url: str) -> tuple[int, bytes]:
        clock.now += 5.0  # the reply takes longer than the pause
        return 200, MOS_CSV.encode()

    assert pull.get_politely(slow, "u", pacer, print, sleep=clock.sleep) == MOS_CSV.encode()
    pacer.wait()
    assert clock.slept == [pytest.approx(2.0)]
    assert pacer.state()["asked"] == clock.now
    # A failed connection counts from its end too.
    clock.slept.clear()

    def cut(_url: str) -> tuple[int, bytes]:
        clock.now += 7.0
        raise httpx.ReadTimeout("slow")

    with pytest.raises(pull.PullError):
        pull.get_politely(cut, "u", pacer, lambda _l: None, tries=1, sleep=lambda _s: None)
    pacer.wait()
    assert clock.slept[-1] == pytest.approx(pacer.pause())  # the full pause after the cut


def test_busy_replies_on_two_tasks_back_to_back_double_the_backoff(tmp_path: Path) -> None:
    clock = Clock()
    stamp = tmp_path / "last"
    pacer = pull.Pacer(stamp, lambda _m: 2.0, sleep=clock.sleep, clock=clock.time)
    replies = [(429, b""), (200, MOS_CSV.encode())] * 2
    for task in ("u/a", "u/b"):
        pull.get_politely(lambda _u: replies.pop(0), task, pacer, print, sleep=clock.sleep)
    assert [s for s in clock.slept if s >= pull.BACKOFF_FIRST] == [60.0, 120.0]
    # Another process (a restart) reads the same backoff.
    other = pull.Pacer(stamp, lambda _m: 2.0, sleep=clock.sleep, clock=clock.time)
    assert other.busy() == 240.0
    assert [other.busy() for _ in range(3)] == [480.0, 900.0, 900.0]
    # Only a run of calm replies eases it: halved, then gone (the next busy waits 60 s).
    for _ in range(pull.BACKOFF_EASE_AFTER - 1):
        other.calm()
    assert other.state()["backoff"] == 900.0
    other.calm()
    assert other.state()["backoff"] == 450.0
    for _ in range(4 * pull.BACKOFF_EASE_AFTER):
        other.calm()
    assert other.state()["backoff"] == 0.0
    assert other.busy() == pull.BACKOFF_FIRST
    assert not list(tmp_path.glob("*.part"))


def test_a_body_that_is_not_the_table_backs_off_and_failures_in_a_row_stop_the_queue(
    tmp_path: Path,
) -> None:
    tasks = [pull.Task("mav", k, f"u/{k}", tmp_path / f"{k}.parquet") for k in "abcdefg"]
    bodies = {"u/a": MOS_CSV.encode(), "u/b": b"<html>maintenance</html>"}
    rejected: list[str] = []
    afters: list[int] = []

    def get(url: str) -> bytes | None:
        return bodies.get(url, b"ERROR: the database is down")

    with pytest.raises(pull.PullError, match="5 tasks failed in a row"):
        pull.run_tasks(
            tasks,
            get,
            tmp_path / "done.jsonl",
            lambda _l: None,
            rejected=rejected.append,
            after=lambda: afters.append(1),
        )
    assert tasks[0].path.exists()
    assert not any(t.path.exists() for t in tasks[1:])
    assert len(rejected) == 4  # each bad body backs off; the fifth stops the queue
    assert len(afters) == 6  # the status is written after failures too
    assert not tasks[6].path.exists()
    # A kept table between failures starts the count again.
    bodies.update({"u/d": MOS_CSV.encode()})
    with pytest.raises(pull.PullError):
        pull.run_tasks(tasks, get, tmp_path / "done.jsonl", lambda _l: None, stop_after=3)
    assert tasks[3].path.exists()


def test_a_hole_is_asked_again_a_day_later_and_noted_confirmed(tmp_path: Path) -> None:
    tasks = [pull.Task("mav", k, f"u/{k}", tmp_path / f"{k}.parquet") for k in "abc"]
    index = tmp_path / "done.jsonl"
    bodies: dict[str, bytes | None] = {"u/a": None, "u/b": b"station,runtime,ftime\n"}
    bodies["u/c"] = MOS_CSV.encode()
    assert pull.run_tasks(tasks[:2], bodies.get, index, lambda _l: None) == 2
    assert [t for t, _ in pull.holes_to_confirm(tasks, index)] == tasks[:2]
    kept_at = pull.holes_to_confirm(tasks, index)[0][1]
    now = [kept_at + timedelta(hours=3)]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += timedelta(seconds=seconds)

    # IEM now has rows for b: they are kept; a is still empty and noted confirmed.
    bodies["u/b"] = MOS_CSV.encode()
    asked = pull.confirm_holes(
        tasks, bodies.get, index, lambda _l: None, now=lambda: now[0], sleep=sleep
    )
    assert asked == 2
    assert slept
    assert sum(slept) >= timedelta(hours=21).total_seconds()
    assert pl.read_parquet(tasks[1].path).height == 3
    assert pull.holes_to_confirm(tasks, index) == []
    notes = [json.loads(line) for line in index.read_text().splitlines()]
    assert [(n["key"], n["rows"], n.get("confirmed")) for n in notes[2:]] == [
        ("a", 0, True),
        ("b", 3, True),
    ]
    # A hole whose second ask fails stays a hole to confirm on the next run.
    tasks.append(pull.Task("mav", "d", "u/d", tmp_path / "d.parquet"))
    pull.run_tasks(tasks[3:], lambda _u: None, index, lambda _l: None)
    now[0] += timedelta(days=2)

    def down(_url: str) -> bytes | None:
        raise pull.PullError("down")

    assert pull.confirm_holes(tasks, down, index, print, now=lambda: now[0], sleep=sleep) == 1
    assert [t.key for t, _ in pull.holes_to_confirm(tasks, index)] == ["d"]


def test_the_status_says_whether_each_queue_runs_and_its_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(airports, "load", lambda: AIRPORTS)
    (tmp_path / "iem.run").write_text(json.dumps({"pid": 4242, "since": "2026-11-23T06:40:00"}))
    pacer = pull.Pacer(tmp_path / "iem.last", pull.gap_at)
    pacer.wait()
    pacer.busy()
    now = datetime(2026, 11, 23, 7, tzinfo=UTC)
    with pull.only_one(tmp_path / "iem.lock"):
        text = "\n".join(pull.status_lines(tmp_path, now.date(), now))
    assert "iem queue: running (pid 4242 since 2026-11-23T06:40:00), last request asked 20" in text
    assert "backoff 60 s" in text
    assert "bts queue: not running" in text
    assert "restart it" in text  # nothing of BTS kept yet: it did not finish
    assert "every task done" in pull.queue_line(tmp_path, "bts", finished=True)
    assert "iem queue: not running" in pull.queue_line(tmp_path, "iem")


def test_hours_left_follow_the_pace_of_the_last_two_hours() -> None:
    start = datetime(2026, 11, 23, 3, tzinfo=UTC)
    steady = [
        {"at": (start + timedelta(seconds=30 * i)).isoformat(), "seconds": 1.0} for i in range(300)
    ]
    # Every 30 s over the last two hours (the pauses and backoffs in), not the request's 1 s.
    assert pull.seconds_each(steady, "iem") == pytest.approx(30.0)
    few = steady[:5]
    assert pull.seconds_each(few, "iem") == pytest.approx(1.0 + pull.GAP_SECONDS)
    assert pull.seconds_each([], "bts") == 0.0


def test_no_iem_request_goes_while_the_live_pass_may_read_iem(tmp_path: Path) -> None:
    clock = Clock()
    made = clock.now - 10 * 60
    calls: list[int] = []

    def fetch() -> bytes | None:
        calls.append(1)
        stamp = datetime.fromtimestamp(made, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return json.dumps({"generated_at": stamp}).encode()

    hold = pull.LiveHold(fetch, clock=clock.time, log=lambda _l: None)
    assert hold() == 0.0  # 10 minutes old: no pass due yet
    clock.now += 5 * 60  # 15 minutes old: a pass may be under way
    assert 0 < hold() <= pull.LIVE_CHECK_EVERY
    assert len(calls) == 2
    assert 0 < hold() <= pull.LIVE_CHECK_EVERY
    assert len(calls) == 2  # read at most once a minute
    made = clock.now - 60  # the pass wrote a new file
    clock.now += 60
    assert hold() == 0.0
    made = clock.now - 40 * 60  # the live job stalled: the pull goes on
    clock.now += 60
    assert hold() == 0.0

    def broken() -> bytes | None:
        raise httpx.ConnectError("no")

    assert pull.LiveHold(broken, clock=clock.time)() == 0.0
    assert pull.LiveHold(lambda: b"<html>", clock=clock.time)() == 0.0
    # The pacer sleeps the hold out before the pause.
    holds = [30.0, 0.0]
    pacer = pull.Pacer(
        tmp_path / "last",
        lambda _m: 2.0,
        sleep=clock.sleep,
        clock=clock.time,
        hold=lambda: holds.pop(0),
    )
    clock.slept.clear()
    pacer.wait()
    assert clock.slept == [30.0]


def test_the_track_record_leaves_out_the_non_weather_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # S6 (LR-F2): the monthly track record scores weather days only, as every other count does.
    meltdown, other = date(2022, 12, 26), date(2022, 12, 10)
    rows = [("AAA", meltdown, "WN", 100, 80), ("AAA", meltdown, "DL", 100, 2)]
    rows += [("AAA", other, "WN", 50, 1), ("AAA", other, "DL", 50, 1)]
    root = _dep(tmp_path, rows)
    dep = monthly.month_departures(root, Month(2022, 12)).sort("day")
    assert dep.select("day", "n", "canc").rows() == [(other, 100, 2), (meltdown, 100, 2)]
    monkeypatch.setattr(spans, "NOT_WEATHER", ((other, other, "a test span"),))
    dep = monthly.month_departures(root, Month(2022, 12))
    assert dep.get_column("day").to_list() == [meltdown]


# --- a stalled queue (critic r2: the local proxy moved) ------------------------------------------

PROXY = "http://127.0.0.1:37707"


def test_only_a_proxy_on_this_machine_is_local() -> None:
    assert pull.local_proxy({"HTTPS_PROXY": PROXY}) == PROXY
    assert pull.local_proxy({"https_proxy": "http://localhost:3128"}) == "http://localhost:3128"
    assert pull.local_proxy({"HTTPS_PROXY": "http://proxy.example.com:80"}) is None
    assert pull.local_proxy({}) is None
    refused = httpx.ConnectError("[Errno 111] Connection refused")
    assert pull.local_failure(refused, PROXY)
    assert not pull.local_failure(refused, None)  # no proxy: the host itself refused
    assert not pull.local_failure(httpx.RemoteProtocolError("dropped"), PROXY)
    assert not pull.local_failure(httpx.ReadTimeout("slow"), PROXY)


def test_a_local_proxy_refusal_leaves_the_iem_pace_alone_and_three_stop_the_queue(
    tmp_path: Path,
) -> None:
    clock = Clock()
    pacer = pull.Pacer(tmp_path / "last", lambda _m: 2.0, sleep=clock.sleep, clock=clock.time)
    before = {k: v for k, v in pacer.state().items() if k not in {"last", "asked"}}
    reasons: list[str] = []

    def refused(_u: str) -> tuple[int, bytes]:
        raise httpx.ConnectError("[Errno 111] Connection refused")

    with pytest.raises(pull.LocalProxyError, match=r"127\.0\.0\.1:37707 refused 3 requests"):
        pull.get_politely(
            refused,
            "u",
            pacer,
            lambda _l: None,
            sleep=clock.sleep,
            proxy=PROXY,
            failed=reasons.append,
        )
    after = {k: v for k, v in pacer.state().items() if k not in {"last", "asked"}}
    assert after == before  # no stretched pause, no backoff: IEM never saw these
    assert pacer.pause() == 2.0
    assert max(clock.slept) <= pull.LOCAL_WAIT
    assert len(reasons) == pull.LOCAL_STOP_AFTER
    assert all("local proxy" in r for r in reasons)
    # The queue stops at once: no task is noted failed and nothing more is asked.
    tasks = [pull.Task("mav", k, f"u/{k}", tmp_path / f"{k}.parquet") for k in "abc"]
    asked: list[str] = []

    def get(url: str) -> bytes | None:
        asked.append(url)
        return pull.get_politely(
            refused, url, pacer, lambda _l: None, sleep=clock.sleep, proxy=PROXY
        )

    with pytest.raises(pull.LocalProxyError):
        pull.run_tasks(tasks, get, tmp_path / "done.jsonl", lambda _l: None)
    assert asked == ["u/a"]
    assert not (tmp_path / "done.jsonl").exists()


def test_a_lone_local_refusal_spends_no_try_and_a_real_reply_counts_again(tmp_path: Path) -> None:
    clock = Clock()
    pacer = pull.Pacer(tmp_path / "last", lambda _m: 2.0, sleep=clock.sleep, clock=clock.time)
    replies: list[object] = [
        httpx.ConnectError("refused"),
        httpx.ConnectError("refused"),
        (503, b""),
        httpx.ConnectError("refused"),
        httpx.ConnectError("refused"),
        (200, MOS_CSV.encode()),
    ]

    def request(_u: str) -> tuple[int, bytes]:
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        assert isinstance(reply, tuple)
        return reply

    body = pull.get_politely(request, "u", pacer, print, tries=2, sleep=clock.sleep, proxy=PROXY)
    assert body == MOS_CSV.encode()
    # Only the 503 from IEM backed off and stretched the pace.
    assert [s for s in clock.slept if s >= pull.BACKOFF_FIRST] == [60.0]
    assert pacer.state()["backoff"] == 60.0


def test_a_restart_waits_out_the_backoff_it_finds(tmp_path: Path) -> None:
    clock = Clock()
    stamp = tmp_path / "last"
    pull.Pacer(stamp, lambda _m: 2.0, sleep=clock.sleep, clock=clock.time).busy()
    restarted = pull.Pacer(stamp, lambda _m: 2.0, sleep=clock.sleep, clock=clock.time)
    restarted.wait()
    assert sum(clock.slept) == pytest.approx(pull.BACKOFF_FIRST)
    clock.slept.clear()
    restarted.wait()
    assert clock.slept == [pytest.approx(restarted.pause())]  # then the (stretched) pause


def test_every_wait_writes_the_status_at_least_once_a_minute() -> None:
    clock = Clock()
    ticks: list[float] = []
    nap = pull.napper(lambda: ticks.append(clock.now), sleep=clock.sleep)
    nap(900.0)
    assert clock.slept == [60.0] * 15
    assert len(ticks) == 15
    nap(2.5)
    assert clock.slept[-1] == 2.5
    assert len(ticks) == 16


def _running(tmp_path: Path, since: str) -> None:
    (tmp_path / "iem.run").write_text(json.dumps({"pid": 4242, "since": since}))


def test_a_queue_that_keeps_nothing_says_so_and_its_hours_left_count_to_now(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(airports, "load", lambda: AIRPORTS)
    start = datetime(2026, 11, 23, 6, 0, tzinfo=UTC)
    kept = [
        {
            "source": "mav",
            "key": f"K{i:03d}_20040101",
            "rows": 5,
            "seconds": 4.0,
            "at": (start + timedelta(seconds=30 * i)).isoformat(),
        }
        for i in range(60)
    ]
    (tmp_path / "iem-done.jsonl").write_text("\n".join(json.dumps(r) for r in kept) + "\n")
    _running(tmp_path, "2026-11-23T05:50:00+00:00")
    last = start + timedelta(seconds=30 * 59)
    pull.note_error(
        tmp_path, "iem", "ConnectError: [Errno 111] Connection refused", last + timedelta(minutes=1)
    )
    with pull.only_one(tmp_path / "iem.lock"):
        fresh = "\n".join(pull.status_lines(tmp_path, start.date(), last + timedelta(minutes=5)))
        stalled_at = last + timedelta(minutes=60)
        stalled = "\n".join(pull.status_lines(tmp_path, start.date(), stalled_at))
        assert pull.stuck(tmp_path, "iem", last + timedelta(minutes=20)) is None
        assert pull.stuck(tmp_path, "iem", stalled_at) == 4242
    assert "no table kept" not in fresh
    assert (
        "iem queue: no table kept for 60 min (last error 2026-11-23T06:30:30Z: ConnectError"
        in stalled
    )
    # The pace runs to now: an hour with nothing kept slows it (it is no longer every 30 s).
    recent = kept
    assert pull.seconds_each(recent, "iem", last) == pytest.approx(30.0)
    assert pull.seconds_each(recent, "iem", stalled_at) == pytest.approx((89.5 * 60) / 59)
    # Too few kept for a pace: never faster than one table per the time since the first of them.
    assert pull.seconds_each(recent[-2:], "iem", last + timedelta(minutes=30)) == pytest.approx(
        (30.5 * 60) / 2
    )
    # Nothing kept in the last two hours: no pace to tell, so no hours-left figure.
    late = last + timedelta(hours=3)
    assert pull.seconds_each(recent, "iem", late) is None
    with pull.only_one(tmp_path / "iem.lock"):
        text = "\n".join(pull.status_lines(tmp_path, start.date(), late))
    assert "est. hours left: IEM unknown (no table kept in the last 2 hours)" in text
    # Not running: no stall line, and no queue to replace.
    assert pull.stall_line(tmp_path, "iem", late) is None
    assert pull.stuck(tmp_path, "iem", late) is None


def test_a_stall_after_a_clean_table_names_no_old_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(airports, "load", lambda: AIRPORTS)
    _running(tmp_path, "2026-11-23T06:00:00")
    pull.note_error(tmp_path, "iem", "HTTP 503", datetime(2026, 11, 23, 6, 1, tzinfo=UTC))
    record = {"source": "mav", "key": "KAAA_20040101", "rows": 5, "at": "2026-11-23T06:05:00+00:00"}
    (tmp_path / "iem-done.jsonl").write_text(json.dumps(record) + "\n")
    with pull.only_one(tmp_path / "iem.lock"):
        line = pull.stall_line(tmp_path, "iem", datetime(2026, 11, 23, 6, 25, tzinfo=UTC))
        # A queue that kept nothing since its start counts from its start.
        (tmp_path / "iem-done.jsonl").unlink()
        since = pull.stall_line(tmp_path, "iem", datetime(2026, 11, 23, 6, 10, tzinfo=UTC))
    assert (
        line == "iem queue: no table kept for 20 min (no failed request since the last table kept)"
    )
    assert since is None


def test_a_stopped_queue_says_why_and_a_backoff_says_when_it_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(airports, "load", lambda: AIRPORTS)
    _running(tmp_path, "2026-11-23T07:10:02+00:00")
    why = pull.stopped_by_proxy(pull.LocalProxyError(f"the local proxy {PROXY} refused 3"))
    pull.note_stop(tmp_path, "iem", why, datetime(2026, 11, 23, 7, 30, tzinfo=UTC))
    line = pull.queue_line(tmp_path, "iem")
    assert line.startswith(
        "iem queue: not running (last started 2026-11-23T07:10:02+00:00, pid 4242)"
    )
    assert "stopped 2026-11-23T07:30:00+00:00: local proxy refused (the local proxy " in line
    assert line.endswith("restart it from a shell with the current proxy; restart it")
    pacer = pull.Pacer(tmp_path / "iem.last", pull.gap_at)
    pacer.busy()
    until = pacer.state()["until"]
    with pull.only_one(tmp_path / "iem.lock"):
        waiting = pull.queue_line(tmp_path, "iem", now=until - 30)
        over = pull.queue_line(tmp_path, "iem", now=until + 1)
    assert waiting.endswith(f"backoff 60 s (waiting it out until {pull._when(until)})")
    assert over.endswith("backoff 60 s")


def test_the_monthly_warning_tells_non_weather_days_from_days_not_kept() -> None:
    assert spans.not_weather_days(date(2020, 3, 1), date(2020, 3, 31)) == 22
    assert spans.not_weather_days(date(2020, 6, 1), date(2020, 6, 30)) == 7
    assert spans.not_weather_days(date(2021, 1, 1), date(2021, 1, 31)) == 0
    score = FlightsMonthScore(
        month="2020-03",
        target=FlightsTarget.DEP_CANC,
        units=10,
        brier=0.01,
        brier_usual=0.02,
        rough_days=0,
        caught=0,
        days_in_month=31,
        days_scored=7,
    )
    line = monthly.unscored_warning("2020-03", score, 22)
    assert line is not None
    assert (
        "scored on 7 of its 31 days (of the rest, 22 in a non-weather span, left out and "
        "2 not kept)" in line
    )
    spans_only = score.model_copy(update={"days_scored": 9})
    assert "(of the rest, 22 in a non-weather span, left out)" in str(
        monthly.unscored_warning("2020-03", spans_only, 22)
    )
    kept_only = score.model_copy(update={"days_scored": 30})
    assert "(of the rest, 1 not kept)" in str(monthly.unscored_warning("2021-01", kept_only, 0))
    assert (
        monthly.unscored_warning("2021-01", score.model_copy(update={"days_scored": 31}), 0) is None
    )


def test_failures_and_confirmed_holes_are_no_table_kept_and_a_bad_run_file_names_no_pid(
    tmp_path: Path,
) -> None:
    index = [
        {"source": "mav", "key": "a", "rows": 5, "at": "2026-11-23T06:00:00+00:00"},
        {"source": "mav", "key": "b", "failed": "HTTP 500"},
        {"source": "mav", "key": "c", "rows": 0, "confirmed": True, "at": "2026-11-23T07:00:00"},
        {"source": "mav", "key": "d", "rows": 5, "at": "not a time"},
    ]
    (tmp_path / "iem-done.jsonl").write_text("\n".join(json.dumps(r) for r in index) + "\n")
    assert pull.last_kept(tmp_path, "iem") == datetime(2026, 11, 23, 6, tzinfo=UTC)
    assert pull.last_kept(tmp_path, "bts") is None
    (tmp_path / "iem.run").write_text(json.dumps({"since": "2026-11-23T05:00:00+00:00"}))
    with pull.only_one(tmp_path / "iem.lock"):
        assert pull.stuck(tmp_path, "iem", datetime(2026, 11, 23, 9, tzinfo=UTC)) is None
        (tmp_path / "iem.run").write_text("[1, 2]")
        assert pull.quiet_for(tmp_path, "iem", datetime(2026, 11, 23, 9, tzinfo=UTC)) == timedelta(
            hours=3
        )
