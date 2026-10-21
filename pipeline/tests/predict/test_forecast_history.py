"""The forecast history (S7-F F1): nights and samples, the deciding schools, one night's codes
from synthetic runs, the delay, gaps, the heads-up files and the workflow.

Every forecast here is synthetic (tests/predict/grib.py) and every school is the test world's.
"""

from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from predict import grib, world
from snowlight.predict import forecast_history as fh
from snowlight.predict import inputs, ndfd
from snowlight.predict.calendar import school_days
from snowlight.predict.ndfd import Element, Host, Listed
from snowlight.predict.situations import HEADS_UP_BY_CODE, HeadsUp
from snowlight.weights.archive import ArchiveCsvError

NIGHT = date(2025, 1, 6)
SHARE = world.CONFIG.weather.covered_share
REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "predict-forecast-history.yml"


def test_chunks_cover_every_school_day_once_in_80_jobs() -> None:
    assert len(fh.CHUNKS) * (fh.LAST_SEASON - fh.FIRST_SEASON + 1) == 80
    found = [day for chunk in range(len(fh.CHUNKS)) for day in fh.nights(2024, chunk)]
    assert found == list(school_days(date(2024, 8, 15), date(2025, 6, 15)))
    assert date(2025, 1, 1) not in fh.nights(2024, 4)
    assert fh.nights(2024, 4)[0] == date(2025, 1, 2)


def test_samples_are_the_local_hours_from_8_am_to_4_am_three_per_slot() -> None:
    assert fh.sample_time(NIGHT, "America/Chicago", 0) == datetime(2025, 1, 5, 14, tzinfo=UTC)
    assert fh.sample_time(NIGHT, "America/Chicago", 15) == datetime(2025, 1, 6, 5, tzinfo=UTC)
    assert fh.sample_time(NIGHT, "America/Chicago", 20) == datetime(2025, 1, 6, 10, tzinfo=UTC)
    # The Monday after daylight time starts: Sunday 08:00 is already daylight time.
    assert fh.sample_time(date(2025, 3, 10), "America/New_York", 0) == datetime(
        2025, 3, 9, 12, tzinfo=UTC
    )
    assert fh.sample_time(date(2025, 3, 10), "America/Phoenix", 20) == datetime(
        2025, 3, 10, 11, tzinfo=UTC
    )
    assert tuple(s for s in range(1, 8) for _ in range(3)) == fh.SLOT_OF_SAMPLE


def test_the_deciding_schools_are_the_serving_passs() -> None:
    schools = fh.deciding_schools(world.directory(), world.model())
    assert schools.districts == world.DISTRICTS
    by_district = {
        leaid: int((schools.district == i).sum()) for i, leaid in enumerate(schools.districts)
    }
    # District 2's charter school does not decide; the private school has no district.
    assert by_district == {"2000004": 1, "2900001": 2, "2900002": 1, "2900003": 1, "4900005": 1}
    assert schools.zone_of_district[4] == "America/Denver"
    again = fh.Schools.from_frame(schools.frame())
    assert again.districts == schools.districts
    assert np.array_equal(again.district, schools.district)
    assert np.allclose(again.lat, schools.lat)
    clash = schools.frame().with_columns(
        pl.when((pl.col("lat") - 39.11).abs() < 1e-6)
        .then(pl.lit("America/Denver"))
        .otherwise("time_zone")
        .alias("time_zone")
    )
    with pytest.raises(ValueError, match="two time zones"):
        fh.Schools.from_frame(clash)


def test_districts_the_model_cannot_place_are_left_out() -> None:
    model = world.model()
    districts = dict(model.districts)
    districts["2900003"] = districts["2900003"].model_copy(update={"time_zone": None})
    del districts["2000004"]
    schools = fh.deciding_schools(
        world.directory(), model.model_copy(update={"districts": districts})
    )
    assert schools.districts == ("2900001", "2900002", "4900005")


# --- one night from synthetic runs ---------------------------------------------------------------


def period_ends(reference: datetime, night: date = NIGHT) -> list[datetime]:
    """The ends of a run's periods: the one under way at ``reference``, then on to 18Z on D."""
    end = reference.replace(minute=0) + timedelta(hours=6 - reference.hour % 6)
    last = datetime.combine(night, datetime.min.time(), tzinfo=UTC) + timedelta(hours=18)
    found = []
    while end <= last:
        found.append(end)
        end += timedelta(hours=6)
    return found


def lead_of(reference: datetime, end: datetime, stamp: ndfd.PeriodStamp) -> float:
    """NDFD's forecast time of the period ending at ``end`` (:class:`ndfd.PeriodStamp`)."""
    if stamp is ndfd.PeriodStamp.END:
        return (end - reference).total_seconds() / 3600
    return max(0.0, (end - timedelta(hours=6) - reference).total_seconds() / 3600)


def amounts(  # noqa: PLR0913 - one file's shape
    reference: datetime,
    values: dict[int, float],
    *,
    bad_middle: bool = False,
    stamp: ndfd.PeriodStamp = ndfd.PeriodStamp.START,
    element: Element = Element.SNOW,
    night: date = NIGHT,
) -> list[bytes]:
    """A run's snow or ice file as NDFD writes it: whole 6-hour periods from the one under way
    at ``reference`` to 18Z on the night, stamped as ``stamp`` says; ``values`` maps a period's
    end hour on D (6, 12, 18) to its constant amount. ``bad_middle`` stamps the later periods
    3 hours off."""
    found = []
    for index, end in enumerate(period_ends(reference, night)):
        value = values.get(end.hour, 0.0) if end.date() == night else 0.0
        lead = lead_of(reference, end, stamp) + (3 if bad_middle and index else 0)
        found.append(
            grib.message(element.parameter, reference, lead_hours=lead, end=end, values=value)
        )
    return found


def ice(reference: datetime, hole_at: tuple[float, float] | None) -> list[bytes]:
    values = np.zeros(ndfd.NX * ndfd.NY)
    if hole_at is not None:
        where = ndfd.cells(np.array([hole_at[1]]), np.array([hole_at[0]]))
        values[where.row[0] * ndfd.NX + where.col[0]] = np.nan
    return [
        grib.message(
            Element.ICE.parameter,
            reference,
            lead_hours=lead_of(reference, end, ndfd.PeriodStamp.START),
            end=end,
            values=values,
        )
        for end in period_ends(reference)
    ]


def apt(reference: datetime, kelvin: float) -> list[bytes]:
    last = datetime(2025, 1, 6, 15, tzinfo=UTC)
    hours = int((last - reference).total_seconds() // 3600)
    return [
        grib.message(Element.APT.parameter, reference, lead_hours=h, values=kelvin)
        for h in range(1, hours + 1)
    ]


UTAH = world.SCHOOLS[6][:2]


def make_run(
    stamp: str, files: dict[Element, list[bytes]], store: dict[str, bytes]
) -> list[Listed]:
    found = []
    for element, messages in files.items():
        url = f"https://example.invalid/{element.heading}_{stamp}"
        store[url] = grib.framed(messages, f"{element.heading} KWBN 0000")
        found.append(Listed(element, grib.utc(stamp), url, Host.AWS, None))
    return found


def opener_of(store: dict[str, bytes]) -> fh.Opener:
    """Reads the files of ``store`` by their URL."""
    return lambda item: ndfd.bytes_reader(store[item.url])


@pytest.fixture(scope="module")
def night() -> fh.Night:
    store: dict[str, bytes] = {}
    first = grib.utc("2025-01-05T13:00")
    late = grib.utc("2025-01-06T04:00")
    bad = grib.utc("2025-01-05T18:00")
    listed = [
        *make_run(
            "2025-01-05T12:46",
            {
                Element.SNOW: amounts(first, {6: 0.0508, 12: 0.1016}),
                Element.ICE: ice(first, UTAH),
                Element.APT: apt(first, 250.0),
            },
            store,
        ),
        *make_run(
            "2025-01-05T17:46",
            {
                Element.SNOW: amounts(bad, {6: 0.0508}, bad_middle=True),
                Element.ICE: ice(bad, None),
                Element.APT: apt(bad, 250.0),
            },
            store,
        ),
        *make_run(
            "2025-01-06T03:46",
            {
                Element.SNOW: amounts(late, {6: 0.0254, 12: 0.0254}),
                Element.ICE: ice(late, None),
                Element.APT: apt(late, 250.0),
            },
            store,
        ),
    ]
    runs = ndfd.assemble_runs(listed).runs
    assert len(runs) == 3
    schools = fh.deciding_schools(world.directory(), world.model())
    groups = fh.zone_groups(schools)
    return fh.night_codes(
        NIGHT,
        schools,
        groups,
        runs,
        lambda item: ndfd.bytes_reader(store[item.url]),
        SHARE,
        workers=2,
    )


def code_at(night: fh.Night, district: str, sample: int, column: str = "code") -> int:
    rows = night.codes.filter((pl.col("district") == district) & (pl.col("sample") == sample))
    assert rows.height == 1
    return int(rows[column][0])


def test_a_night_codes_every_district_at_every_sample(night: fh.Night) -> None:
    assert night.codes.height == len(world.DISTRICTS) * fh.SAMPLES
    assert night.samples.height == 2 * fh.SAMPLES  # two zones
    kc = "2900001"
    # 08:00 and 09:00 CST: the 12:46Z run, 6 inches in the window (2 + 4).
    assert code_at(night, kc, 0) == ndfd.Bucket.SNOW_6
    assert code_at(night, kc, 1) == ndfd.Bucket.SNOW_6
    # 10:00 CST: that run is over 3 hours old and the next one's snow file does not read:
    # unknown (its ice and feels read, but any snow could be stronger).
    assert code_at(night, kc, 2) == ndfd.Bucket.UNKNOWN
    # 21:00 CST (03Z): no run at most 3 hours old (the 03:46Z run counts from 03:56Z).
    assert code_at(night, kc, 13) == ndfd.Bucket.UNKNOWN
    # 22:00 CST (04Z): the 03:46Z run: the period under way, 00-06Z whole (1 in), and 06-12Z
    # (1 in).
    assert code_at(night, kc, 14) == ndfd.Bucket.SNOW_2
    # Midnight CST (06Z): the 06Z period has ended; 1 inch left (feels about -10 F ranks lower).
    assert code_at(night, kc, 16) == ndfd.Bucket.SNOW_HALF
    # 01:00 CST (07Z): the run is over 3 hours old.
    assert code_at(night, kc, 17) == ndfd.Bucket.UNKNOWN


def test_a_cell_with_no_value_is_unknown_strictly_and_nothing_when_filled(night: fh.Night) -> None:
    utah = "4900005"
    assert code_at(night, utah, 0) == ndfd.Bucket.UNKNOWN
    assert code_at(night, utah, 0, "code_filled") == ndfd.Bucket.SNOW_6
    assert code_at(night, utah, 0, "missing") == 2
    assert code_at(night, "2900001", 0, "missing") == 0


def test_the_sample_table_says_which_run_and_why_not(night: fh.Night) -> None:
    chicago = night.samples.filter(pl.col("time_zone") == "America/Chicago").sort("sample")
    first = chicago.row(0, named=True)
    assert first["run_time"] == grib.utc("2025-01-05T12:46")
    assert first["age_minutes"] == 74.0
    assert first["period_stamp"] == "start"
    assert first["refused_runs"] == 0
    bad = chicago.filter(pl.col("error").is_not_null())
    assert bad.height == 3  # 18Z, 19Z, 20Z
    assert bad["error"][0].startswith("snow: period: periods stamped neither")
    assert set(bad["reason"].to_list()) == {"element_error"}
    assert set(bad["period_stamp"].to_list()) == {"start"}  # the ice file read
    gap = chicago.filter(pl.col("run_time").is_null())
    assert gap["unknown"].to_list() == [4] * gap.height
    assert set(gap["reason"].to_list()) == {"no_run"}
    assert chicago.filter(pl.col("reason").is_null())["error"].is_null().all()
    assert not chicago["archive_copy"].fill_null(False).any()
    summary = fh.summarize(night.samples, night.codes, night.refused)
    assert summary["samples"] == 42
    assert summary["period_stamps"] == {"start": 3}
    assert summary["run_reasons"] == {"element_error": 1}
    assert summary["refused_runs"] == []
    assert summary["samples_from_archive_copies"] == 0
    assert summary["reasons"] == {
        "no_run": int(night.samples["reason"].eq("no_run").sum()),
        "element_error": 6,
    }
    assert summary["error_share_by_month"] == {"2025-01": round(6 / 42, 4)}


def test_a_grid_change_stops_the_history() -> None:
    store: dict[str, bytes] = {}
    reference = grib.utc("2025-01-06T03:00")
    wrong = grib.message(
        Element.SNOW.parameter,
        reference,
        lead_hours=0,
        end=grib.utc("2025-01-06T06:00"),
        values=np.zeros(2144 * ndfd.NY),
        grid={"Nx": 2144},
    )
    listed = make_run(
        "2025-01-06T02:46",
        {Element.SNOW: [wrong], Element.ICE: [wrong], Element.APT: apt(reference, 250.0)},
        store,
    )
    schools = fh.deciding_schools(world.directory(), world.model())
    with pytest.raises(ndfd.GridError):
        fh.night_codes(
            NIGHT,
            schools,
            fh.zone_groups(schools),
            ndfd.assemble_runs(listed).runs,
            lambda item: ndfd.bytes_reader(store[item.url]),
            SHARE,
        )


def test_a_file_that_does_not_read_leaves_its_samples_unknown() -> None:
    reference = grib.utc("2025-01-06T03:00")
    listed = make_run("2025-01-06T02:46", {e: [b"not grib"] for e in ndfd.ELEMENTS}, {})
    (run,) = ndfd.assemble_runs(listed).runs
    schools = fh.deciding_schools(world.directory(), world.model())
    found = fh.run_values(
        run,
        NIGHT,
        [reference],
        ndfd.cells(schools.lat, schools.lon),
        lambda _: ndfd.bytes_reader(b"x" * 2000),
    )
    assert set(found.errors) == set(ndfd.ELEMENTS)
    assert found.error is not None
    assert found.error.startswith("snow: read:")
    assert fh._reason(found) == "run_error"


def test_a_run_reads_alike_whichever_way_its_periods_are_stamped() -> None:
    # Until 2018-10-30 13:15Z NDFD stamped every period at its end; the same amounts read the
    # same, and the sample table says which way the run was stamped.
    reference = grib.utc("2025-01-06T03:00")
    schools = fh.deciding_schools(world.directory(), world.model())
    where = ndfd.cells(schools.lat, schools.lon)
    found = {}
    for stamp in ndfd.PeriodStamp:
        store: dict[str, bytes] = {}
        files = {
            Element.SNOW: amounts(reference, {6: 0.0254, 12: 0.0508}, stamp=stamp),
            Element.ICE: amounts(reference, {12: 0.5}, stamp=stamp, element=Element.ICE),
            Element.APT: apt(reference, 250.0),
        }
        (run,) = ndfd.assemble_runs(make_run("2025-01-06T02:46", files, store)).runs
        found[stamp] = fh.run_values(
            run,
            NIGHT,
            [reference],
            where,
            opener_of(store),
        )
    start, end = found[ndfd.PeriodStamp.START], found[ndfd.PeriodStamp.END]
    assert end.errors == start.errors == {}
    assert end.period_stamp == "end"
    assert start.period_stamp == "start"
    assert end.snow.keys() == start.snow.keys() == set(ndfd.window_ends(NIGHT))
    for name in ("snow", "ice"):
        for key, value in getattr(start, name).items():
            assert np.array_equal(getattr(end, name)[key], value)
    assert np.allclose(start.snow[grib.utc("2025-01-06T12:00")], 2.0)


def test_a_file_holding_its_messages_twice_reads_once_and_only_if_they_agree() -> None:
    # Half the runs of 2019-08-19 and 2019-09-09: every message of the snow and ice files twice.
    reference = grib.utc("2025-01-06T03:00")
    schools = fh.deciding_schools(world.directory(), world.model())
    where = ndfd.cells(schools.lat, schools.lon)
    once = amounts(reference, {6: 0.0254, 12: 0.0508})
    other = amounts(reference, {6: 0.0254, 12: 0.1016})
    found = {}
    for name, snow in (("same", once + once), ("different", once + other)):
        store: dict[str, bytes] = {}
        files = {
            Element.SNOW: snow,
            Element.ICE: ice(reference, None),
            Element.APT: apt(reference, 250.0),
        }
        (run,) = ndfd.assemble_runs(make_run("2025-01-06T02:46", files, store)).runs
        found[name] = fh.run_values(run, NIGHT, [reference], where, opener_of(store))
    same, different = found["same"], found["different"]
    assert same.errors == {}
    assert same.repeated == len(once)
    assert np.allclose(same.snow[grib.utc("2025-01-06T12:00")], 2.0)
    assert set(different.errors) == {Element.SNOW}
    assert "two different messages of the period to 2025-01-06 12:00" in str(different.error)
    assert different.snow == {}


def test_a_run_whose_content_is_another_runs_gives_way_to_the_run_before() -> None:
    # NCEI's 201906030016/0017 files hold the run of 2019-07-03 00:30: a file whose reference
    # time does not fit its stamp is not that run, and the run before it is used.
    store: dict[str, bytes] = {}
    good = grib.utc("2025-01-05T13:00")
    later = grib.utc("2025-02-05T14:00")  # a month on
    listed = [
        *make_run(
            "2025-01-05T12:46",
            {
                Element.SNOW: amounts(good, {6: 0.0508, 12: 0.1016}),
                Element.ICE: ice(good, None),
                Element.APT: apt(good, 250.0),
            },
            store,
        ),
        *make_run(
            "2025-01-05T13:46",
            {
                Element.SNOW: amounts(later, {}, night=date(2025, 2, 6)),
                Element.ICE: ice(good, None),
                Element.APT: apt(good, 250.0),
            },
            store,
        ),
    ]
    schools = fh.deciding_schools(world.directory(), world.model())
    night = fh.night_codes(
        NIGHT,
        schools,
        fh.zone_groups(schools),
        ndfd.assemble_runs(listed).runs,
        lambda item: ndfd.bytes_reader(store[item.url]),
        SHARE,
    )
    (refused,) = night.refused
    assert refused.run.time == grib.utc("2025-01-05T13:46")
    assert refused.refused == "snow reference 2025-02-05 14:00Z, run 2025-01-05 13:46Z"
    # 09:00 CST (15Z): the refused run would be newest; the 12:46Z run is used (6 inches).
    assert code_at(night, "2900001", 1) == ndfd.Bucket.SNOW_6
    chicago = night.samples.filter(pl.col("time_zone") == "America/Chicago").sort("sample")
    assert chicago["run_time"][:2].to_list() == [grib.utc("2025-01-05T12:46")] * 2
    # 10:00 CST (16Z): the 12:46Z run is over 3 hours old, and no run stands in for the refused
    # one; 11:00 CST: the refused run would be over 3 hours old too.
    assert chicago["run_time"][2] is None
    assert chicago["refused_runs"][:4].to_list() == [1, 1, 1, 0]
    summary = fh.summarize(night.samples, night.codes, night.refused)
    assert summary["refused_runs"] == [{"run": "2025-01-05T13:46:00+00:00", "why": refused.refused}]
    assert summary["samples_passing_over_refused_runs"] == int(
        (night.samples["refused_runs"] > 0).sum()
    )


def test_an_element_that_does_not_read_leaves_the_others_to_decide() -> None:
    reference = grib.utc("2025-01-06T03:00")
    schools = fh.deciding_schools(world.directory(), world.model())
    store: dict[str, bytes] = {}
    files = {
        Element.SNOW: amounts(reference, {6: 0.0254}),
        Element.ICE: ice(reference, None),
        Element.APT: [b"not grib"],
    }
    runs = ndfd.assemble_runs(make_run("2025-01-06T02:46", files, store)).runs
    night = fh.night_codes(
        NIGHT,
        schools,
        fh.zone_groups(schools),
        runs,
        lambda item: ndfd.bytes_reader(store[item.url]),
        SHARE,
    )
    # 22:00 CST (04Z): 1 inch of snow outranks any apparent temperature: decided, not unknown.
    assert code_at(night, "2900001", 14) == ndfd.Bucket.SNOW_HALF
    row = night.samples.filter(
        (pl.col("time_zone") == "America/Chicago") & (pl.col("sample") == 14)
    ).row(0, named=True)
    assert row["reason"] == "element_error"
    assert row["error"].startswith("apt: read:")
    # Amounts that do not read still leave the apparent temperature read.
    files[Element.SNOW] = amounts(reference, {6: 0.0254}, bad_middle=True)
    files[Element.APT] = apt(reference, 250.0)
    (run,) = ndfd.assemble_runs(make_run("2025-01-06T02:46", files, store)).runs
    found = fh.run_values(
        run,
        NIGHT,
        [grib.utc("2025-01-06T13:00")],
        ndfd.cells(schools.lat, schools.lon),
        lambda item: ndfd.bytes_reader(store[item.url]),
    )
    assert set(found.errors) == {Element.SNOW}
    assert found.snow == {}
    assert found.ice.keys() == set(ndfd.window_ends(NIGHT))
    assert np.allclose(found.feels[grib.utc("2025-01-06T13:00")], -9.67)


# --- delay, gaps, listings -----------------------------------------------------------------------


def test_the_delay_stays_ten_minutes_unless_over_2_percent_are_later() -> None:
    delay, stats = fh.delay_from([5.0] * 98 + [12.0, 30.0])
    assert delay == timedelta(minutes=10)
    assert stats["late_share"] == 0.02
    delay, stats = fh.delay_from([5.0] * 96 + [12.0, 13.0, 14.0, 31.0])
    assert stats["late_share"] == 0.04
    assert delay == timedelta(
        minutes=np.ceil(np.percentile([5.0] * 96 + [12.0, 13.0, 14.0, 31.0], 98))
    )
    assert fh.delay_from([])[0] == timedelta(minutes=10)


def listed(element: Element, stamp: str) -> Listed:
    return Listed(
        element,
        grib.utc(stamp),
        f"u/{element.value}/{stamp}",
        Host.AWS,
        grib.utc(stamp) + timedelta(minutes=5),
    )


def test_gap_hours_are_hours_with_no_run_at_most_three_hours_old() -> None:
    runs = ndfd.assemble_runs([listed(e, "2025-01-06T00:46") for e in ndfd.ELEMENTS]).runs
    hours = [datetime(2025, 1, 6, h, tzinfo=UTC) for h in range(6)]
    assert [h.hour for h in fh.gap_hours(runs, hours)] == [0, 4, 5]
    many = ndfd.assemble_runs(
        [
            listed(e, f"2025-01-06T{h:02d}:{m:02d}")
            for e in ndfd.ELEMENTS
            for h, m in ((1, 16), (2, 49), (7, 46))
        ]
    ).runs
    every = [datetime(2025, 1, 6, 0, tzinfo=UTC) + timedelta(minutes=10 * i) for i in range(72)]
    assert fh.gap_hours(many, every) == [h for h in every if ndfd.newest_run(many, h) is None]


def test_listings_go_to_each_days_history_host() -> None:
    asked: list[str] = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        if "ncei" in url:
            return (
                b'<catalog><dataset name="YSUZ98_KWBN_202004160246"'
                b' urlPath="p/YSUZ98_KWBN_202004160246"></dataset></catalog>'
            )
        return b"<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>"

    assert fh.host_for(date(2020, 4, 16)) is Host.NCEI
    assert fh.host_for(date(2020, 4, 17)) is Host.AWS
    listings = fh.Listings(fetch)
    found = listings.around(date(2020, 4, 17)).listed
    assert [item.host for item in found] == [Host.NCEI]
    assert len(asked) == 4  # one catalog, three element listings
    listings.around(date(2020, 4, 17))
    assert len(asked) == 4  # each day once
    frame = fh.objects_frame([*found, *found])
    assert frame.height == 1
    assert frame["late_minutes"].to_list() == [None]
    assert frame["archive_copy"].to_list() == [False]


NCEI_DAY = (
    b'<catalog><dataset name="YSUZ98_KWBN_201911162246" urlPath="p/YSUZ98_KWBN_201911162246">'
    b"</dataset></catalog>"
)


def test_a_day_the_archive_lacks_lists_nothing_and_the_other_days_runs_still_count() -> None:
    asked: list[str] = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        if "/20191117/" in url:
            raise ndfd.NotFoundError(f"HTTP 404 for {url}")
        return NCEI_DAY

    listings = fh.Listings(fetch)
    around = listings.around(date(2019, 11, 17))
    assert around.missing == (date(2019, 11, 17),)
    assert around.error is None
    assert [item.stamp.day for item in around.listed] == [16]
    again = listings.around(date(2019, 11, 18))
    assert again.missing == (date(2019, 11, 17),)
    assert len(asked) == 3  # the missing day is not asked again
    assert fh.list_day_safely(fetch, date(2019, 11, 17)) == fh.DayListing(
        date(2019, 11, 17), missing=True
    )


def test_a_day_that_does_not_list_is_an_error_and_is_asked_again() -> None:
    answers: Iterator[bytes | Exception] = iter(
        [ndfd.NdfdError("HTTP 503 for x"), NCEI_DAY, NCEI_DAY]
    )

    def fetch(_: str) -> bytes:
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    listings = fh.Listings(fetch)
    around = listings.around(date(2019, 11, 17))
    assert around.error == "2019-11-16: HTTP 503 for x"
    later = listings.around(date(2019, 11, 17))  # 11-16 asked again, 11-17 kept
    assert later.error is None
    assert len(later.listed) == 2


def test_a_night_whose_listing_failed_is_unknown_even_with_runs_and_says_why() -> None:
    listed = make_run("2025-01-06T02:46", {e: [b"never read"] for e in ndfd.ELEMENTS}, {})
    runs = ndfd.assemble_runs(listed).runs
    schools = fh.deciding_schools(world.directory(), world.model())

    def opener(_: Listed) -> ndfd.Ranged:
        raise AssertionError("no run is read")

    failed = fh.night_codes(
        NIGHT,
        schools,
        fh.zone_groups(schools),
        runs,
        opener,
        SHARE,
        listing=fh.Around(listed, error="2025-01-05: HTTP 503"),
    )
    assert set(failed.codes["code"].to_list()) == {ndfd.Bucket.UNKNOWN}
    assert set(failed.samples["reason"].to_list()) == {"listing_failed"}
    assert set(failed.samples["error"].to_list()) == {"2025-01-05: HTTP 503"}
    assert failed.samples["run_time"].is_null().all()
    missing = fh.night_codes(
        NIGHT,
        schools,
        fh.zone_groups(schools),
        [],
        opener,
        SHARE,
        listing=fh.Around([], missing=(date(2025, 1, 5),)),
    )
    assert set(missing.codes["code"].to_list()) == {ndfd.Bucket.UNKNOWN}
    assert set(missing.samples["reason"].to_list()) == {"day_not_in_archive"}
    assert missing.samples["error"].is_null().all()
    assert fh.summarize(missing.samples, missing.codes)["reasons"] == {"day_not_in_archive": 42}


# --- the backfilled weeks of 2020 and prepare's guard -------------------------------------------

BULK = "2020-06-02T00:12"
"""When AWS wrote its copies of 2020-04-17 to 2020-05-28 (the critic's listing of 2020-04-20)."""


def aws(element: Element, stamp: str, written: str) -> Listed:
    when = grib.utc(stamp)
    return Listed(element, when, f"u/{element.value}/{stamp}", Host.AWS, grib.utc(written))


def test_an_archive_copy_counts_from_its_stamp_plus_the_delay_and_is_flagged() -> None:
    # The bulk upload: every object of 2020-04-17 to 05-28 written on 2020-06-02.
    bulk = [
        aws(e, f"2020-04-{day:02d}T{hour:02d}:16", BULK)
        for e in ndfd.ELEMENTS
        for day in range(20, 23)
        for hour in range(12)
    ]
    fills = ndfd.archive_fills(bulk)
    assert fills == {date(2020, 6, 2): 108}
    backfilled = bulk[::36]
    assert all(item.archive_copy(fills) and item.published_at(fills) is None for item in backfilled)
    (run,) = ndfd.assemble_runs(backfilled, fills=fills).runs
    assert run.archive_copy
    assert run.available_at == grib.utc("2020-04-20T00:26")
    assert ndfd.newest_run([run], grib.utc("2020-04-20T01:00")) == run
    # Without the fill day the copies hold the run until 2020-06-02: it never counts.
    (held,) = ndfd.assemble_runs(backfilled).runs
    assert not held.archive_copy
    assert held.available_at == grib.utc(BULK)
    # A few objects a day late on another day are no fill: late publications, held.
    few = [aws(e, "2025-02-05T06:47", "2025-02-06T07:00") for e in ndfd.ELEMENTS]
    assert ndfd.archive_fills(few) == {}
    (late,) = ndfd.assemble_runs(few, fills=ndfd.archive_fills(few)).runs
    assert not late.archive_copy
    assert late.available_at == grib.utc("2025-02-06T07:00")
    # Written late by less than a day: held until written (and so too old to count).
    some = [aws(e, "2020-05-30T12:16", "2020-05-30T12:20") for e in ndfd.ELEMENTS[:2]]
    some.append(aws(Element.APT, "2020-05-30T12:16", "2020-05-31T11:00"))
    (slow,) = ndfd.assemble_runs(some, fills=fills).runs
    assert slow.available_at == grib.utc("2020-05-31T11:00")
    assert ndfd.newest_run([slow], grib.utc("2020-05-31T11:00")) is None


def test_the_delay_leaves_out_archive_copies_and_objects_over_three_hours_late() -> None:
    # The critic's measure: 2.44% of school-day objects 5 to 46 days late made the delay 8 days.
    on_time = [4.0] * 9_600 + [12.0] * 150  # 1.5% over 10 minutes
    backfill = [7_200.0 + 100 * i for i in range(240)]
    hours_late = [200.0, 900.0, 1_400.0]
    delay, stats = fh.delay_from(on_time + backfill + hours_late)
    assert delay == timedelta(minutes=10)
    assert stats["over_a_day"] == 240
    assert stats["over_max_age"] == 3
    assert stats["objects"] == len(on_time)
    assert stats["late_share"] == pytest.approx(150 / 9_750)
    # Late objects within 3 hours still raise the delay to their 98th percentile.
    delay, stats = fh.delay_from([4.0] * 95 + [25.0] * 5 + backfill)
    assert delay == timedelta(minutes=25)
    assert stats["over_a_day"] == 240


def hourly(
    day: date,
    written_after: timedelta,
    hours: Iterable[int] = range(24),
    written: datetime | None = None,
) -> fh.DayListing:
    found: list[Listed] = []
    for hour in hours:
        stamp = datetime(day.year, day.month, day.day, hour, 16, tzinfo=UTC)
        when = written or stamp + written_after
        found.extend(
            Listed(e, stamp, f"u/{e.value}/{stamp:%Y%m%d%H%M}", Host.AWS, when)
            for e in ndfd.ELEMENTS
        )
    return fh.DayListing(day, tuple(found))


WEEK = [date(2025, 1, 5) + timedelta(days=i) for i in range(6)]


def test_prepare_measures_the_feed_and_keeps_the_backfill_out_of_the_delay() -> None:
    days = [hourly(day, timedelta(minutes=4)) for day in WEEK]
    # Two backfilled days: every object written in one bulk upload weeks later.
    bulk = datetime(2025, 2, 6, 0, 12, tzinfo=UTC)
    days[2] = hourly(WEEK[2], timedelta(0), written=bulk)
    days[3] = hourly(WEEK[3], timedelta(0), written=bulk)
    feed = fh.measure_feed(days)
    assert feed.problems == ()
    assert feed.delay == timedelta(minutes=10)
    report = feed.report
    assert report["archive_fill_days"] == {"2025-02-06": 144}
    assert report["archive_copies"] == 144
    assert report["late_over_a_day_held"] == 0
    assert report["runs_archive_copy"] == 48
    assert feed.fills == (date(2025, 2, 6),)
    assert report["gap_share_by_season"] == {"2024-25": 0.0}
    assert report["school_day_hours_by_season"] == {"2024-25": 5 * 24}
    stats = report["lateness_school_days"]
    assert isinstance(stats, dict)
    assert stats["over_a_day"] == 144


def test_prepare_fails_before_the_matrix_on_a_long_delay_gaps_or_days_not_listed() -> None:
    slow = fh.measure_feed([hourly(day, timedelta(minutes=45)) for day in WEEK])
    assert slow.delay == timedelta(minutes=45)
    assert slow.problems[0] == "the delay is 0:45:00, over 0:30:00"
    sparse = fh.measure_feed([hourly(day, timedelta(minutes=4), (0, 12)) for day in WEEK])
    assert sparse.problems == ("2024-25: 75.0% of school-day hours have no run",)
    failed = [hourly(day, timedelta(minutes=4)) for day in WEEK]
    failed[3] = fh.DayListing(WEEK[3], error="HTTP 503")
    found = fh.measure_feed(failed)
    assert found.report["failed_days"] == {"2025-01-08": "HTTP 503"}
    assert found.problems[-1] == "1 of 6 days did not list"
    missing = [hourly(day, timedelta(minutes=4)) for day in WEEK]
    missing[3] = fh.DayListing(WEEK[3], missing=True)
    kept = fh.measure_feed(missing)
    assert kept.report["missing_days"] == ["2025-01-08"]
    assert not any("did not list" in p for p in kept.problems)


def probe_run(
    day: date, stamp: str, store: dict[str, bytes], *, bad: bool = False, month_on: bool = False
) -> list[Listed]:
    """A run on UTC day ``day`` at ``stamp`` (HH:MM); ``bad`` stamps its snow periods off,
    ``month_on`` makes its snow file hold a run a month later."""
    when = datetime.combine(day, datetime.strptime(stamp, "%H:%M").time(), tzinfo=UTC)
    reference = when.replace(minute=30 if when.minute < 30 else 0) + timedelta(
        hours=0 if when.minute < 30 else 1
    )
    snow_reference = reference + timedelta(days=31) if month_on else reference
    files = {
        Element.SNOW: amounts(
            snow_reference, {}, bad_middle=bad, night=snow_reference.date() + timedelta(days=1)
        ),
        Element.ICE: amounts(
            reference, {}, element=Element.ICE, night=reference.date() + timedelta(days=1)
        ),
        Element.APT: [grib.message(Element.APT.parameter, reference, lead_hours=1, values=270.0)],
    }
    return make_run(when.strftime("%Y-%m-%dT%H:%M"), files, store)


def test_prepare_probes_a_run_a_week_and_stops_on_a_month_that_does_not_read() -> None:
    store: dict[str, bytes] = {}
    days = [date(2025, 1, 6), date(2025, 1, 13), date(2025, 1, 21), date(2025, 2, 3)]
    listed = [
        *probe_run(days[0], "02:46", store),
        *probe_run(days[1], "02:16", store),
        *probe_run(days[1], "02:46", store, month_on=True),  # refused: the 02:16 run is probed
        *probe_run(days[2], "02:46", store, bad=True),
        *probe_run(days[3], "02:46", store, bad=True),
    ]
    runs = ndfd.assemble_runs(listed).runs

    def opener(item: Listed) -> ndfd.Ranged:
        return ndfd.bytes_reader(store[item.url])

    probe = fh.probe_periods(runs, opener, [*days, date(2025, 2, 4)], workers=2)
    report = probe.report
    assert report["probe_by_month"] == {
        "2025-01": {
            "nights": 3,
            "refused": 1,
            "probed": 3,
            "stamp_start": 3,
            "repeated": 0,
            "errors": 1,
        },
        "2025-02": {
            "nights": 2,
            "refused": 0,
            "probed": 1,
            "stamp_start": 1,
            "repeated": 0,
            "errors": 1,
            "no_run": 1,
        },
    }
    assert probe.problems == ("2025-02: 1 of 1 probed runs have an element that does not read",)
    assert report["probe_refused"] == [
        {
            "night": "2025-01-13",
            "run": "2025-01-13T02:46:00+00:00",
            "why": "snow reference 2025-02-13 03:00Z, run 2025-01-13 02:46Z",
        }
    ]
    failures = report["probe_failures"]
    assert isinstance(failures, list)
    assert [f["night"] for f in failures if isinstance(f, dict)] == ["2025-01-21", "2025-02-03"]


def test_the_probe_takes_a_morning_run_when_no_evening_run_counts() -> None:
    # NCEI has no evening runs on many nights of 2018-19 and 2019-20.
    store: dict[str, bytes] = {}
    night = date(2020, 1, 14)
    runs = ndfd.assemble_runs(probe_run(night, "11:46", store)).runs
    probe = fh.probe_periods(runs, opener_of(store), [night])
    assert probe.report["probe_by_month"] == {
        "2020-01": {"nights": 1, "refused": 0, "probed": 1, "stamp_start": 1, "repeated": 0}
    }


def test_the_probe_takes_the_first_night_of_every_week_of_the_history() -> None:
    found = fh.probe_nights()
    every = sorted(
        d
        for s in range(fh.FIRST_SEASON, fh.LAST_SEASON + 1)
        for c in range(10)
        for d in fh.nights(s, c)
    )
    assert found[0] == every[0] == date(2018, 8, 15)
    assert len({d.isocalendar()[:2] for d in every}) == len(found)
    assert all(
        d == min(e for e in every if e.isocalendar()[:2] == d.isocalendar()[:2]) for d in found
    )


def test_collect_names_the_months_whose_samples_mostly_did_not_read() -> None:
    samples = pl.DataFrame(
        {
            "night": [date(2018, 9, 12)] * 4 + [date(2018, 11, 5)] * 2,
            "reason": ["run_error", "element_error", "listing_failed", None, "no_run", None],
        }
    )
    shares = fh.error_share_by_month(samples)
    assert shares == {"2018-09": 0.75, "2018-11": 0.0}
    assert fh.error_problems(shares) == [
        "2018-09: 75.0% of samples from runs or listings that did not read"
    ]
    assert fh.error_share_by_month(samples.clear()) == {}


# --- the heads-up files --------------------------------------------------------------------------

HEADER = (
    "wfo,utc_issue,utc_expire,utc_prodissue,utc_init_expire,phenomena,gtype,significance,eventid,"
    "status,ugc,area2d,utc_updated,hvtec_nwsli,hvtec_severity,hvtec_cause,hvtec_record,"
    "is_emergency,utc_polygon_begin,utc_polygon_end,windtag,hailtag,tornadotag,damagetag,"
    "product_id,fcster,vtec_year"
)


def row(code: str, ugc: str = "MOZ028", status: str = "UPG") -> str:
    phenomena, significance = code.split(".")
    return (
        f"EAX,2025-01-05 00:00,2025-01-03 18:56,2025-01-02 20:09,2025-01-06 00:00,{phenomena},C,"
        f"{significance},1,{status},{ugc},1234.5,2025-01-03 18:56,,,,,False,,,,,,,"
        f"202501022009-KEAX-WWUS83-WSWEAX,,2025"
    )


def csv(rows: Iterable[str]) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


def test_the_heads_up_codes_are_one_table() -> None:
    assert frozenset(HEADS_UP_BY_CODE) == inputs.HEADS_UP_CODES
    assert HEADS_UP_BY_CODE["BZ.A"] is HeadsUp.WINTER_STORM_WATCH
    assert HEADS_UP_BY_CODE["WC.Y"] is HEADS_UP_BY_CODE["CW.Y"] is HeadsUp.COLD_WEATHER_ADVISORY
    assert "IS.A" not in HEADS_UP_BY_CODE
    assert "EC.Y" not in HEADS_UP_BY_CODE
    assert HeadsUp.TROPICAL_STORM_WATCH.label == "tropical_storm_watch"
    url = inputs.headsup_url(2024)
    assert "phenomena=WS,BZ,LE,WC,EC,HU,TR,CW,WC&significance=A,A,A,A,A,A,A,Y,Y" in url
    assert "sts=2024-08-01T00:00Z&ets=2025-06-17T00:00Z" in url
    path = inputs.headsup_path(inputs.HEADS_UP_CACHE, 2024)
    assert path.parts[-4:] == (
        "predict",
        "mesonet.agron.iastate.edu",
        "watchwarn-headsup-csv",
        "2024-2025.csv",
    )
    assert "weights" not in path.parts


def test_a_heads_up_file_reads_and_counts_by_code() -> None:
    rows, by_code, closed = inputs.read_headsup(
        csv([row("WS.A"), row("WS.A", "KSZ104"), row("CW.Y", status="CAN"), row("WS.A", "PKZ130")])
    )
    assert by_code == {"CW.Y": 1, "WS.A": 2}
    assert closed == 0
    assert {r.status for r in rows} == {"UPG", "CAN"}
    with pytest.raises(ArchiveCsvError, match="was not asked for"):
        inputs.read_headsup(csv([row("WS.W")]))


def tropical(code: str, ugc: str, status: str, expire: str, etn: int = 1003) -> str:
    phenomena, significance = code.split(".")
    return (
        f"NHC,2016-06-06 03:00,{expire},2016-06-06 03:00,{expire},{phenomena},C,{significance},"
        f"{etn},{status},{ugc},800.0,{expire},,,,,False,,,,,,,201606060300-KNHC-WTNT83-TCVAT3,,2016"
    )


def test_a_tropical_watch_no_product_ended_ends_with_its_event() -> None:
    # IEM keeps a placeholder end on a watch "until further notice" (spec-f s. 3: a row that is
    # not cancelled or upgraded counts while its span overlaps the window).
    rows, by_code, closed = inputs.read_headsup(
        csv(
            [
                tropical("TR.A", "GAZ138", "CAN", "2016-06-07 12:00"),
                tropical("TR.A", "SCZ047", "CON", "2016-06-12 12:00"),
                tropical("HU.A", "FLZ052", "NEW", "2016-06-12 12:00", etn=1004),
            ]
        )
    )
    assert by_code == {"HU.A": 1, "TR.A": 2}
    assert closed == 1
    ends = {r.ugc: r.end for r in rows}
    assert ends["SCZ047"] == datetime(2016, 6, 7, 12, tzinfo=UTC)
    # Marked: that end came from a later product, so before it passes the watch was still open.
    recorded = {r.ugc: r.recorded_end for r in rows}
    assert recorded == {
        "GAZ138": None,
        "SCZ047": datetime(2016, 6, 12, 12, tzinfo=UTC),
        "FLZ052": None,
    }
    # An event with no explicitly ended row keeps its span (none in the 2015-27 files).
    assert ends["FLZ052"] == datetime(2016, 6, 12, 12, tzinfo=UTC)


def test_codes_in_seasons_they_cannot_have_are_named() -> None:
    assert inputs.code_problems({2016: {"BZ.A": 3, "WC.Y": 9}, 2024: {"EC.A": 1, "CW.Y": 2}}) == []
    assert inputs.code_problems(
        {2017: {"BZ.A": 1}, 2023: {"EC.A": 2, "WC.A": 4}, 2024: {"WC.Y": 5, "WS.A": 0}}
    ) == ["2017-18: 1 rows of BZ.A", "2023-24: 2 rows of EC.A", "2024-25: 5 rows of WC.Y"]


# --- the workflow --------------------------------------------------------------------------------


def test_the_workflow_runs_once_on_landing_and_on_demand_and_commits_nothing() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow[True]
    assert triggers["push"] == {"paths": [".github/workflows/predict-forecast-history.yml"]}
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers
    assert workflow["permissions"]["contents"] == "read"
    jobs = workflow["jobs"]
    matrix = jobs["nights"]["strategy"]["matrix"]
    assert matrix["season"] == list(range(fh.FIRST_SEASON, fh.LAST_SEASON + 1))
    assert matrix["chunk"] == list(range(len(fh.CHUNKS)))
    assert jobs["nights"]["strategy"]["fail-fast"] is False
    for name, job in jobs.items():
        runs = [str(step.get("run", "")) for step in job["steps"]]
        assert "uv sync --locked --no-dev" in runs, name
        assert not any("git push" in r or "git commit" in r for r in runs), name
        uploads = [
            s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact")
        ]
        assert uploads, name
        assert all(s["with"]["retention-days"] == 90 for s in uploads)
