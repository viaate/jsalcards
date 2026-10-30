"""GC1's checker (``predict/night_check.py``): a second implementation that never loads the rule
it checks, and that agrees with the pass on a synthetic blend and catches a wrong night. Every
value is made up (``nbm_fake.py``, ``world.py``)."""

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from predict import world
from predict.nbm_fake import Bucket, asnow
from predict.test_publish import NOW, MemoryHost, make_pass
from snowlight.predict import cli, nbm, ndfd, night_check
from snowlight.predict.serve import CHARTER, PRIVATE, VIRTUAL

CYCLE = datetime(2026, 1, 7, 0, tzinfo=UTC)
PIPELINE = Path(__file__).resolve().parents[2]


def test_the_checker_loads_none_of_the_rule_it_checks() -> None:
    code = (
        "import sys; import snowlight.predict.night_check as m; "
        "print(sorted(k for k in sys.modules if k.startswith('snowlight')))"
    )
    found = subprocess.run(  # noqa: S603 - this interpreter, a fixed line
        [sys.executable, "-c", code], cwd=PIPELINE, capture_output=True, text=True, check=True
    )
    loaded = json.loads(found.stdout.replace("'", '"'))
    assert loaded == [
        "snowlight",
        "snowlight.predict",
        "snowlight.predict.ndfd",
        "snowlight.predict.night_check",
    ]
    assert not set(night_check.BANNED) & set(loaded)


def _grid(hour: int) -> np.ndarray:
    """Metres of snow an hour in whole millimetres, as NBM packs them, varying by column and by
    hour (1 to 21 mm)."""
    cols = np.arange(nbm.NX)
    row = ((cols % 7) + 1) * 0.001 * (1 + hour % 3)
    return np.tile(row, (nbm.NY, 1)).reshape(-1)


@pytest.fixture(scope="module")
def bucket() -> Bucket:
    found = Bucket()
    found.add_cycle(
        CYCLE, {h: asnow(CYCLE, h, _grid(h)) for h in range(1, 18)}, CYCLE + timedelta(minutes=51)
    )
    return found


def _get(bucket: Bucket) -> night_check.Get:
    def get(url: str, span: tuple[int, int] | None) -> bytes:
        return bucket.get(url) if span is None else bucket.ranged(url)(*span)

    return get


def _schools() -> night_check.Directory:
    points = world.directory().points
    return night_check.directory_of(
        points.lat_e6 / 1e6,
        points.lon_e6 / 1e6,
        points.district,
        (points.kind & (PRIVATE | CHARTER | VIRTUAL)) == 0,
    )


def _published(bucket: Bucket) -> bytes:
    serve = world.CONFIG.serve.model_copy(update={"chart": "on"})
    host = MemoryHost()
    run = make_pass(
        host,
        directory=world.directory(),
        config=world.CONFIG.model_copy(update={"serve": serve}),
    )
    reader = nbm.NbmReader(bucket.get, bucket.ranged)
    run.night = cli.night_reader(reader.read, timedelta(minutes=150))
    assert cli.one_pass(run) == 0
    return host.files["v1/predictions/latest.json"]


def test_the_checker_agrees_with_the_pass(bucket: Bucket) -> None:
    data = _published(bucket)
    value = json.loads(data)
    assert value["night_at"] == "2026-01-07T00:00:00Z"
    report = night_check.check_file(data, _schools(), get=_get(bucket))
    assert report.nights >= 4
    assert report.failures == []
    assert report.passed
    assert timedelta(minutes=120) == NOW - CYCLE


def _corrupt(data: bytes, change: Any) -> bytes:
    value = json.loads(data)
    for entry in value["districts"]:
        for day in entry["days"]:
            if "night" in day:
                change(day["night"])
                return json.dumps(value).encode()
    raise AssertionError("no night")


@pytest.mark.parametrize(
    ("change", "words"),
    [
        (lambda n: n["least"].__setitem__(0, round(n["least"][0] + 0.1, 1)), "bar 0"),
        (lambda n: n.__setitem__("high", n["low"]), "not in"),
        (lambda n: n["least"].pop(), "bars for"),
        (lambda n: n.__setitem__("heavy", [0, 3]), "span"),
        (lambda n: n.__setitem__("high", n["high"] + 1), "is not the rule's"),
        (lambda n: n.__setitem__("low", max(n["low"] - 1, 0)), "is not the rule's"),
    ],
)
def test_the_checker_catches_a_wrong_night(bucket: Bucket, change: Any, words: str) -> None:
    data = _corrupt(_published(bucket), change)
    report = night_check.check_file(data, _schools(), get=_get(bucket))
    assert not report.passed
    assert any(words in line for line in report.failures), report.failures


def test_the_checker_finds_a_district_that_should_have_charted(bucket: Bucket) -> None:
    value = json.loads(_published(bucket))
    dropped = None
    for entry in value["districts"]:
        for day in entry["days"]:
            if "night" in day and dropped is None:
                del day["night"]
                dropped = entry["district"]
    report = night_check.check_file(json.dumps(value).encode(), _schools(), get=_get(bucket))
    assert any(f"district {dropped} " in line and "no night" in line for line in report.failures)


def test_the_checker_finds_a_cycle_older_than_the_newest_that_counted(bucket: Bucket) -> None:
    value = json.loads(_published(bucket))
    value["night_at"] = "2026-01-06T23:00:00Z"
    report = night_check.check_file(json.dumps(value).encode(), _schools(), get=_get(bucket))
    assert any(
        "the newest that counted" in line and "01-07 00Z" in line for line in report.failures
    )


def test_the_checker_finds_a_message_of_another_hour() -> None:
    bucket = Bucket()
    messages = {h: asnow(CYCLE, h, _grid(h)) for h in range(1, 18)}
    messages[5] = asnow(CYCLE, 6, _grid(5))  # f005 holds the hour to f006
    bucket.add_cycle(CYCLE, messages, CYCLE + timedelta(minutes=51))
    good = Bucket()
    good.add_cycle(
        CYCLE, {h: asnow(CYCLE, h, _grid(h)) for h in range(1, 18)}, CYCLE + timedelta(minutes=51)
    )
    with pytest.raises(ValueError, match="steps"):
        night_check.asnow_hour(_get(bucket), CYCLE, 5)
    assert night_check.asnow_hour(_get(good), CYCLE, 5).metres.shape == (nbm.NX * nbm.NY,)


def test_the_checker_s_rule_is_exact_on_five_and_ten_inches() -> None:
    split = np.full(13, 127 // 13)
    split[: 127 % 13] += 1
    found = night_check.rule(split.reshape(13, 1))
    assert found.least[-1] == 50
    assert (found.low, found.high, found.tenths) == (5, 5, False)
    ten = night_check.rule(np.array([[254 - 30], [30]]))
    assert (ten.low, ten.high) == (10, 10)
    assert night_check.whole_mm(np.array([0.001, 0.013])) is not None
    assert night_check.whole_mm(np.array([0.0015])) is None


def test_the_checker_locates_each_school_at_its_nearest_grid_point() -> None:
    lat, lon = np.array([40.0, 35.5, 44.9]), np.array([-95.0, -80.2, -70.1])
    near = ndfd.cells(lat, lon)
    # eccodes' own coordinates of a message on the NBM grid: the nearest is the pass's cell
    # (from NBM's own first point), at its value's place in the file's alternating rows.
    message = asnow(CYCLE, 4, 0.0)
    import eccodes  # type: ignore[import-untyped]  # noqa: PLC0415

    handle = eccodes.codes_new_from_message(message)
    try:
        grid_lat = np.array(eccodes.codes_get_array(handle, "latitudes"))
        grid_lon = np.array(eccodes.codes_get_array(handle, "longitudes"))
    finally:
        eccodes.codes_release(handle)
    found = night_check.locate(lat, lon, grid_lat, grid_lon)
    want = nbm.cells(lat, lon)
    assert (found == night_check.raw_index(want.row, want.col)).all()
    assert (np.abs(want.col - (near.col + 200)) <= 1).all()


def test_the_checker_re_derives_the_night_day_and_window() -> None:
    from snowlight.schemas.predictions import night_day, night_open, night_window  # noqa: PLC0415

    moment = datetime(2026, 1, 1, tzinfo=UTC)
    for zone in ("America/New_York", "America/Phoenix", "America/Los_Angeles"):
        at = moment
        while at < datetime(2026, 12, 31, tzinfo=UTC):
            day, open_, start, end = night_check.window_of(at, zone)
            assert day == night_day(at, zone)
            assert open_ == night_open(at, zone)
            assert (start, end) == night_window(at, zone)
            at += timedelta(minutes=97)
