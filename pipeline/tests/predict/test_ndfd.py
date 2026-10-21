"""The NDFD reader (S7-F F1): grid, flip, index, range walk, runs, window, 50% value, buckets.

Every GRIB message here is synthetic (tests/predict/grib.py); no real forecast is read.
"""

from datetime import UTC, date, datetime, timedelta
from itertools import product

import eccodes  # type: ignore[import-untyped]
import numpy as np
import pytest

from predict import grib
from snowlight.predict import ndfd
from snowlight.predict.ndfd import Bucket, Element, Host, Listed

SNOW = Element.SNOW.parameter
APT = Element.APT.parameter
RAMP = 10_000.0 + np.arange(ndfd.NX * ndfd.NY, dtype=np.float64)
"""Cell numbers, kept clear of the missing value 9999."""
CITIES = (
    ("Kansas City", 39.2976, -94.7139),
    ("Minneapolis", 44.88, -93.22),
    ("Boston", 42.36, -71.01),
    ("Seattle", 47.45, -122.31),
    ("Dallas", 32.90, -97.04),
    ("Miami", 25.79, -80.29),
    ("Bismarck", 46.77, -100.75),
)


@pytest.fixture(scope="module")
def ramp() -> bytes:
    return grib.message(APT, grib.utc("2025-01-06T03:00"), lead_hours=9, values=RAMP)


def test_the_flip_and_the_lambert_index_find_exactly_the_cell_eccodes_calls_nearest(
    ramp: bytes,
) -> None:
    head = ndfd.parse_head(ramp, 0)
    decoded = ndfd.decode(ramp, head)
    assert np.array_equal(decoded.values.reshape(-1), RAMP)
    lat = np.array([c[1] for c in CITIES])
    lon = np.array([c[2] for c in CITIES])
    where = ndfd.cells(lat, lon)
    assert where.inside.all()
    mine = ndfd.sample(decoded.values, where)
    handle = eccodes.codes_new_from_message(ramp)
    try:
        nearest = [
            eccodes.codes_grib_find_nearest(handle, a, o)[0]["value"]
            for a, o in zip(lat, lon, strict=True)
        ]
    finally:
        eccodes.codes_release(handle)
    assert mine.tolist() == nearest
    # Without the flip an odd row reads another cell (research B, gotcha 1).
    raw = np.array(eccodes_values(ramp)).reshape(ndfd.NY, ndfd.NX)
    odd = where.row % 2 == 1
    assert odd.any()
    assert not np.array_equal(raw[where.row[odd], where.col[odd]], mine[odd])


def test_the_lambert_index_agrees_with_eccodes_coordinates_and_the_flip_keeps_rows_whole(
    ramp: bytes,
) -> None:
    # eccodes 2.49 (pinned), on real NDFD messages as on these: the "latitudes" and "longitudes"
    # arrays (and find_nearest's index) are in natural order, index = row * NX + col with rows
    # south to north and each row west to east; codes_get_values is in the file's order, odd
    # rows reversed (scanning mode 80). So the index is checked against the coordinates, not
    # against find_nearest's value, and decode must flip the odd rows back.
    handle = eccodes.codes_new_from_message(ramp)
    try:
        lat = np.asarray(eccodes.codes_get_array(handle, "latitudes"), dtype=np.float64)
        lon = np.asarray(eccodes.codes_get_array(handle, "longitudes"), dtype=np.float64)
    finally:
        eccodes.codes_release(handle)
    count = ndfd.NX * ndfd.NY
    assert lat.shape == lon.shape == (count,)
    picked = np.random.default_rng(7).choice(count, 4_000, replace=False)
    corners = [0, ndfd.NX - 1, ndfd.NX, 2 * ndfd.NX - 1, count - ndfd.NX, count - 1]
    index = np.concatenate([picked, corners])
    where = ndfd.cells(lat[index], lon[index])
    assert where.inside.all()
    assert where.row.tolist() == (index // ndfd.NX).tolist()
    assert where.col.tolist() == (index % ndfd.NX).tolist()
    assert int((where.row % 2).sum()) > 1_500
    # A smooth field (true order) written in the file's order: decoded, neighbouring rows stay
    # close; read in the file's order, every odd row runs the other way.
    rows, cols = np.divmod(np.arange(count, dtype=np.float64), ndfd.NX)
    smooth = 300.0 + 0.01 * cols + 0.001 * rows
    message = grib.message(APT, grib.utc("2025-01-06T03:00"), lead_hours=9, values=smooth)
    decoded = ndfd.decode(message, ndfd.parse_head(message, 0)).values
    assert np.abs(np.diff(decoded, axis=0)).mean() < 0.01
    raw = np.array(eccodes_values(message)).reshape(ndfd.NY, ndfd.NX)
    assert np.abs(np.diff(raw, axis=0)).mean() > 5.0


def eccodes_values(raw: bytes) -> list[float]:
    handle = eccodes.codes_new_from_message(raw)
    try:
        return list(eccodes.codes_get_values(handle))
    finally:
        eccodes.codes_release(handle)


def test_a_point_off_the_grid_reads_nothing() -> None:
    where = ndfd.cells(np.array([10.0, 39.0]), np.array([-94.0, 265.3]))
    assert where.inside.tolist() == [False, True]
    grid = np.ones((ndfd.NY, ndfd.NX))
    values = ndfd.sample(grid, where)
    assert np.isnan(values[0])
    assert values[1] == 1.0


@pytest.mark.parametrize(
    "change",
    [{"LoVInDegrees": 262.5}, {"DxInMetres": 5079.406, "DyInMetres": 5079.406}, {"Nx": 2144}],
)
def test_a_grid_that_is_not_ndfds_is_refused(change: dict[str, float]) -> None:
    count = int(change.get("Nx", ndfd.NX)) * ndfd.NY
    raw = grib.message(
        SNOW,
        grib.utc("2025-01-06T03:00"),
        lead_hours=0,
        end=grib.utc("2025-01-06T06:00"),
        values=np.zeros(count) + 0.01,
        grid=change,
    )
    with pytest.raises(ndfd.GridError):
        ndfd.decode(raw, ndfd.parse_head(raw, 0))


def test_eccodes_must_read_the_heads_parameter_and_times() -> None:
    raw = grib.message(
        SNOW, grib.utc("2025-01-06T03:00"), lead_hours=0, end=grib.utc("2025-01-06T06:00")
    )
    head = ndfd.parse_head(raw, 0)
    assert head.template == 8
    assert (head.reference, head.start, head.end) == (
        grib.utc("2025-01-06T03:00"),
        grib.utc("2025-01-06T03:00"),
        grib.utc("2025-01-06T06:00"),
    )
    with pytest.raises(ndfd.NdfdError, match="parameter"):
        ndfd.decode(raw, ndfd.Head(0, head.length, APT, head.reference, head.start, head.end, 8))
    late = head.end + timedelta(hours=6)
    with pytest.raises(ndfd.NdfdError, match="eccodes reads"):
        ndfd.decode(raw, ndfd.Head(0, head.length, SNOW, head.reference, head.start, late, 8))


def test_missing_cells_read_as_nan() -> None:
    values = np.full(ndfd.NX * ndfd.NY, 0.02)
    values[:5000] = np.nan
    raw = grib.message(
        SNOW,
        grib.utc("2025-01-06T03:00"),
        lead_hours=0,
        end=grib.utc("2025-01-06T06:00"),
        values=values,
    )
    decoded = ndfd.decode(raw, ndfd.parse_head(raw, 0)).values.reshape(-1)
    assert np.isnan(decoded[:5000]).all()
    assert np.allclose(decoded[5000:], 0.02)


# --- the range walk -----------------------------------------------------------------------------


def snow_run(reference: datetime) -> list[bytes]:
    """A partial period from ``reference`` to the next 6-hour end, then two whole periods."""
    end = reference.replace(hour=reference.hour - reference.hour % 6) + timedelta(hours=6)
    found = [grib.message(SNOW, reference, lead_hours=0, end=end, values=0.01)]
    for step in range(2):
        start = end + timedelta(hours=6 * step)
        lead = (start - reference).total_seconds() / 3600
        found.append(
            grib.message(
                SNOW, reference, lead_hours=lead, end=start + timedelta(hours=6), values=0.02
            )
        )
    return found


class Counting:
    def __init__(self, data: bytes) -> None:
        self.read = ndfd.bytes_reader(data)
        self.calls: list[tuple[int, int]] = []

    def __call__(self, offset: int, size: int) -> bytes:
        self.calls.append((offset, size))
        return self.read(offset, size)


def test_framed_and_bare_files_walk_alike_reading_only_heads() -> None:
    messages = snow_run(grib.utc("2025-01-06T03:00"))
    bare = b"".join(messages)
    wmo = grib.framed(messages)
    walked = []
    for data in (bare, wmo):
        reader = Counting(data)
        heads = list(ndfd.walk(reader))
        assert all(size == ndfd.HEAD_BYTES for _, size in reader.calls)
        walked.append([(h.start, h.end, h.length) for h in heads])
        for head in heads:
            assert ndfd.message(reader, head)[:4] == b"GRIB"
    assert walked[0] == walked[1]
    assert [end.hour for _, end, _ in walked[0]] == [6, 12, 18]


def test_a_walk_stops_at_the_head_it_was_told_to() -> None:
    reference = grib.utc("2025-01-06T03:00")
    data = grib.framed(
        [grib.message(APT, reference, lead_hours=hour, values=260.0) for hour in range(1, 6)],
        "YTUZ98 KWBN 060246",
    )
    heads = list(
        ndfd.walk(ndfd.bytes_reader(data), stop=lambda h: h.end >= grib.utc("2025-01-06T06:00"))
    )
    assert [h.end.hour for h in heads] == [4, 5, 6]


def test_a_cut_message_and_junk_between_messages_are_errors() -> None:
    raw = snow_run(grib.utc("2025-01-06T03:00"))[0]
    head = ndfd.parse_head(raw, 0)
    with pytest.raises(ndfd.NdfdError, match="cut short"):
        ndfd.message(ndfd.bytes_reader(raw[:-10]), head)
    with pytest.raises(ndfd.NdfdError, match="no GRIB"):
        list(ndfd.walk(ndfd.bytes_reader(b"x" * (ndfd.HEAD_BYTES + 10) + raw)))
    with pytest.raises(ndfd.NdfdError, match="edition"):
        ndfd.parse_head(raw[:7] + b"\x01" + raw[8:], 0)


# --- runs ---------------------------------------------------------------------------------------


def listed(element: Element, stamp: str, written: str | None = None) -> Listed:
    when = grib.utc(stamp)
    return Listed(
        element,
        when,
        f"https://example.invalid/{element.heading}_{stamp}",
        Host.AWS,
        None if written is None else grib.utc(written),
    )


def test_a_run_is_three_elements_in_one_half_hour_and_counts_ten_minutes_after_its_time() -> None:
    files = [
        listed(Element.SNOW, "2025-01-06T02:46"),
        listed(Element.ICE, "2025-01-06T02:46"),
        listed(Element.APT, "2025-01-06T02:47"),
        listed(Element.SNOW, "2025-01-06T03:16"),
        listed(Element.ICE, "2025-01-06T03:16"),
    ]
    assembled = ndfd.assemble_runs(files)
    assert assembled.incomplete == (grib.utc("2025-01-06T03:00"),)
    (run,) = assembled.runs
    assert run.time == grib.utc("2025-01-06T02:47")
    assert run.available_at == grib.utc("2025-01-06T02:57")
    assert ndfd.newest_run(assembled.runs, grib.utc("2025-01-06T02:56")) is None
    assert ndfd.newest_run(assembled.runs, grib.utc("2025-01-06T02:57")) == run


def test_a_late_object_holds_the_run_until_it_was_written() -> None:
    files = [
        listed(Element.SNOW, "2025-01-06T02:46", "2025-01-06T02:50"),
        listed(Element.ICE, "2025-01-06T02:46", "2025-01-06T03:05"),
        listed(Element.APT, "2025-01-06T02:46", "2025-01-06T02:52"),
    ]
    (run,) = ndfd.assemble_runs(files).runs
    assert run.available_at == grib.utc("2025-01-06T03:05")
    late = ndfd.assemble_runs(files, delay=timedelta(minutes=25)).runs[0]
    assert late.available_at == grib.utc("2025-01-06T03:11")


def test_a_run_counts_while_at_most_three_hours_old_and_the_newest_wins() -> None:
    runs = ndfd.assemble_runs(
        [listed(e, s) for e in ndfd.ELEMENTS for s in ("2025-01-06T00:16", "2025-01-06T00:46")]
    ).runs
    assert ndfd.newest_run(runs, grib.utc("2025-01-06T01:00")).time.minute == 46  # type: ignore[union-attr]
    assert ndfd.newest_run(runs, grib.utc("2025-01-06T03:46")) is not None
    assert ndfd.newest_run(runs, grib.utc("2025-01-06T03:47")) is None


AWS_PAGE = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>noaa-ndfd-pds</Name>
<IsTruncated>true</IsTruncated><Contents><Key>wmo/snow/2025/02/18/YSUZ98_KWBN_202502180016</Key>
<LastModified>2025-02-18T00:22:00.000Z</LastModified></Contents><Contents>
<Key>wmo/snow/2025/02/18/YSUZ98_KWBN_202502180046.tmp</Key>
<LastModified>2025-02-18T00:52:19.000Z</LastModified></Contents>
<NextContinuationToken>abc/+=</NextContinuationToken></ListBucketResult>"""
NCEI_PAGE = b"""<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0">
<dataset name="YSUZ98_KWBN_201901150246" ID="NDFD-OLD/201901/20190115/YSUZ98_KWBN_201901150246"
 urlPath="model-ndfd-file-old/201901/20190115/YSUZ98_KWBN_201901150246"></dataset>
<dataset name="YAUZ98_KWBN_201901150246" ID="x" urlPath="model-ndfd-file-old/x"></dataset>
<dataset name="YTUZ98_KWBN_201901150247" ID="y"
 urlPath="model-ndfd-file-old/201901/20190115/YTUZ98_KWBN_201901150247"></dataset>
</catalog>"""


def test_listings_of_both_hosts_read() -> None:
    found, token = ndfd.parse_aws_listing(AWS_PAGE)
    assert token == "abc/+="  # noqa: S105 - a listing's continuation token
    (item,) = found
    assert item.stamp == grib.utc("2025-02-18T00:16")
    assert item.lateness == timedelta(minutes=6)
    assert "continuation-token=abc%2F%2B%3D" in ndfd.aws_listing_url(
        Element.SNOW, date(2025, 2, 18), token
    )
    catalog = ndfd.parse_ncei_catalog(NCEI_PAGE)
    assert [(i.element, i.last_modified) for i in catalog] == [
        (Element.SNOW, None),
        (Element.APT, None),
    ]
    assert catalog[0].url.endswith(
        "/thredds/fileServer/model-ndfd-file-old/201901/20190115/YSUZ98_KWBN_201901150246"
    )
    with pytest.raises(ndfd.NdfdError):
        ndfd.parse_aws_listing(b"<html/>")
    with pytest.raises(ndfd.NdfdError):
        ndfd.parse_ncei_catalog(b"<html/>")
    with pytest.raises(ndfd.NdfdError):
        ndfd.parse_aws_listing(
            AWS_PAGE.replace(b"<NextContinuationToken>abc/+=</NextContinuationToken>", b"")
        )
    with pytest.raises(ndfd.NdfdError):
        ndfd.stamp_of("2025021800")


# --- the window ---------------------------------------------------------------------------------


def head(reference: str, start: str, end: str, span: float = 6) -> ndfd.Head:
    return ndfd.Head(
        0, 1, SNOW, grib.utc(reference), grib.utc(start), grib.utc(end), 8, timedelta(hours=span)
    )


def test_every_amount_message_is_the_whole_6_hour_period_ending_at_its_end() -> None:
    # Since 2018-10-30 13:47Z: the first message stamped at the reference time, inside the
    # period under way, the rest at their period's start. Each holds the whole period (measured
    # on real runs, docs/predict.md), snow before the run included.
    start = [
        head("2025-01-06T03:30", "2025-01-06T03:30", "2025-01-06T06:00"),
        head("2025-01-06T03:30", "2025-01-06T06:00", "2025-01-06T12:00"),
    ]
    assert ndfd.period_stamp(start) is ndfd.PeriodStamp.START
    assert [h.period_start for h in start] == [grib.utc("2025-01-06T00:00"), start[1].start]
    # Until 2018-10-30 13:15Z: every message stamped at its period's end (start == end).
    end = [
        head("2018-09-12T11:30", "2018-09-12T12:00", "2018-09-12T12:00"),
        head("2018-09-12T11:30", "2018-09-12T18:00", "2018-09-12T18:00"),
    ]
    assert ndfd.period_stamp(end) is ndfd.PeriodStamp.END
    assert end[0].period_start == grib.utc("2018-09-12T06:00")
    # A reference time on a period's start: the first period is whole either way.
    on_start = [head("2025-01-06T06:00", "2025-01-06T06:00", "2025-01-06T12:00")]
    assert ndfd.period_stamp(on_start) is ndfd.PeriodStamp.START


@pytest.mark.parametrize(
    ("heads", "message"),
    [
        ([], "no amount message"),
        ([head("2025-01-06T03:30", "2025-01-06T03:30", "2025-01-06T06:00", span=2.5)], "not 6"),
        ([head("2025-01-06T03:30", "2025-01-06T03:30", "2025-01-06T07:00")], "off the hours"),
        (
            [
                head("2025-01-06T03:30", "2025-01-06T03:30", "2025-01-06T06:00"),
                head("2025-01-06T04:00", "2025-01-06T06:00", "2025-01-06T12:00"),
            ],
            "two reference times",
        ),
        (
            [
                head("2025-01-06T03:30", "2025-01-06T03:30", "2025-01-06T12:00"),
                head("2025-01-06T03:30", "2025-01-06T00:00", "2025-01-06T06:00"),
            ],
            "do not rise",
        ),
        ([head("2025-01-06T03:30", "2025-01-06T06:00", "2025-01-06T12:00")], "not the one"),
        ([head("2025-01-06T06:00", "2025-01-06T06:00", "2025-01-06T06:00")], "not the one"),
        (
            [
                head("2025-01-06T03:30", "2025-01-06T03:30", "2025-01-06T06:00"),
                head("2025-01-06T03:30", "2025-01-06T12:00", "2025-01-06T12:00"),
            ],
            "neither",
        ),
    ],
)
def test_amount_messages_that_do_not_fit_are_refused(heads: list[ndfd.Head], message: str) -> None:
    with pytest.raises(ndfd.PeriodError, match=message):
        ndfd.period_stamp(heads)


def test_both_stamps_read_from_real_section_4_bytes_and_decode() -> None:
    reference = grib.utc("2018-09-12T11:30")
    noon = grib.utc("2018-09-12T12:00")
    for lead, stamp in ((0.0, ndfd.PeriodStamp.START), (0.5, ndfd.PeriodStamp.END)):
        raw = grib.message(SNOW, reference, lead_hours=lead, end=noon, values=0.01)
        parsed = ndfd.parse_head(raw, 0)
        assert parsed.span == timedelta(hours=6)
        assert parsed.end == noon
        assert parsed.period_start == grib.utc("2018-09-12T06:00")
        assert ndfd.period_stamp([parsed]) is stamp
        assert np.allclose(ndfd.decode(raw, parsed).values[:3, :3], 0.01)


def test_a_files_reference_time_must_fit_its_run() -> None:
    run_time = grib.utc("2019-06-03T00:17")
    assert ndfd.reference_ok(grib.utc("2019-06-03T00:30"), run_time)
    assert ndfd.reference_ok(run_time, run_time)
    assert not ndfd.reference_ok(run_time + timedelta(hours=1), run_time)
    assert not ndfd.reference_ok(run_time - timedelta(minutes=1), run_time)
    # NCEI's 201906030016/0017 files hold the run of 2019-07-03 00:30.
    assert not ndfd.reference_ok(grib.utc("2019-07-03T00:30"), run_time)


def test_the_window_is_the_periods_ending_06_12_18z_less_those_ended() -> None:
    day = date(2025, 1, 6)
    ends = ndfd.window_ends(day)
    assert [e.hour for e in ends] == [6, 12, 18]
    by_end = {end: np.array([float(i + 1)]) for i, end in enumerate(ends)}
    assert ndfd.window_total(by_end, day, grib.utc("2025-01-06T01:00")).tolist() == [6.0]  # type: ignore[union-attr]
    assert ndfd.window_total(by_end, day, grib.utc("2025-01-06T06:00")).tolist() == [5.0]  # type: ignore[union-attr]
    assert ndfd.window_total(by_end, day, grib.utc("2025-01-06T18:00")).tolist() == [0.0]  # type: ignore[union-attr]
    del by_end[ends[2]]
    assert ndfd.window_total(by_end, day, grib.utc("2025-01-06T07:00")) is None
    assert ndfd.window_total({}, day, grib.utc("2025-01-06T19:00")) is None
    heads = [
        head("2025-01-06T03:00", "2025-01-06T03:00", "2025-01-06T06:00"),
        head("2025-01-06T03:00", "2025-01-06T18:00", "2025-01-07T00:00"),
    ]
    assert list(ndfd.amount_heads(heads, day)) == [ends[0]]


@pytest.mark.parametrize(
    ("day", "zone", "hour"),
    [
        (date(2025, 1, 6), "America/New_York", 12),
        (date(2025, 1, 6), "America/Chicago", 13),
        (date(2025, 1, 6), "America/Denver", 14),
        (date(2025, 1, 6), "America/Los_Angeles", 15),
        (date(2025, 3, 10), "America/New_York", 11),
        (date(2025, 3, 10), "America/Los_Angeles", 14),
        (date(2025, 3, 10), "America/Phoenix", 14),
        (date(2025, 11, 3), "America/Chicago", 13),
    ],
)
def test_the_bus_hour_follows_each_zone_and_daylight_time(day: date, zone: str, hour: int) -> None:
    assert ndfd.bus_time(day, zone) == datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def test_apparent_temperature_is_the_message_valid_at_each_bus_time() -> None:
    reference = grib.utc("2025-01-06T03:00")
    heads = [
        ndfd.Head(
            0, 1, APT, reference, reference + timedelta(hours=h), reference + timedelta(hours=h), 0
        )
        for h in range(1, 12)
    ]
    found = ndfd.apt_heads(heads, [grib.utc("2025-01-06T12:00"), grib.utc("2025-01-06T15:00")])
    assert sorted(t.hour for t in found) == [12]


# --- units, the 50% value and buckets ------------------------------------------------------------


def test_units_land_exactly_on_bucket_bounds() -> None:
    assert ndfd.snow_inches(np.array([0.0508])).tolist() == [2.0]
    assert ndfd.ice_inches(np.array([0.254])).tolist() == [0.01]
    assert ndfd.fahrenheit(np.array([260.927777777778])).tolist() == [10.0]


def test_the_50_percent_value_is_the_largest_amount_half_the_schools_reach() -> None:
    values = np.array([1.0, 5.0, 3.0, 2.0, 9.0, 4.0, 4.0, np.nan, 7.0])
    group = np.array([0, 0, 0, 0, 1, 1, 1, 2, 2])
    groups = ndfd.groups_of(group)
    assert ndfd.group_half(values, groups).tolist()[:2] == [3.0, 4.0]
    assert np.isnan(ndfd.group_half(values, groups)[2])
    coldest = ndfd.group_half(values, groups, coldest=True)
    assert coldest.tolist()[:2] == [2.0, 4.0]
    low, high = ndfd.group_min_max(values, groups)
    assert low.tolist()[:2] == [1.0, 4.0]
    assert high.tolist()[:2] == [5.0, 9.0]
    assert np.isnan(low[2])
    # The rule matches the class's: count(at least v) >= share * schools.
    for share in (0.5, 0.3, 1.0):
        found = ndfd.group_half(values[:4], ndfd.groups_of(group[:4]), share)[0]
        assert (values[:4] >= found).sum() >= share * 4
        assert not any((values[:4] >= v).sum() >= share * 4 for v in values[:4] if v > found)


@pytest.mark.parametrize(
    ("snow", "ice", "feels", "code"),
    [
        (0.49, 0.0, 40.0, Bucket.QUIET),
        (0.5, 0.0, 40.0, Bucket.SNOW_HALF),
        (2.0, 0.0, 40.0, Bucket.SNOW_2),
        (4.0, 0.0, 40.0, Bucket.SNOW_4),
        (6.0, 0.0, 40.0, Bucket.SNOW_6),
        (9.0, 0.0, 40.0, Bucket.SNOW_9),
        (0.0, 0.01, 40.0, Bucket.ICE_TRACE),
        (0.0, 0.10, 40.0, Bucket.ICE_TENTH),
        (0.0, 0.25, 40.0, Bucket.ICE_QUARTER),
        (0.0, 0.0, 10.0, Bucket.FEELS_10),
        (0.0, 0.0, 10.01, Bucket.QUIET),
        (0.0, 0.0, 0.0, Bucket.FEELS_0),
        (0.0, 0.0, -10.0, Bucket.FEELS_MINUS_10),
        (0.0, 0.0, -20.0, Bucket.FEELS_MINUS_20),
        (12.0, 0.10, -30.0, Bucket.ICE_TENTH),
        (12.0, 0.01, -30.0, Bucket.SNOW_9),
        (0.5, 0.01, -30.0, Bucket.SNOW_HALF),
        (0.0, 0.01, -30.0, Bucket.ICE_TRACE),
        (np.nan, 0.30, -30.0, Bucket.ICE_QUARTER),
        (np.nan, 0.10, 40.0, Bucket.ICE_TENTH),
        (np.nan, 0.01, 40.0, Bucket.UNKNOWN),
        (5.0, np.nan, 40.0, Bucket.UNKNOWN),
        (5.0, 0.0, np.nan, Bucket.SNOW_4),
        (0.0, 0.01, np.nan, Bucket.ICE_TRACE),
        (0.0, 0.0, np.nan, Bucket.UNKNOWN),
    ],
)
def test_bucket_bounds_and_priority(snow: float, ice: float, feels: float, code: Bucket) -> None:
    assert ndfd.bucket_codes(np.array([snow]), np.array([ice]), np.array([feels])).tolist() == [
        code
    ]


def test_buckets_agree_with_every_reading_of_an_unknown_value() -> None:
    snow_values = [np.nan, 0.0, 0.5, 2.0, 4.0, 6.0, 9.0]
    ice_values = [np.nan, 0.0, 0.01, 0.1, 0.25]
    feels_values = [np.nan, 40.0, 10.0, 0.0, -10.0, -20.0]
    rank = {code: i for i, code in enumerate(ndfd.PRIORITY)}

    def known(s: float, i: float, f: float) -> int:
        return int(ndfd.bucket_codes(np.array([s]), np.array([i]), np.array([f]))[0])

    combos = list(product(snow_values, ice_values, feels_values))
    found = ndfd.bucket_codes(
        np.array([c[0] for c in combos]),
        np.array([c[1] for c in combos]),
        np.array([c[2] for c in combos]),
    )
    for (s, i, f), code in zip(combos, found.tolist(), strict=True):
        readings = {
            known(a, b, c)
            for a in (snow_values[1:] if np.isnan(s) else [s])
            for b in (ice_values[1:] if np.isnan(i) else [i])
            for c in (feels_values[1:] if np.isnan(f) else [f])
        }
        assert code == (readings.pop() if len(readings) == 1 else Bucket.UNKNOWN), (s, i, f)
        assert code == Bucket.UNKNOWN or code in rank
