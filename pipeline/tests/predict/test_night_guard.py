"""The night chart's guard (design spec chart-data r3, 5.6; critic 3 S7): a chart failure never
touches a chance. Every case publishes a file whose chances, why lines and bases are byte for
byte the file with ``serve.chart: off``, and whose health names the check. Also the fetch gate,
the coded withheld reasons, shadow and on. Every amount and alert is made up (``world.py``)."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import numpy as np
import numpy.typing as npt
import pytest
from pydantic import ValidationError

from predict import world
from predict.test_publish import NOW, MemoryHost, feed, make_pass
from snowlight.predict import cli, nbm, ndfd, night_chart, night_serve, serve
from snowlight.predict.config import PredictConfig
from snowlight.predict.night_chart import NightInputs
from snowlight.predict.night_serve import (
    Candidate,
    Nights,
    NightValues,
    Withheld,
    guarded_nights,
    night_stage,
)
from snowlight.predict.situations import WeatherClass
from snowlight.schemas.predictions import NightSnow, PredictionsFile

KEY = "v1/predictions/latest.json"
CYCLE = datetime(2026, 1, 7, 0, tzinfo=UTC)  # 120 min before the pass
DAY = date(2026, 1, 7)

type Floats = npt.NDArray[np.float64]
type BlendRead = Callable[
    [Floats, Floats, set[datetime], datetime, timedelta], tuple[datetime, dict[datetime, Floats]]
]


def _config(chart: str = "on", fault: str = "none") -> PredictConfig:
    serve = world.CONFIG.serve.model_copy(update={"chart": chart, "chart_fault": fault})
    return world.CONFIG.model_copy(update={"serve": serve})


def steady(rate: float = 0.4, cycle: datetime = CYCLE) -> BlendRead:
    """A blend with ``rate`` inches every hour at every school (none in Utah)."""

    def read(
        lat: Floats, lon: Floats, hours: set[datetime], at: datetime, max_age: timedelta
    ) -> tuple[datetime, dict[datetime, Floats]]:
        del lat, at, max_age
        amount = np.where(lon < -100, 0.0, rate)
        return cycle, {hour: amount.astype(np.float64) for hour in hours}

    return read


def _pass(
    chart: str = "on",
    *,
    read: BlendRead | None = None,
    fault: str = "none",
    night: Callable[..., NightValues] | None = None,
    now: datetime = NOW,
) -> tuple[cli.Pass, MemoryHost, list[frozenset[date]]]:
    host = MemoryHost()
    run = make_pass(host, directory=world.directory(), config=_config(chart, fault), now=now)
    calls: list[frozenset[date]] = []
    reader = cli.night_reader(read or steady(), timedelta(minutes=150))

    def counted(model: Any, days: frozenset[date], at: datetime) -> NightValues:
        calls.append(days)
        return (night or reader)(model, days, at)

    run.night = counted
    return run, host, calls


def _published(chart: str = "on", **kwargs: Any) -> tuple[bytes, cli.Pass, list[frozenset[date]]]:
    run, host, calls = _pass(chart, **kwargs)
    assert cli.one_pass(run) == 0
    return host.files[KEY], run, calls


def _without_nights(data: bytes) -> Any:
    value = json.loads(data)
    value.pop("night_at", None)
    for entry in value["districts"]:
        for day in entry["days"]:
            day.pop("night", None)
    return value


OFF: dict[str, bytes] = {}


def _off() -> bytes:
    if "file" not in OFF:
        OFF["file"], _run, calls = _published("off")
        assert calls == []
    return OFF["file"]


def _nights(data: bytes) -> dict[int, dict[str, Any]]:
    value = json.loads(data)
    return {
        entry["district"]: day["night"]
        for entry in value["districts"]
        for day in entry["days"]
        if "night" in day
    }


def test_on_publishes_the_nights_and_every_chance_as_off() -> None:
    data, run, calls = _published("on")
    assert calls == [frozenset({DAY})]
    assert _without_nights(data) == json.loads(_off())
    nights = _nights(data)
    # Four districts in Kansas City (10 hours, 4 in), none in Utah (no snow).
    assert sorted(nights) == [0, 1, 2, 3]
    assert nights[1]["least"] == [round(0.4 * (i + 1), 1) for i in range(10)]
    assert (nights[1]["low"], nights[1]["high"]) == (4.0, 4.0)
    assert json.loads(data)["night_at"] == "2026-01-07T00:00:00Z"
    assert run.state.chart_health["nights"] == 4
    assert run.state.chart_health["withheld"] == []


def test_shadow_publishes_the_off_file_and_reports_the_nights(capsys: Any) -> None:
    data, run, calls = _published("shadow")
    assert calls == [frozenset({DAY})]
    assert data == _off()
    out = capsys.readouterr().out
    assert "chart (shadow): 4 nights from the 00Z cycle, 120 min old" in out
    assert run.state.chart_health["nights"] == 4


def test_off_reads_nothing_and_keeps_the_state_as_before() -> None:
    run, _host, calls = _pass("off")
    assert cli.one_pass(run) == 0
    assert calls == []
    assert "chart_health" not in run.state.as_json()


def test_the_gate_reads_nothing_for_a_friday_night() -> None:
    # 8 PM Friday in Kansas City: the night's day is Saturday, not a school day.
    friday = datetime(2026, 1, 10, 2, tzinfo=UTC)
    run, _host, calls = _pass("on", now=friday)
    run.alerts = lambda: (feed(updated="2026-01-10T01:55:00+00:00"), True)
    assert cli.one_pass(run) == 0
    assert calls == []


def test_the_gate_reads_nothing_on_a_calm_school_night() -> None:
    run, host, calls = _pass("on")
    run.alerts = lambda: (feed(alerts=0), True)
    assert cli.one_pass(run) == 0
    assert calls == []
    assert b'"night' not in host.files[KEY]


def test_one_advisory_anywhere_opens_the_gate() -> None:
    from snowlight.sources.nws.alerts import parse_active  # noqa: PLC0415

    advisory = world.feature(
        "/O.NEW.KSLC.WW.Y.0001.260107T0600Z-260108T0000Z/",
        ("UTZ105",),
        sent="2026-01-06T20:00:00+00:00",
        onset="2026-01-07T06:00:00+00:00",
        ends="2026-01-08T00:00:00+00:00",
        event="Winter Weather Advisory",
    )
    run, host, calls = _pass("on")
    run.alerts = lambda: (
        parse_active(world.feed_bytes([advisory], "2026-01-07T01:55:00+00:00")),
        True,
    )
    assert cli.one_pass(run) == 0
    assert calls == [frozenset({DAY})]
    # The gate is national: the Kansas City districts chart on Utah's advisory.
    assert sorted(_nights(host.files[KEY])) == [0, 1, 2, 3]


def _withheld(run: cli.Pass) -> list[list[Any]]:
    found: list[list[Any]] = run.state.chart_health["withheld"]  # type: ignore[assignment]
    return found


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (nbm.NbmStaleError("frozen"), "nbm_stale"),
        (nbm.NbmUnreadableError("cut"), "nbm_unreadable"),
        (ndfd.GridError("off"), "grid"),
        (IndexError("bug"), "invalid (IndexError)"),
    ],
)
def test_a_failed_read_withholds_the_chart_and_only_the_chart(
    error: Exception, code: str, capsys: Any
) -> None:
    def broken(*_args: Any) -> tuple[datetime, dict[datetime, Floats]]:
        raise error

    data, run, _calls = _published("on", read=broken)
    assert data == _off()
    assert _withheld(run) == [[code, 1]]
    assert f"chart: withheld, {code}" in capsys.readouterr().out


def test_a_raising_builder_for_one_district_drops_that_night_only(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    real = night_chart.night
    seen: list[int] = []

    def flaky(inputs: NightInputs, min_inches: float = 1.0) -> NightSnow | None:
        seen.append(1)
        if len(seen) == 1:
            raise RuntimeError("a bug")
        return real(inputs, min_inches)

    monkeypatch.setattr(night_chart, "night", flaky)
    data, run, _calls = _published("on")
    assert sorted(_nights(data)) == [1, 2, 3]
    assert _without_nights(data) == json.loads(_off())
    assert _withheld(run) == [["invalid (RuntimeError)", 1]]
    assert "chart: withheld, invalid (RuntimeError)" in capsys.readouterr().out


def test_a_builder_raising_for_every_district_gives_the_off_file(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    def broken(_inputs: NightInputs, _min: float = 1.0) -> NightSnow | None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(night_chart, "night", broken)
    data, run, _calls = _published("on")
    assert data == _off()
    assert _withheld(run) == [["invalid (RuntimeError)", 5]]
    assert "invalid (RuntimeError) x5" in capsys.readouterr().out


def test_the_raise_fault_in_shadow() -> None:
    data, run, _calls = _published("shadow", fault="raise")
    assert data == _off()
    assert _withheld(run) == [["invalid (RuntimeError)", 5]]


def test_the_fault_hooks_only_in_shadow() -> None:
    serve = world.CONFIG.serve.model_dump() | {"chart": "on", "chart_fault": "raise"}
    with pytest.raises(ValidationError, match="chart_fault"):
        type(world.CONFIG.serve).model_validate(serve)


def _bad(**fields: Any) -> NightSnow:
    base: dict[str, Any] = {
        "least": tuple(round(0.4 * (i + 1), 1) for i in range(10)),
        "low": 4.0,
        "high": 4.0,
        "heavy": None,
    }
    return NightSnow.model_construct(**(base | fields))


@pytest.mark.parametrize(
    ("night", "check"),
    [
        (_bad(least=(*(round(0.4 * (i + 1), 1) for i in range(8)), 4.0)), "bars"),
        (_bad(least=(0.4,) * 9 + (100.0,), high=4.0), "least_bound"),
        (_bad(least=(0.4,) * 8 + (0.6, 0.5), low=0.0, high=2.0), "least_falls"),
        (_bad(low=4.5), "range"),
        (_bad(heavy=(0, 2)), "heavy"),
    ],
)
def test_each_failed_night_check_drops_that_night_only(
    night: NightSnow, check: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = night_chart.night
    seen: list[int] = []

    def one_bad(inputs: NightInputs, min_inches: float = 1.0) -> NightSnow | None:
        seen.append(1)
        return night if len(seen) == 2 else real(inputs, min_inches)

    monkeypatch.setattr(night_chart, "night", one_bad)
    data, run, _calls = _published("on")
    assert sorted(_nights(data)) == [0, 2, 3]
    assert _without_nights(data) == json.loads(_off())
    assert _withheld(run) == [[f"invalid ({check})", 1]]


def test_a_night_for_another_day_fails_window() -> None:
    zone = "America/Chicago"
    generated = NOW
    start, end = datetime(2026, 1, 7, 3, tzinfo=UTC), datetime(2026, 1, 7, 13, tzinfo=UTC)
    inputs = NightInputs(DAY + timedelta(days=1), zone, start, end, np.full((10, 2), 0.4))
    values = NightValues(CYCLE, (Candidate(DAY + timedelta(days=1), 0, inputs),))
    nights, withheld = guarded_nights(values, generated)
    assert not nights
    assert withheld == Withheld((("invalid (window)", 1),))


def _inject(nights: Nights) -> Callable[..., tuple[Nights, Withheld, int]]:
    def stage(*_args: Any) -> tuple[Nights, Withheld, int]:
        return nights, Withheld(), 0

    return stage


def _good() -> NightSnow:
    return NightSnow(least=tuple(round(0.4 * (i + 1), 1) for i in range(10)), low=4.0, high=4.0)


@pytest.mark.parametrize(
    ("nights", "check"),
    [
        (Nights({(DAY, 1): _good(), (DAY - timedelta(days=1), 1): _good()}, CYCLE), "one_day"),
        (Nights({(DAY, 1): _good()}, None), "night_at_pair"),
        (Nights({(DAY, 1): _good()}, NOW - timedelta(minutes=151)), "night_at_age"),
        (Nights({(DAY, 1): _good()}, NOW + timedelta(minutes=1)), "night_at_age"),
    ],
)
def test_a_file_level_failure_rebuilds_the_file_with_no_nights(
    nights: Nights, check: str, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(cli, "_nights", _inject(nights))
    data, run, _calls = _published("on")
    assert data == _off()
    assert _withheld(run) == [[f"invalid ({check})", 1]]
    assert f"chart: withheld, invalid ({check})" in capsys.readouterr().out


def test_the_stale_night_at_fault_in_shadow() -> None:
    data, run, _calls = _published("shadow", fault="stale_night_at")
    assert data == _off()
    assert _withheld(run) == [["invalid (night_at_age)", 1]]


def test_a_night_on_a_private_outlook_rebuilds(monkeypatch: pytest.MonkeyPatch) -> None:
    real = serve.forecast_file

    def outlook_night(*args: Any, **kwargs: Any) -> PredictionsFile:
        made = real(*args, **kwargs)
        if not kwargs["nights"]:
            return made
        value = json.loads(made.to_json_bytes())
        value["outlooks"][0]["night"] = _good().to_json_value()
        return PredictionsFile.from_json_bytes(json.dumps(value).encode())

    monkeypatch.setattr(cli, "forecast_file", outlook_night)
    data, run, _calls = _published("on")
    assert data == _off()
    assert _withheld(run) == [["invalid (outlook)", 1]]


def test_any_other_failure_with_nights_rebuilds_too(monkeypatch: pytest.MonkeyPatch) -> None:
    real = serve.forecast_file

    def keyed(*args: Any, **kwargs: Any) -> PredictionsFile:
        if kwargs["nights"]:
            raise KeyError("a wrong Nights shape")
        return real(*args, **kwargs)

    monkeypatch.setattr(cli, "forecast_file", keyed)
    data, run, _calls = _published("on")
    assert data == _off()
    assert _withheld(run) == [["invalid (KeyError)", 1]]


def test_a_rebuild_that_fails_too_raises_as_today(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> PredictionsFile:
        raise ValueError("a validator broken in the fixture")

    monkeypatch.setattr(cli, "forecast_file", broken)
    for chart in ("off", "on"):
        run, _host, _calls = _pass(chart)
        with pytest.raises(ValueError, match="broken in the fixture"):
            cli.one_pass(run)


def test_the_stage_never_raises() -> None:
    def read(_days: frozenset[date]) -> NightValues:
        raise MemoryError

    nights, withheld = night_stage(read, frozenset({DAY}), NOW)
    assert nights is night_serve.NO_NIGHTS
    assert withheld.line() == "chart: withheld, invalid (MemoryError)"


# --- critic r1: the chart can never hold a pass back, and shadow runs after the chance is out ---


class _Clock:
    """A virtual clock: requests and waits move it, nothing sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _bucket_transport(clock: _Clock, behave: Callable[[httpx.Request, int], float | None]) -> Any:
    """The synthetic NBM bucket (``nbm_fake``) over HTTP. ``behave(request, n)``: how long the
    n-th request takes (the clock moves by it), or None to time out after 10 s."""
    from predict.nbm_fake import Bucket, asnow  # noqa: PLC0415

    bucket = Bucket()
    grid = np.full(nbm.NX * nbm.NY, 0.004)  # 4 mm an hour
    bucket.add_cycle(
        CYCLE, {h: asnow(CYCLE, h, grid) for h in range(1, 18)}, CYCLE + timedelta(minutes=51)
    )
    seen = [0]

    def handle(request: httpx.Request) -> httpx.Response:
        seen[0] += 1
        took = behave(request, seen[0])
        if took is None:
            clock.now += 10.0
            raise httpx.ReadTimeout("timed out", request=request)
        clock.now += took
        url = str(request.url)
        span = request.headers.get("Range")
        if span is None:
            return httpx.Response(200, content=bucket.get(url))
        key = url.removeprefix(f"{nbm.BUCKET_ROOT}/")
        first, last = (int(v) for v in span.removeprefix("bytes=").split("-"))
        body = bucket.files[key][0]
        part = body[first : last + 1]
        said = f"bytes {first}-{first + len(part) - 1}/{len(body)}"
        return httpx.Response(206, content=part, headers={"Content-Range": said})

    return httpx.MockTransport(handle), seen


def _blend_pass(
    chart: str, behave: Callable[[httpx.Request, int], float | None]
) -> tuple[cli.Pass, MemoryHost, _Clock, list[int], list[bool]]:
    clock = _Clock()
    transport, seen = _bucket_transport(clock, behave)
    host = MemoryHost()
    run = make_pass(host, directory=world.directory(), config=_config(chart))
    budget = nbm.Budget(clock=clock)
    reader = cli.blend_night(
        httpx.Client(transport=transport), run.config.serve, budget, sleep=clock.sleep
    )
    published: list[bool] = []

    def read(model: Any, days: frozenset[date], at: datetime) -> NightValues:
        published.append(KEY in host.files)
        return reader(model, days, at)

    run.night = reader if chart == "on" else read
    return run, host, clock, seen, published


def test_a_healthy_bucket_charts_through_the_budgeted_reader() -> None:
    run, host, clock, seen, _published_first = _blend_pass("on", lambda _r, _n: 0.5)
    assert cli.one_pass(run) == 0
    assert sorted(_nights(host.files[KEY])) == [0, 1, 2, 3, 4]  # 4 mm an hour everywhere
    assert seen[0] > 0
    assert clock.now < nbm.READ_SECONDS


def test_a_hanging_bucket_holds_the_pass_back_at_most_two_tries() -> None:
    run, host, clock, seen, _first = _blend_pass("on", lambda _r, _n: None)
    assert cli.one_pass(run) == 0
    assert host.files[KEY] == _off()
    assert _withheld(run) == [["nbm_unreadable", 1]]
    assert seen[0] == nbm.READ_ATTEMPTS  # one listing, tried twice
    assert clock.now <= 2 * 10.0 + 1.0


def test_a_limping_bucket_stops_at_the_budget_with_the_chance_unchanged() -> None:
    # Every request first times out (10 s), then answers slowly (9 s): about 20 s a request,
    # some 30 requests a cold pass. The stage stops at the budget, and the pass goes on.
    run, host, clock, seen, _first = _blend_pass("on", lambda _r, n: None if n % 2 == 1 else 9.0)
    assert cli.one_pass(run) == 0
    assert host.files[KEY] == _off()
    assert _withheld(run) == [["nbm_slow", 1]]
    assert nbm.READ_SECONDS <= clock.now <= nbm.READ_SECONDS + 10.0 + 9.0
    assert seen[0] < 10


def test_shadow_reads_the_blend_only_after_the_file_is_published() -> None:
    run, host, _clock, _seen, published = _blend_pass("shadow", lambda _r, _n: 0.5)
    assert cli.one_pass(run) == 0
    assert published == [True]
    assert host.files[KEY] == _off()
    assert run.state.chart_health["nights"] == 5


def test_a_bug_in_the_shadow_report_never_touches_the_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    def broken(*_args: Any) -> None:
        raise ZeroDivisionError

    monkeypatch.setattr(cli, "_say_chart", broken)
    data, _run, _calls = _published("shadow")
    assert data == _off()
    assert "chart (shadow): withheld, invalid (ZeroDivisionError)" in capsys.readouterr().err


def test_a_bug_in_the_chart_s_health_never_touches_the_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    def broken(_self: Any) -> None:
        raise KeyError("line")

    monkeypatch.setattr(Withheld, "line", broken)
    for chart in ("on", "shadow"):
        run, host, _calls = _pass(chart)
        assert cli.one_pass(run) == 0
        assert _without_nights(host.files[KEY]) == json.loads(_off())
    assert "withheld, invalid (KeyError)" in capsys.readouterr().err


def test_a_file_that_fails_the_strict_parse_is_rebuilt_without_nights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strict = PredictionsFile.from_json_bytes

    def stricter(data: bytes) -> PredictionsFile:
        if b'"night"' in data:
            raise ValueError("night: strict_only")
        return strict(data)

    monkeypatch.setattr(PredictionsFile, "from_json_bytes", stricter)
    data, run, _calls = _published("on")
    assert data == _off()
    assert _withheld(run) == [["invalid (strict_only)", 1]]


def test_shadow_says_would_publish_for_a_file_it_never_publishes(capsys: Any) -> None:
    calls: list[str] = []

    def make(fit: serve.Fit, nights: Nights) -> PredictionsFile:
        del nights
        calls.append(fit.name)
        return PredictionsFile.from_json_bytes(_off())

    settings = world.CONFIG.serve.model_copy(update={"night_max_raw_bytes": 10})
    nights = Nights({(DAY, 0): NightSnow(least=(1.0,), low=1.0, high=1.0)}, CYCLE)
    cli.fitted(make, settings, nights, shadow=True)
    out = capsys.readouterr()
    assert "would publish it with no" in out.out
    assert "published it with no" not in out.err


def test_an_advisory_off_the_blend_s_grid_never_opens_the_gate() -> None:
    zones = ["America/Anchorage", "America/New_York"]
    days = [DAY, DAY + timedelta(days=1)]
    classes = np.zeros((2, 2), dtype=np.int64)
    classes[0, :] = int(WeatherClass.ADVISORY)
    at = datetime(2026, 1, 7, 2, 7, tzinfo=UTC)  # 9:07 PM Eastern
    assert night_serve.gate_days(zones, days, classes, at) == frozenset({DAY})
    charting = np.array([False, True])
    assert night_serve.gate_days(zones, days, classes, at, charting) == frozenset()
    classes[1, 0] = int(WeatherClass.ADVISORY)
    assert night_serve.gate_days(zones, days, classes, at, charting) == frozenset({DAY})


def test_the_reader_says_which_districts_can_chart() -> None:
    run = make_pass(directory=world.directory())
    model = run.serve_model(world.directory())
    reader = cli.night_reader(steady(), timedelta(minutes=150))
    charting = reader.charting(model)
    assert charting.shape == (len(model.directory.district_ids),)
    assert charting.all()  # every world school is in the contiguous states
