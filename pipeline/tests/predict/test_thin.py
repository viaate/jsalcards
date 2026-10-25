"""The thin flag (spec addendum 2026-10-24 e, E3b): a base that names the nation because the
district's region holds too few recorded days of the weather says so, additively; its chance
and sentence stay the nation's record. Synthetic world only."""

import json
from datetime import UTC, date, datetime, time

import pytest
from pydantic import ValidationError

from predict import world
from predict.test_serve import index, model, storm
from snowlight.predict import serve
from snowlight.predict.alerts_live import live_events
from snowlight.predict.pool import SCOPES
from snowlight.predict.serve import district_classes, forecast_file
from snowlight.predict.share import points_of, says_true
from snowlight.predict.situations import SITUATIONS, Situation, WeatherClass, Window
from snowlight.predict.why import base_for
from snowlight.schemas.predictions import Forecast, PooledBase, PredictionsFile
from snowlight.sources.nws.alerts import parse_active

WINDOW = Window(time(18), time(9), 21)
SHARE = 0.5
UTAH = world.DISTRICTS.index("4900005")
KANSAS = world.DISTRICTS.index("2000004")
MISSOURI = tuple(i for i, leaid in enumerate(world.DISTRICTS) if leaid.startswith("29"))
"""Missouri's region holds the world's recorded days; Kansas's (the South) and Utah's none."""
SNOW = Situation(WeatherClass.SNOW_WARNING)
NONE = Situation(WeatherClass.NONE)
ADVISORY = Situation(WeatherClass.ADVISORY)
ADVISORY_K = SITUATIONS.index(ADVISORY)


def _pass(*, warned: bool) -> PredictionsFile:
    built = model()
    now = world.utc("2026-01-07T02:00:00")
    days = (date(2026, 1, 6), date(2026, 1, 7))
    events = storm() if warned else []
    classes = district_classes(built, events, index(), days, now, WINDOW, SHARE)
    return forecast_file(built, classes, days, now, closed_on=lambda _day: None, last=None)


def test_a_district_whose_region_holds_no_record_says_so() -> None:
    made = _pass(warned=False)
    utah = made.districts[UTAH].days[1]
    assert isinstance(utah, Forecast)
    base = utah.why.base
    assert isinstance(base, PooledBase)
    assert base.scope == "nation"
    assert base.thin
    # Its chance is still the nation's record, and the sentence is true of it.
    assert base.points == round(utah.p_no_school * 100)
    kansas = made.districts[KANSAS].days[1]
    assert isinstance(kansas, Forecast)
    assert getattr(kansas.why.base, "thin", False)
    for i in MISSOURI:
        for day in made.districts[i].days:
            if isinstance(day, Forecast) and isinstance(day.why.base, PooledBase):
                assert not day.why.base.thin  # Missouri's region holds days


def test_the_flag_rides_the_file_and_parses_back() -> None:
    made = _pass(warned=False)
    data = made.to_json_bytes()
    assert b'"thin":true' in data
    assert PredictionsFile.from_json_bytes(data) == made


def test_the_flag_follows_the_region_not_the_district() -> None:
    built = model()
    assert built.thin.shape == built.p.shape
    assert bool(built.thin[UTAH].all())
    assert bool(built.thin[KANSAS].all())
    assert not bool(built.thin[list(MISSOURI)].any())


def test_only_a_nation_base_from_recorded_days_is_thin() -> None:
    with pytest.raises(ValidationError, match="thin"):
        PooledBase(kind="pooled", scope="state", points=40, thin=True)
    with pytest.raises(ValidationError, match="thin"):
        PooledBase(kind="pooled", scope="nation", points=40, thin=True, live=True)
    assert PooledBase(kind="pooled", scope="nation", points=40, thin=True).thin
    with pytest.raises(ValueError, match="thin"):
        base_for(SNOW, 0.4, True, "nation", thin=True)
    with pytest.raises(ValueError, match="thin"):
        base_for(SNOW, 0.4, False, "region", thin=True)
    found = base_for(SNOW, 0.4, False, "nation", thin=True)
    assert isinstance(found, PooledBase)
    assert found.thin


def test_a_situation_read_live_is_never_thin() -> None:
    cell = serve._Cell(
        p=0.4, q=0.1, own=False, scope="nation", counted=SNOW, live=True, records={},
        of="districts", thin=True,
    )  # fmt: skip
    at = datetime(2026, 1, 7, 2, tzinfo=UTC)
    day = serve._forecast(cell, SNOW, date(2026, 1, 7), None, at)
    assert isinstance(day.why.base, PooledBase)
    assert day.why.base.live
    assert not day.why.base.thin


def test_every_thin_served_cell_says_the_nations_true_record() -> None:
    built = model()
    rules = built.artifact.settings.rules()
    for k, _situation in enumerate(SITUATIONS):
        for i in range(len(world.DISTRICTS)):
            if not built.thin[i, k]:
                continue
            assert SCOPES[int(built.scope[i, k])] == "nation"
            assert not built.own[i, k]
            assert bool(
                says_true(
                    points_of(built.p[i : i + 1, k]),
                    built.named_y[i : i + 1, k],
                    built.named_n[i : i + 1, k],
                    rules.almost_share or 0.05,
                )[0]
            )


def _advisory_model() -> serve.ServeModel:
    """SYNTHETIC: the served model with recorded advisory days in the first two Missouri
    districts (30 closed of 40 each), so the nation's advisory record backs the situation and
    the regions without such days (Utah's, Kansas's) are thin under it."""
    artifact = world.model()
    districts = dict(artifact.districts)
    for leaid in ("2900001", "2900002"):
        entry = districts[leaid]
        assert entry.y is not None
        assert entry.n is not None
        assert entry.nd is not None
        y, n, nd = list(entry.y), list(entry.n), list(entry.nd)
        y[ADVISORY_K], n[ADVISORY_K], nd[ADVISORY_K] = 30, 40, 10
        districts[leaid] = entry.model_copy(update={"y": tuple(y), "n": tuple(n), "nd": tuple(nd)})
    return serve.build_model(
        world.directory(),
        artifact.model_copy(update={"districts": districts}),
        world.CONFIG,
        lambda _lon, _lat: None,
    )


def _advisory_pass(built: serve.ServeModel, ugcs: tuple[str, ...]) -> PredictionsFile:
    """SYNTHETIC: a Winter Weather Advisory over ``ugcs`` for the second day."""
    feed = parse_active(
        world.feed_bytes(
            [
                world.feature(
                    "/O.NEW.KSLC.WW.Y.0004.260107T0600Z-260108T0000Z/",
                    ugcs,
                    sent="2026-01-06T20:00:00+00:00",
                    onset="2026-01-07T06:00:00+00:00",
                    ends="2026-01-08T00:00:00+00:00",
                    event="Winter Weather Advisory",
                )
            ],
            "2026-01-06T20:05:00+00:00",
        )
    )
    now = world.utc("2026-01-07T02:00:00")
    days = (date(2026, 1, 6), date(2026, 1, 7))
    classes = district_classes(built, live_events(feed), index(), days, now, WINDOW, SHARE)
    return forecast_file(built, classes, days, now, closed_on=lambda _day: None, last=None)


def test_a_thin_advisory_base_keeps_its_weather_name_and_whole_flag() -> None:
    """After the rebase onto E2: a thin nation base under an advisory still names the weather
    of the days it counts ("recorded winter advisory days": every advisory day counted is one
    that did not follow a snow day, so ``whole``), and the two flags ride side by side."""
    built = _advisory_model()
    assert SITUATIONS[built.effective[ADVISORY_K]] == ADVISORY
    assert bool(built.thin[UTAH, ADVISORY_K])
    assert bool(built.whole[UTAH, ADVISORY_K])
    made = _advisory_pass(built, ("UTZ105",))
    day = made.districts[UTAH].days[1]
    assert isinstance(day, Forecast)
    base = day.why.base
    assert isinstance(base, PooledBase)
    assert (base.scope, base.thin, base.alert, base.weather) == ("nation", True, None, "advisory")
    value = json.loads(base.model_dump_json(exclude_defaults=True))
    assert (value["thin"], value["weather"]) == (True, "advisory")
    # Missouri's region holds the advisory days: its bases are not thin.
    for i in MISSOURI:
        assert not bool(built.thin[i, ADVISORY_K])


def test_the_base_takes_thin_and_whole_together() -> None:
    both = base_for(ADVISORY, 0.74, own=False, scope="nation", whole=True, thin=True)
    assert isinstance(both, PooledBase)
    assert (both.weather, both.thin) == ("advisory", True)
    plain = base_for(ADVISORY, 0.74, own=False, scope="nation", whole=True)
    assert isinstance(plain, PooledBase)
    assert (plain.weather, plain.thin) == ("advisory", False)
    assert "thin" not in json.loads(plain.model_dump_json(exclude_defaults=True))


def test_a_file_without_the_flag_reads_as_not_thin() -> None:
    """An old file (before the flag) parses unchanged: no base is thin."""
    made = _pass(warned=False)
    old = made.to_json_bytes().replace(b',"thin":true', b"")
    assert b"thin" not in old
    for entry in PredictionsFile.from_json_bytes(old).districts:
        for item in entry.days:
            if isinstance(item, Forecast):
                assert not getattr(item.why.base, "thin", False)
