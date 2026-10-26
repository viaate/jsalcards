"""The outlook's limits on the serving loop (S7-F F3): its forecast reads have a time limit per
pass, so an AWS feed that is slow or down cannot hold back the next pass; its inputs failing to
build turn it off, never a run dark; its record holds the chances a district's page would show;
the 3-hour rule reaches the published line through the real forecast path; the reader keeps
only runs that can still count. SYNTHETIC alerts, forecasts and T only (:mod:`predict.night`).
"""

import math
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import numpy as np
import pytest

from predict import night, world
from predict.test_outlook_serve import quiet_pass
from predict.test_publish import MemoryHost, make_pass
from snowlight.predict import cli, forecast_history, forecast_live, learn, ndfd
from snowlight.predict import forecast_history as history
from snowlight.predict.forecast_values import Forecasts
from snowlight.predict.outlook import OutlookMode
from snowlight.predict.outlook_live import (
    READ_ATTEMPTS,
    READ_SECONDS,
    RUNS_KEPT,
    Budget,
    ReadForecast,
    as_shown,
    as_shown_percent,
    forecast_reader,
    prune_runs,
)
from snowlight.predict.outlook_record import NOT_TAKEN8, Record
from snowlight.predict.publish import Mode
from snowlight.predict.serve import FLOOR, ServeModel
from snowlight.schemas.predictions import Forecast, OutlookReason, PredictionsFile
from snowlight.sources.nws.alerts import parse_active

REQUEST_SECONDS = 35.0
"""How long each SYNTHETIC request to the failing feed takes."""


class FakeTime:
    """A clock the tests move: each request and each wait between tries."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def failing_fetcher(
    fake: FakeTime, before: Any, attempts: int = READ_ATTEMPTS
) -> tuple[forecast_history.Fetcher, list[str]]:
    """A fetcher whose every request takes :data:`REQUEST_SECONDS` and answers 503."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        fake.now += REQUEST_SECONDS
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return forecast_history.Fetcher(client, attempts=attempts, before=before), asked


def shadow_passes(
    read: ReadForecast, budget: Budget | None, fake: FakeTime, moments: list[datetime]
) -> tuple[list[bytes | None], list[float], cli.Pass]:
    """Shadow passes at ``moments`` over ``read``: the files and each pass's time."""
    host = MemoryHost()
    run = make_pass(host, mode=Mode.ON, directory=world.directory())
    clock = [moments[0]]
    run.now = lambda: clock[0]
    run.alerts = lambda: (night.feed_at(clock[0]), True)
    night.with_outlook(OutlookMode.SHADOW, read)(run)
    run.outlook_budget = budget
    files: list[bytes | None] = []
    spent: list[float] = []
    for moment in moments:
        clock[0] = moment
        start = fake.now
        assert cli.one_pass(run) == 0
        spent.append(fake.now - start)
        files.append(host.files.get(night.KEY))
    return files, spent, run


def test_a_feed_that_is_down_holds_a_shadow_pass_no_longer_than_its_time_limit(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    fake = FakeTime()
    monkeypatch.setattr(forecast_history, "clock", SimpleNamespace(sleep=fake.sleep))
    moments = night.times()[20:23]  # 01:07Z to 02:07Z: samples and the 8 PM chances due
    budget = Budget(clock=fake.monotonic)
    fetcher, asked = failing_fetcher(fake, budget.check)
    files, spent, run = shadow_passes(forecast_reader(fetcher, 0.5), budget, fake, moments)
    off, _run, _host = night.run_night(at=moments)
    assert files == off  # the published file is untouched
    # Each pass waits at most its time limit and one request that was already under way.
    assert max(spent) <= READ_SECONDS + REQUEST_SECONDS + 2.0
    assert len(asked) <= len(moments) * math.ceil(READ_SECONDS / REQUEST_SECONDS + 1)
    # Nothing read is nothing taken: every due sample is skipped, never imputed.
    assert "nothing recorded" not in capsys.readouterr().err
    skipped = run.state.outlook_health["skipped"]
    assert isinstance(skipped, int)
    assert skipped > 0
    # The limit is what cut it: the same reader with no limit takes longer.
    fake.now = 0.0
    loose, _asked = failing_fetcher(fake, None)
    _files, no_limit, _run = shadow_passes(forecast_reader(loose, 0.5), None, fake, moments[:1])
    assert no_limit[0] > max(spent)
    # The same feed, read the way the history reads it (6 tries, a failed day asked again on
    # every read, no limit), would have held each pass for minutes.
    fake.now = 0.0
    slow, _asked = failing_fetcher(fake, None, attempts=6)
    unbounded = forecast_reader(slow, 0.5)
    _files, unlimited, _run = shadow_passes(unbounded, None, fake, moments[:1])
    assert unlimited[0] > 2 * (READ_SECONDS + REQUEST_SECONDS)


def test_a_slow_feed_is_cut_at_the_time_limit_and_the_rest_reads_as_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTime()
    monkeypatch.setattr(forecast_history, "clock", SimpleNamespace(sleep=fake.sleep))
    budget = Budget(seconds=30.0, clock=fake.monotonic)
    budget.start()
    fetcher, asked = failing_fetcher(fake, budget.check)
    with pytest.raises(ndfd.NdfdError):
        fetcher.get("https://example.invalid/a")
    assert len(asked) == 1  # one try (35 s), then the time is up before the second
    with pytest.raises(ndfd.NdfdError, match="are up"):
        fetcher.get("https://example.invalid/b")
    assert len(asked) == 1  # no request once the time is up
    budget.start()  # the next pass has its own time
    budget.check()


def test_the_fetcher_answers_a_200_and_a_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("missing"):
            return httpx.Response(404)
        if request.url.path.endswith("teapot"):
            return httpx.Response(418)
        return httpx.Response(200, content=b"listed")

    fetcher = forecast_history.Fetcher(httpx.Client(transport=httpx.MockTransport(handler)))
    assert fetcher.get("https://example.invalid/ok") == b"listed"
    assert (fetcher.requests, fetcher.bytes) == (1, 6)
    with pytest.raises(ndfd.NotFoundError):
        fetcher.get("https://example.invalid/missing")
    with pytest.raises(ndfd.NdfdError, match="418"):
        fetcher.get("https://example.invalid/teapot")


def test_a_day_that_did_not_list_is_asked_once_a_pass() -> None:
    asked: list[str] = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        raise ndfd.NdfdError("down")

    once = history.Listings(fetch, again=False)
    for _ in range(3):
        assert once.around(date(2026, 1, 7)).error is not None
    assert len(asked) == 2  # D-1 and D, once each
    asked.clear()
    every = history.Listings(fetch)
    for _ in range(3):
        every.around(date(2026, 1, 7))
    assert len(asked) == 6


def test_the_reader_keeps_only_runs_that_can_still_count() -> None:
    now = world.utc("2026-01-07T04:07")
    day = date(2026, 1, 7)

    def values(at: datetime) -> history.RunValues:
        return history.RunValues(ndfd.Run(at, {}, at + timedelta(minutes=10)))

    cache = {
        (now - RUNS_KEPT - timedelta(minutes=1), day): values(now - RUNS_KEPT),
        (now - RUNS_KEPT, day): values(now - RUNS_KEPT),
        (now - timedelta(hours=1), day): values(now - timedelta(hours=1)),
    }
    prune_runs(cache, now)
    assert sorted(cache) == [(now - RUNS_KEPT, day), (now - timedelta(hours=1), day)]
    # Kept: a run 3 hours old still counts at a sample hour up to 15 minutes before the pass.
    assert ndfd.MAX_AGE + timedelta(minutes=15) <= RUNS_KEPT


def test_outlook_inputs_that_fail_to_build_turn_the_outlook_off_never_the_run(
    capsys: Any,
) -> None:
    def broken() -> dict[str, Any]:
        raise FileNotFoundError("data/predict/model-f.json.gz")

    assert cli.outlook_parts(OutlookMode.SHADOW, broken) == {"outlook_mode": OutlookMode.OFF}
    assert "the outlook is off" in capsys.readouterr().err
    assert cli.outlook_parts(OutlookMode.ON, lambda: {"outlook_budget": None}) == {
        "outlook_mode": OutlookMode.ON,
        "outlook_budget": None,
    }
    assert cli.outlook_parts(OutlookMode.OFF, broken) == {"outlook_mode": OutlookMode.OFF}


def test_the_record_holds_the_chance_a_page_shows_where_a_district_said_school_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from snowlight.predict.opens import SaidOpen  # noqa: PLC0415

    day = world.utc("2026-01-07T00:00").date()
    _made, plain = quiet_pass(OutlookMode.SHADOW)
    content = learn.content_key(world.directory())
    before = Record.from_json(plain.state.outlook, content, len(world.DISTRICTS)).days[day]
    assert before.chance_f is not None
    assert int(before.chance_f.values[0]) > round(FLOOR * 100)  # Kansas: 6 to 9 inches

    said = SaidOpen(districts={day: frozenset({0})})
    monkeypatch.setattr(cli, "_said_open", lambda *_args: said)
    made, run = quiet_pass(OutlookMode.SHADOW)
    entry = Record.from_json(run.state.outlook, content, len(world.DISTRICTS)).days[day]
    assert entry.chance_f is not None
    assert entry.chance_v2 is not None
    d = made.days.index(day)
    shown = made.districts[0].days[d]
    assert isinstance(shown, Forecast)
    assert round(shown.p_no_school * 100) == round(FLOOR * 100)
    assert int(entry.chance_v2.values[0]) == round(FLOOR * 100)
    assert int(entry.chance_f.values[0]) == round(FLOOR * 100)
    # Every other district keeps the outlook's own chance.
    assert np.array_equal(entry.chance_f.values[1:4], before.chance_f.values[1:4])


def test_as_shown_floors_only_the_districts_that_said_school_is_on() -> None:
    from snowlight.predict.opens import SaidOpen  # noqa: PLC0415

    days = (date(2026, 1, 6), date(2026, 1, 7))
    said = SaidOpen(districts={days[1]: frozenset({1, 9})})
    p = np.array([[0.2, 0.3], [0.4, 0.5], [0.6, np.nan]])
    shown = as_shown(p, said, days)
    assert shown[1, 1] == FLOOR
    assert shown[0, 1] == pytest.approx(0.3)
    assert shown[1, 0] == pytest.approx(0.4)
    assert p[1, 1] == pytest.approx(0.5)  # a copy
    percent = np.array([[20, 30], [40, 255]])
    found = as_shown_percent(percent, SaidOpen(districts={days[1]: frozenset({0, 1})}), days)
    assert found.tolist() == [[20, 1], [40, NOT_TAKEN8]]


# --- the 3-hour rule through the real forecast path ---------------------------------------------


def aws_like(age: timedelta, inches: float = 2.4) -> ReadForecast:
    """A reader over :func:`~snowlight.predict.forecast_live.forecasts` (the live path), whose
    one SYNTHETIC run is ``age`` old at the pass: ``inches`` of snow in each window period at
    every school, no ice, a mild morning."""

    def read(
        model: ServeModel,
        days: tuple[date, ...],
        now: datetime,
        moment: Any,
        zones: Any,
    ) -> Forecasts:
        schools = forecast_history.deciding_schools(model.directory, model.artifact)
        index = {leaid: i for i, leaid in enumerate(model.directory.district_ids)}
        run = ndfd.Run(now - age, {}, now - age + timedelta(minutes=10))
        count = schools.lat.shape[0]

        def values_of(found: ndfd.Run, day: date) -> history.RunValues:
            values = history.RunValues(found)
            ends = ndfd.window_ends(day)
            values.snow = {end: np.full(count, inches) for end in ends}
            values.ice = {end: np.zeros(count) for end in ends}
            values.feels = {
                ndfd.bus_time(day, zone): np.full(count, 25.0)
                for zone in set(schools.zone_of_district)
            }
            return values

        return forecast_live.forecasts(
            schools,
            index,
            days,
            now,
            lambda _day: [run],
            values_of,
            0.5,
            moment=moment if moment is not None else (lambda _day, _zone: now),
            zones=zones,
        )

    return read


def outlook_lines(made: Any) -> list[OutlookReason]:
    return [
        reason
        for entry in made.districts
        for day in entry.days
        if isinstance(day, Forecast)
        for reason in day.why.reasons
        if isinstance(reason, OutlookReason)
    ]


def test_a_run_2_h_59_min_old_gives_the_line_and_one_3_h_01_min_old_the_identity(
    capsys: Any,
) -> None:
    now = world.utc("2026-01-07T02:07")
    fresh, fresh_run = quiet_pass(OutlookMode.ON, aws_like(timedelta(hours=2, minutes=59)))
    assert outlook_lines(fresh)
    assert fresh.forecast_at == now - timedelta(hours=2, minutes=59)
    assert fresh_run.state.outlook_health["stale"] == 0

    stale, stale_run = quiet_pass(OutlookMode.ON, aws_like(timedelta(hours=3, minutes=1)))
    assert not outlook_lines(stale)
    assert stale.forecast_at is None
    stale_count = stale_run.state.outlook_health["stale"]
    assert isinstance(stale_count, int)
    assert stale_count > 0
    # The identity: every chance is the issued-alerts-only one, as with the outlook off.
    off, _off_run = quiet_pass(OutlookMode.OFF)
    d = off.days.index(now.date())
    for on_entry, off_entry in zip(stale.districts, off.districts, strict=True):
        on_day, off_day = on_entry.days[d], off_entry.days[d]
        assert isinstance(on_day, Forecast)
        assert isinstance(off_day, Forecast)
        assert on_day.why.base == off_day.why.base
        assert on_day.p_no_school == off_day.p_no_school
    assert "issued-alerts-only chance (identity)" in capsys.readouterr().out

    # Under the dark config the same stale run darkens the pass (exit 3).
    serve = world.CONFIG.serve.model_copy(update={"forecast_stale": "dark"})
    config = world.CONFIG.model_copy(update={"serve": serve})
    host = MemoryHost()
    run = make_pass(host, mode=Mode.ON, directory=world.directory(), config=config)
    run.now = lambda: now
    run.alerts = lambda: (parse_active(world.feed_bytes([], now.isoformat())), True)
    night.with_outlook(OutlookMode.ON, aws_like(timedelta(hours=3, minutes=1)))(run)
    assert cli.one_pass(run) == cli.EXIT_DARK
    run.outlook_forecast = aws_like(timedelta(hours=2, minutes=59))
    assert cli.one_pass(run) == 0


def test_on_s_identity_is_the_v3_rates_issued_alerts_only_chance_not_the_v2_rates() -> None:
    """With the outlook on and the forecast stale, a district's chance is the issued-alerts-only
    chance of the rates on serves: the v3 rates (05:00 labels), never the v2 rates' (21:00) of
    the pass with the outlook off. The night's other tests use v3 rates equal to the v2 ones,
    so here they differ: in the v3 rates one district closed on 8 of its 40 quiet days. Whether the
    identity of the lead's Dark.FORECAST decision is this (on's own rates) is the lead's call
    before on (docs/predict.md, Outlook, before on)."""
    v2 = world.model()
    leaid = world.DISTRICTS[1]
    own = world.counts(n_none=40, y_none=8, n_snow=10, y_snow=6)
    v3 = v2.model_copy(
        update={"districts": {**v2.districts, leaid: v2.districts[leaid].model_copy(update=own)}}
    )
    now = world.utc("2026-01-07T02:07")

    def pass_with(mode: OutlookMode, rates: Any) -> PredictionsFile:
        host = MemoryHost()
        run = make_pass(host, mode=Mode.ON, directory=world.directory())
        run.now = lambda: now
        run.alerts = lambda: (parse_active(world.feed_bytes([], now.isoformat())), True)
        night.with_outlook(mode, aws_like(timedelta(hours=3, minutes=1)))(run)
        run.outlook_model = lambda: (v3, night.outlook_model()[1])
        run.model = lambda: rates
        assert cli.one_pass(run) == 0
        return PredictionsFile.from_json_bytes(host.files[night.KEY])

    on = pass_with(OutlookMode.ON, v2)
    v2_off = pass_with(OutlookMode.OFF, v2)
    v3_off = pass_with(OutlookMode.OFF, v3)  # S7-L's pass over the v3 rates
    assert on.forecast_at is None
    assert not outlook_lines(on)
    d = on.days.index(now.date())
    differs = 0
    for on_entry, v2_entry, v3_entry in zip(
        on.districts, v2_off.districts, v3_off.districts, strict=True
    ):
        on_day, v2_day, v3_day = on_entry.days[d], v2_entry.days[d], v3_entry.days[d]
        assert isinstance(on_day, Forecast)
        assert isinstance(v2_day, Forecast)
        assert isinstance(v3_day, Forecast)
        assert on_day.why.base == v3_day.why.base
        assert on_day.p_no_school == v3_day.p_no_school
        differs += on_day.p_no_school != v2_day.p_no_school
    assert differs > 0  # that district and those its counts pool with


def test_on_s_class_issued_is_the_v2_path_s_class_through_a_night_of_products() -> None:
    """On reads each district's class from the product log under rule D2
    (:func:`~snowlight.predict.outlook_serve.district_states`), the v2 path from the alert
    memory (:func:`~snowlight.predict.serve.unit_classes`). Through the SYNTHETIC night's
    watch upgraded to a warning, advisory issued then cancelled, and cold watch replaced by a
    cold advisory, with the outlook's forecast stale (on serves the identity), every pass's
    every district-day has the same base and the same chance as with the outlook off: the two
    paths give the same class. Where they can differ is in docs/predict.md (Outlook, the class
    issued)."""
    off, _run, _host = night.run_night()
    on, _run, _host = night.run_night(
        prepare=night.with_outlook(OutlookMode.ON, night.fake_forecast(stale=True))
    )
    compared = 0
    for off_bytes, on_bytes in zip(off, on, strict=True):
        assert (off_bytes is None) == (on_bytes is None)
        if off_bytes is None or on_bytes is None:
            continue
        off_file = PredictionsFile.from_json_bytes(off_bytes)
        on_file = PredictionsFile.from_json_bytes(on_bytes)
        for off_entry, on_entry in zip(off_file.districts, on_file.districts, strict=True):
            for off_day, on_day in zip(off_entry.days, on_entry.days, strict=True):
                assert type(off_day) is type(on_day)
                if isinstance(off_day, Forecast) and isinstance(on_day, Forecast):
                    assert on_day.why.base == off_day.why.base
                    assert on_day.p_no_school == off_day.p_no_school
                    compared += 1
    assert compared > 100


def test_the_contract_names_the_heads_ups_in_the_pipeline_s_order() -> None:
    """``OutlookReason.now`` and ``like`` carry a heads-up by index; the contract's description
    names each index (the web's words are held to the same list, web/src/data/tests/
    outlook.test.ts), and it is :class:`~snowlight.predict.situations.HeadsUp`'s order."""
    from snowlight.predict.situations import HeadsUp  # noqa: PLC0415

    text = " ".join((OutlookReason.__doc__ or "").split())
    listed = text.split("heads-up 0 none, ", 1)[1].split(")", 1)[0]
    names = [part.split(" ", 1)[1] for part in listed.split(", ")]
    assert names == [item.name.lower().replace("_", " ") for item in HeadsUp][1:]
