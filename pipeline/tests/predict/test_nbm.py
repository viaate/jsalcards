"""The NBM reader (``predict/nbm.py``): the exact ``.idx`` pick, the grid assertion, the odd-row
flip, the (r, c + 200) cell map, the cycle choice and the cache. Every file is synthetic
(``nbm_fake.py``)."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import numpy as np
import pytest

from predict.nbm_fake import Bucket, asnow, core_file
from snowlight.predict import nbm, ndfd

CYCLE = datetime(2026, 1, 27, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)
INCH = 0.0254


def _schools(count: int = 50, seed: int = 26) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    return rng.uniform(26.0, 48.5, count), rng.uniform(-123.5, -68.0, count)


def test_the_idx_pick_takes_the_one_deterministic_line() -> None:
    body, idx = core_file(CYCLE, 6, b"GRIB" + b"x" * 100 + b"7777")
    offset, size = nbm.pick(idx, 6, len(body))
    assert body[offset : offset + size] == b"GRIB" + b"x" * 100 + b"7777"
    assert "ASNOW:surface:5-6 hour acc fcst:prob" in idx.decode()
    assert "ASNOW:surface:0-6 hour acc fcst:" in idx.decode()


@pytest.mark.parametrize("lines", [0, 2])
def test_a_missing_or_doubled_line_is_unreadable(lines: int) -> None:
    body, idx = core_file(CYCLE, 6, b"GRIB7777", lines=lines)
    with pytest.raises(nbm.NbmUnreadableError, match=f"holds {lines} lines"):
        nbm.pick(idx, 6, len(body))


def test_the_last_line_reads_to_the_file_s_end() -> None:
    idx = f"1:0:d={CYCLE:%Y%m%d%H}:ASNOW:surface:2-3 hour acc fcst:\n".encode()
    assert nbm.pick(idx, 3, 600) == (0, 600)
    with pytest.raises(nbm.NbmUnreadableError):
        nbm.pick(idx, 3, None)


def test_decode_flips_the_odd_rows_into_true_order() -> None:
    true = np.zeros(nbm.NX * nbm.NY)
    grid = true.reshape(nbm.NY, nbm.NX)
    grid[1, 0] = 0.05  # west end of an odd row
    grid[2, nbm.NX - 1] = 0.02
    found = nbm.decode(asnow(CYCLE, 4, true), CYCLE, 4)
    assert found.shape == (nbm.NY, nbm.NX)
    assert found[1, 0] == pytest.approx(0.05, abs=1e-5)
    assert found[1, nbm.NX - 1] == pytest.approx(0.0, abs=1e-5)
    assert found[2, nbm.NX - 1] == pytest.approx(0.02, abs=1e-5)


@pytest.mark.parametrize(
    "grid",
    [
        {"Nx": nbm.NX - 1},
        {"Ny": nbm.NY + 1},
        {"latitudeOfFirstGridPointInDegrees": 20.191999},
        {"longitudeOfFirstGridPointInDegrees": 238.445999},
        {"LoVInDegrees": 262.5},
        {"DxInMetres": 3000.0},
        {"scanningMode": 64},
    ],
)
def test_every_grid_key_is_asserted(grid: dict[str, float]) -> None:
    with pytest.raises(ndfd.GridError):
        nbm.decode(asnow(CYCLE, 4, 0.001, grid=grid), CYCLE, 4)


def test_another_parameter_span_cycle_or_hour_is_unreadable() -> None:
    with pytest.raises(nbm.NbmUnreadableError, match="parameter"):
        nbm.decode(asnow(CYCLE, 4, parameter=(0, 1, 8)), CYCLE, 4)
    with pytest.raises(nbm.NbmUnreadableError, match="accumulation"):
        nbm.decode(asnow(CYCLE, 6, span_hours=6), CYCLE, 6)
    with pytest.raises(nbm.NbmUnreadableError, match="accumulation"):
        nbm.decode(asnow(CYCLE, 4, statistic=0), CYCLE, 4)
    with pytest.raises(nbm.NbmUnreadableError, match="cycle"):
        nbm.decode(asnow(CYCLE, 4), CYCLE + HOUR, 3)
    with pytest.raises(nbm.NbmUnreadableError, match="cycle"):
        nbm.decode(asnow(CYCLE, 4), CYCLE, 5)
    with pytest.raises(nbm.NbmUnreadableError, match="one GRIB"):
        nbm.decode(b"GRIB...", CYCLE, 4)


def test_the_cell_map_is_the_nearest_nbm_cell_from_nbm_s_own_first_point() -> None:
    lat, lon = _schools(4000)
    found = nbm.cells(lat, lon)
    assert found.inside.all()
    # Every point's cell centre is nearer to it than any neighbouring cell's, on the projection
    # both grids share, measured from NBM's own first point.
    x, y = ndfd._project(lat, lon)
    x0, y0 = (float(v[0]) for v in ndfd._project(np.array([nbm.LA1_DEG]), np.array([nbm.LO1_DEG])))
    gap = np.hypot(x - (x0 + found.col * ndfd.DX_M), y - (y0 + found.row * ndfd.DX_M))
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            other = np.hypot(
                x - (x0 + (found.col + dc) * ndfd.DX_M), y - (y0 + (found.row + dr) * ndfd.DX_M)
            )
            assert (gap <= other + 1e-6).all()
    assert (gap <= ndfd.DX_M / np.sqrt(2) + 1e-6).all()
    # NDFD's cell shifted 200 columns is a neighbour for a few points near a cell edge (the
    # first points are 200.003 columns apart): the map is never that.
    near = ndfd.cells(lat, lon)
    shifted = (near.row == found.row) & (near.col + 200 == found.col)
    assert 0.99 <= shifted.mean() < 1.0
    assert (np.abs(near.col + 200 - found.col)[near.inside] <= 1).all()


def test_points_off_the_grid_are_off_the_nbm_grid() -> None:
    found = nbm.cells(np.array([61.2, 21.3]), np.array([-149.9, -157.8]))
    assert not found.inside.any()


def _bucket(hours: range, posted: datetime, **kwargs: object) -> Bucket:
    bucket = Bucket()
    messages = {h: asnow(CYCLE, h, 0.01) for h in hours}
    bucket.add_cycle(CYCLE, messages, posted, **kwargs)  # type: ignore[arg-type]
    return bucket


def _hours(first: int, last: int) -> set[datetime]:
    return {CYCLE + (f - 1) * HOUR for f in range(first, last + 1)}


@pytest.mark.parametrize(("minutes", "chosen"), [(150, True), (151, False)])
def test_a_cycle_counts_up_to_150_minutes_old(minutes: int, chosen: bool) -> None:
    bucket = _bucket(range(1, 13), CYCLE + timedelta(minutes=51))
    reader = nbm.NbmReader(bucket.get, bucket.ranged)
    at = CYCLE + timedelta(minutes=minutes)
    found = nbm.choose_cycle(_hours(4, 12), at, timedelta(minutes=150), reader.posted)
    assert found == (CYCLE if chosen else None)


def test_a_cycle_counts_only_once_every_needed_file_is_posted() -> None:
    posted = CYCLE + timedelta(minutes=51)
    bucket = _bucket(range(1, 13), posted, late={9: posted + timedelta(minutes=15)})
    reader = nbm.NbmReader(bucket.get, bucket.ranged)
    at = posted + timedelta(minutes=5)
    assert nbm.choose_cycle(_hours(4, 12), at, timedelta(minutes=150), reader.posted) is None
    # A pass that needs only the hours already posted takes the cycle.
    assert nbm.choose_cycle(_hours(4, 8), at, timedelta(minutes=150), reader.posted) == CYCLE
    later = posted + timedelta(minutes=16)
    assert nbm.choose_cycle(_hours(4, 12), later, timedelta(minutes=150), reader.posted) == CYCLE


def test_the_reader_samples_inches_and_a_second_pass_reads_nothing_new() -> None:
    lat, lon = _schools(5)
    where = nbm.cells(lat, lon)
    true = np.zeros(nbm.NX * nbm.NY).reshape(nbm.NY, nbm.NX)
    true[where.row, where.col] = np.arange(1, 6) * INCH / 10  # 0.1 to 0.5 in
    bucket = Bucket()
    bucket.add_cycle(
        CYCLE,
        {h: asnow(CYCLE, h, true.reshape(-1)) for h in range(1, 13)},
        CYCLE + 51 * timedelta(minutes=1),
    )
    reader = nbm.NbmReader(bucket.get, bucket.ranged)
    at = CYCLE + timedelta(minutes=67)
    hours = _hours(3, 12)
    cycle, found = reader.read(lat, lon, hours, at, timedelta(minutes=150))
    assert cycle == CYCLE
    assert sorted(found) == sorted(hours)
    for values in found.values():
        assert values == pytest.approx([0.1, 0.2, 0.3, 0.4, 0.5], abs=1e-3)
    # The 01Z cycle is listed first (not yet posted), then 00Z once.
    listings = [url for url in bucket.requests if "list-type" in url]
    assert [url.split("prefix=blend.20260127/")[1][:2] for url in listings] == ["01", "00"]
    reads = [url for url in bucket.requests if "[" in url]
    assert len(reads) == len(hours)
    assert sum(1 for url in bucket.requests if url.endswith(".idx")) == len(hours)
    before = [url for url in bucket.requests if "list-type" not in url]
    again = reader.read(lat, lon, hours, at + timedelta(minutes=30), timedelta(minutes=150))
    assert again[0] == CYCLE
    # The :37 pass on the same cycle reads no message again; it lists afresh the cycles it
    # weighs (the newer one, then this one), so a file posted anew would be seen.
    assert [url for url in bucket.requests if "list-type" not in url] == before
    relisted = [url for url in bucket.requests if "list-type" in url][2:]
    assert [url.split("prefix=blend.20260127/")[1][:2] for url in relisted] == ["01", "00"]


def test_a_file_posted_anew_under_the_same_cycle_is_read_anew() -> None:
    """Critic r2 S2: NOAA reposts a corrected core file of a cycle the reader holds (a new
    LastModified and size): the next pass reads it, never the old file's values."""
    lat, lon = _schools(3)
    where = nbm.cells(lat, lon)
    grid = np.zeros(nbm.NX * nbm.NY).reshape(nbm.NY, nbm.NX)
    grid[where.row, where.col] = INCH / 10  # 0.1 in
    bucket = Bucket()
    bucket.add_cycle(
        CYCLE, {h: asnow(CYCLE, h, grid.reshape(-1)) for h in range(1, 13)}, CYCLE + 51 * MINUTE
    )
    reader = nbm.NbmReader(bucket.get, bucket.ranged)
    at = CYCLE + timedelta(minutes=67)
    hours = _hours(3, 12)
    _cycle, first = reader.read(lat, lon, hours, at, timedelta(minutes=150))
    assert all(values == pytest.approx([0.1] * 3, abs=1e-3) for values in first.values())
    # f005 posted again at +80 min (a new LastModified) with 0.3 in.
    fixed = grid.copy()
    fixed[where.row, where.col] = 3 * INCH / 10
    again = Bucket()
    again.add_cycle(CYCLE, {5: asnow(CYCLE, 5, fixed.reshape(-1))}, CYCLE + 80 * MINUTE)
    bucket.files.update(again.files)
    reads = len([url for url in bucket.requests if "[" in url])
    _cycle, second = reader.read(lat, lon, hours, at + 30 * MINUTE, timedelta(minutes=150))
    moved = CYCLE + timedelta(hours=4)  # the hour f005 holds
    assert second[moved] == pytest.approx([0.3] * 3, abs=1e-3)
    assert all(
        values == pytest.approx([0.1] * 3, abs=1e-3)
        for hour, values in second.items()
        if hour != moved
    )
    # Only the file posted anew is read again.
    assert len([url for url in bucket.requests if "[" in url]) == reads + 1


def test_no_cycle_is_stale_and_a_failed_read_is_unreadable() -> None:
    lat, lon = _schools(3)
    bucket = Bucket()
    reader = nbm.NbmReader(bucket.get, bucket.ranged)
    with pytest.raises(nbm.NbmStaleError):
        reader.read(lat, lon, _hours(3, 5), CYCLE + HOUR, timedelta(minutes=150))
    bucket = _bucket(range(1, 6), CYCLE + timedelta(minutes=40))
    bucket.fail = lambda url: url.endswith(".co.grib2")
    reader = nbm.NbmReader(bucket.get, bucket.ranged)
    with pytest.raises(nbm.NbmUnreadableError):
        reader.read(lat, lon, _hours(3, 5), CYCLE + HOUR, timedelta(minutes=150))
    bucket = _bucket(range(1, 6), CYCLE + timedelta(minutes=40))
    bucket.fail = lambda url: "list-type" in url
    reader = nbm.NbmReader(bucket.get, bucket.ranged)
    with pytest.raises(nbm.NbmUnreadableError):
        reader.read(lat, lon, _hours(3, 5), CYCLE + HOUR, timedelta(minutes=150))


def test_a_message_off_the_grid_is_a_grid_error() -> None:
    lat, lon = _schools(3)
    bucket = Bucket()
    bad = asnow(CYCLE, 3, 0.001, grid={"longitudeOfFirstGridPointInDegrees": 238.445999})
    bucket.add_cycle(CYCLE, {3: bad}, CYCLE + timedelta(minutes=40))
    reader = nbm.NbmReader(bucket.get, bucket.ranged)
    with pytest.raises(ndfd.GridError):
        reader.read(lat, lon, _hours(3, 3), CYCLE + HOUR, timedelta(minutes=150))


def test_the_listing_asks_for_the_needed_hours_only() -> None:
    url = nbm.listing_url(CYCLE, 4, 12)
    assert "prefix=blend.20260127/00/core/blend.t00z.core.f&" in url
    assert "start-after=blend.20260127/00/core/blend.t00z.core.f003&" in url
    assert url.endswith("max-keys=108")


def test_a_frozen_listing_hides_every_cycle_within_the_cap() -> None:
    from predict import world  # noqa: PLC0415
    from snowlight.predict import cli  # noqa: PLC0415

    lat, lon = _schools(3)
    bucket = _bucket(range(1, 13), CYCLE + timedelta(minutes=51))
    reader = nbm.NbmReader(bucket.get, bucket.ranged)
    at = CYCLE + timedelta(minutes=67)
    assert reader.read(lat, lon, _hours(3, 5), at, timedelta(minutes=150))[0] == CYCLE
    serve = world.CONFIG.serve.model_copy(
        update={"chart": "shadow", "chart_fault": "frozen_listing"}
    )
    frozen = cli.frozen_read(nbm.NbmReader(bucket.get, bucket.ranged), serve)
    with pytest.raises(nbm.NbmStaleError):
        frozen(lat, lon, _hours(3, 5), at, timedelta(minutes=150))
    assert cli.frozen_read(reader, world.CONFIG.serve) == reader.read


# --- critic r1: the blend's HTTP reads are budgeted, and never take a whole core file ---


def _http(handler: Any, clock: list[float] | None = None) -> nbm.NbmHttp:
    now = clock if clock is not None else [0.0]
    budget = nbm.Budget(clock=lambda: now[0])
    budget.start()

    def sleep(seconds: float) -> None:
        now[0] += seconds

    return nbm.NbmHttp(httpx.Client(transport=httpx.MockTransport(handler)), budget, sleep=sleep)


def test_a_whole_file_for_a_range_read_is_refused_unread() -> None:
    read: list[int] = []

    def body() -> Iterator[bytes]:
        read.append(1)
        yield b"x" * 1000

    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Stream(body))

    with pytest.raises(nbm.NbmUnreadableError, match="whole file"):
        _http(handle).ranged(nbm.core_url(CYCLE, 4))(0, 10)
    assert read == []


class _Stream(httpx.SyncByteStream):
    def __init__(self, make: Callable[[], Iterator[bytes]]) -> None:
        self._make = make

    def __iter__(self) -> Iterator[bytes]:
        yield from self._make()


def test_a_range_read_never_takes_more_than_it_asked() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            206, content=b"y" * 50, headers={"Content-Range": "bytes 0-49/100000000"}
        )

    with pytest.raises(nbm.NbmUnreadableError, match="more than"):
        _http(handle).ranged(nbm.core_url(CYCLE, 4))(0, 10)


def test_a_failing_host_is_tried_twice_and_a_spent_budget_stops_every_read() -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(503)

    clock = [0.0]
    http = _http(handle, clock)
    with pytest.raises(nbm.NbmUnreadableError, match="503"):
        http.get(nbm.listing_url(CYCLE, 1, 12))
    assert len(calls) == nbm.READ_ATTEMPTS
    clock[0] += nbm.READ_SECONDS
    with pytest.raises(nbm.NbmSlowError):
        http.get(nbm.listing_url(CYCLE, 1, 12))
    assert len(calls) == nbm.READ_ATTEMPTS
    assert nbm.NbmSlowError("x").code == "nbm_slow"


def test_the_budget_stops_a_body_that_trickles() -> None:
    clock = [0.0]

    def chunks() -> Iterator[bytes]:
        for _ in range(100):
            clock[0] += 5.0
            yield b"z" * 10

    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Stream(chunks))

    with pytest.raises(nbm.NbmSlowError):
        _http(handle, clock).get(nbm.listing_url(CYCLE, 1, 12))
    assert clock[0] <= nbm.READ_SECONDS + 5.0
