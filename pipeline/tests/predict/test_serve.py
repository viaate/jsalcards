"""One serving pass over the synthetic world."""

from datetime import date, time

import numpy as np
import numpy.typing as npt
import pytest

from predict import world
from snowlight.predict import serve as serve_module
from snowlight.predict.alerts_live import LiveEvent, UgcIndex, live_events
from snowlight.predict.artifact import SITUATION_KEYS, RecordDay
from snowlight.predict.serve import (
    DeployedDirectory,
    ServeError,
    ServeModel,
    build_model,
    closed_districts,
    district_classes,
    forecast_file,
    pass_days,
)
from snowlight.predict.share import says_true as share_says_true
from snowlight.predict.situations import Situation, WeatherClass, Window
from snowlight.predict.why import base_for, record_for, why_for
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.predictions import (
    AlertBase,
    DayAfterBase,
    Forecast,
    NoThreat,
    PooledBase,
    PredictionsFile,
    SimilarDaysBase,
)
from snowlight.sources.nws.alerts import parse_active

WINDOW = Window(time(18), time(9), 21)
SHARE = 0.5


def model() -> ServeModel:
    return build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)


def index() -> UgcIndex:
    lon, lat = world.lon_lat()
    return UgcIndex.build(lon, lat, world.ugc_areas())


def storm(ugcs: tuple[str, ...] = ("MOZ028",)) -> list[LiveEvent]:
    feed = parse_active(
        world.feed_bytes(
            [
                world.feature(
                    "/O.NEW.KEAX.WS.W.0004.260107T0600Z-260108T0000Z/",
                    ugcs,
                    sent="2026-01-06T20:00:00+00:00",
                    onset="2026-01-07T06:00:00+00:00",
                    ends="2026-01-08T00:00:00+00:00",
                )
            ],
            "2026-01-06T20:05:00+00:00",
        )
    )
    return live_events(feed)


def test_the_model_knows_every_district_and_their_places() -> None:
    built = model()
    assert built.coverage == 1.0
    assert built.time_zone == tuple(world.ZONES[d] for d in world.DISTRICTS)
    # District 2's charter school is not eligible; the private school belongs to none.
    assert built.eligible[2].tolist() == [2]
    assert all(7 not in schools.tolist() for schools in built.eligible)
    assert built.neighbors[1] == (2,)  # district 3 is just over ten miles away
    assert built.neighbors[2] == (1, 3)
    assert 4 not in built.neighbors[1]  # Utah is far away
    assert all(len(near) <= 12 for near in built.neighbors)
    assert (built.p >= 0.01).all()
    assert (built.p <= 0.99).all()


def test_a_district_without_a_time_zone_is_refused() -> None:
    artifact = world.model()
    districts = dict(artifact.districts)
    districts["4900005"] = districts["4900005"].model_copy(update={"time_zone": None})
    bare = artifact.model_copy(update={"districts": districts})
    with pytest.raises(ServeError, match="no time zone"):
        build_model(world.directory(), bare, world.CONFIG, lambda _lon, _lat: None)
    found = build_model(world.directory(), bare, world.CONFIG, lambda _lon, _lat: "America/Denver")
    assert found.time_zone[4] == "America/Denver"


def test_directory_counts_must_agree_with_its_stamp() -> None:
    stamp = DirectoryStamp(generated_on=date(2026, 10, 14), schools=3, districts=5)
    with pytest.raises(ServeError, match="stamp"):
        DeployedDirectory(stamp, world.DISTRICTS, world.points())
    with pytest.raises(ServeError, match="other districts"):
        DeployedDirectory(
            world.STAMP.model_copy(update={"districts": 4}), world.DISTRICTS[:4], world.points()
        )


def test_classes_follow_the_alert_and_the_window() -> None:
    built = model()
    days = [date(2026, 1, 7), date(2026, 1, 8)]
    now = world.utc("2026-01-07T02:00:00")
    classes = district_classes(built, storm(), index(), days, now, WINDOW, SHARE)
    snow = int(WeatherClass.SNOW_WARNING)
    assert classes[:, 0].tolist() == [0, snow, snow, snow, 0]
    assert classes[:, 1].tolist() == [0, 0, 0, 0, 0]  # ends 6 PM on the 7th
    early = world.utc("2026-01-06T19:00:00")  # before it was sent
    assert not district_classes(built, storm(), index(), days, early, WINDOW, SHARE).any()


def test_a_pass_gives_every_school_day_a_chance_and_weekends_none() -> None:
    built = model()
    now = world.utc("2026-01-09T15:00:00")  # a Friday morning in Los Angeles
    days = pass_days(now, world.CONFIG)
    assert days == (date(2026, 1, 9), date(2026, 1, 10))
    classes = district_classes(built, [], index(), days, now, WINDOW, SHARE)
    made = forecast_file(built, classes, days, now, closed_on=lambda _day: None, last=None)
    assert len(made.districts) == len(world.DISTRICTS)
    for entry in made.districts:
        friday, saturday = entry.days
        assert isinstance(friday, Forecast)
        assert isinstance(saturday, NoThreat)
        assert friday.why.total() == round(friday.p_no_school * 100)
        assert friday.reasons == ()
        assert friday.hours is None
        assert friday.buses_at is None
        assert friday.events == ()
    data = made.to_json_bytes()
    assert PredictionsFile.from_json_bytes(data) == made


def test_the_why_names_its_base_and_the_record_comes_before_the_day() -> None:
    built = model()
    now = world.utc("2026-01-07T02:00:00")
    days = (date(2026, 1, 6), date(2026, 1, 7))
    classes = district_classes(built, storm(), index(), days, now, WINDOW, SHARE)
    made = forecast_file(built, classes, days, now, closed_on=lambda _day: None, last=None)
    own = made.districts[1].days[1]
    assert isinstance(own, Forecast)
    assert isinstance(own.why.base, AlertBase)
    assert own.why.base.alert == "winter_storm_warning"
    assert own.why.total() == round(own.p_no_school * 100)
    assert own.p_no_school > 0.3
    assert own.record is not None
    assert own.record.proves == "base"
    assert all(day.day < date(2026, 1, 7) for day in own.record.days)
    pooled = made.districts[3].days[1]
    assert isinstance(pooled, Forecast)
    assert isinstance(pooled.why.base, PooledBase)
    assert pooled.record is None
    assert pooled.why.base.points == round(pooled.p_no_school * 100)


def test_the_day_after_a_closing_and_previous_chances() -> None:
    built = model()
    days = (date(2026, 1, 7), date(2026, 1, 8))
    first_at = world.utc("2026-01-07T02:00:00")
    classes = district_classes(built, storm(), index(), days, first_at, WINDOW, SHARE)
    first = forecast_file(built, classes, days, first_at, closed_on=lambda _day: None, last=None)
    later_at = world.utc("2026-01-07T02:30:00")
    calm = np.zeros_like(classes)
    second = forecast_file(
        built, calm, days, later_at, closed_on=lambda _day: frozenset({1}), last=first
    )
    moved = second.districts[1].days[0]
    assert isinstance(moved, Forecast)
    assert moved.previous is not None
    assert moved.previous.at == first_at
    assert moved.previous.at < second.generated_at
    # The world has no labeled day after a closing: the day after takes the plain day's
    # rates and sentence (its fallback), never an uninformed 1 in 2.
    assert isinstance(moved.why.base, DayAfterBase | PooledBase | SimilarDaysBase)
    assert moved.p_no_school != 0.5
    third = forecast_file(
        built, calm, days, world.utc("2026-01-07T03:00:00"), closed_on=lambda _d: frozenset({1}),
        last=second,
    )  # fmt: skip
    kept = third.districts[1].days[0]
    assert isinstance(kept, Forecast)
    assert kept.previous == moved.previous  # the same percent: the earlier change stands
    other = forecast_file(
        built,
        calm,
        days,
        later_at,
        closed_on=lambda _day: None,
        last=first.model_copy(update={"directory": world.STAMP.model_copy(update={"schools": 9})}),
    )
    assert all(
        isinstance(day, Forecast) and day.previous is None
        for entry in other.districts
        for day in entry.days
    )


def test_why_bases_and_records() -> None:
    snow = Situation(WeatherClass.SNOW_WARNING)
    assert isinstance(base_for(snow, 0.42, own=True, scope="county"), AlertBase)
    assert isinstance(base_for(Situation(WeatherClass.NONE), 0.01, True, "region"), SimilarDaysBase)
    assert isinstance(
        base_for(Situation(WeatherClass.LAKE_SNOW), 0.2, True, "region"), SimilarDaysBase
    )
    after = Situation(WeatherClass.NONE, after=True)
    assert isinstance(base_for(after, 0.3, True, "region"), DayAfterBase)
    pooled = base_for(Situation(WeatherClass.TROPICAL), 0.05, False, "state")
    assert isinstance(pooled, PooledBase)
    assert pooled.alert is None
    with pytest.raises(ValueError, match="scope"):
        base_for(snow, 0.1, False, "planet")  # type: ignore[arg-type]
    assert why_for(snow, 0.07, True, "region").total() == 7
    days = tuple(RecordDay(day=date(2024, 1, d), did="closed") for d in range(1, 11))
    found = record_for(days, date(2024, 1, 10))
    assert found is not None
    assert len(found.days) == 8
    assert found.days[-1].day == date(2024, 1, 9)
    assert record_for(days, date(2023, 1, 1)) is None


def test_no_published_chance_is_an_uninformed_prior() -> None:
    built = model()
    artifact = world.model()
    n = np.zeros(len(SITUATION_KEYS))
    for counted in artifact.districts.values():
        if counted.n is not None:
            n += np.array(counted.n)
    for k, key in enumerate(SITUATION_KEYS):
        if n[k] < artifact.settings.nation_min_days:
            # Not modeled: its fallback's rates, which the nation has days of.
            target = built.effective[k]
            assert target != k, key
            assert n[target] >= artifact.settings.nation_min_days
            assert np.array_equal(built.p[:, k], built.p[:, target])
    assert all(n[target] >= artifact.settings.nation_min_days for target in built.effective)
    # Every pooled base names a level true of it: here no place but the nation has 8 days
    # of snow, so a district without its own record names the nation.
    days = (date(2026, 1, 7), date(2026, 1, 8))
    now = world.utc("2026-01-07T02:00:00")
    classes = district_classes(built, storm(), index(), days, now, WINDOW, SHARE)
    made = forecast_file(built, classes, days, now, closed_on=lambda _day: None, last=None)
    for entry in made.districts:
        for outlook in entry.days:
            if isinstance(outlook, Forecast) and isinstance(outlook.why.base, PooledBase):
                assert outlook.why.base.scope in {"nation", "region", "state", "county", "nearby"}
                assert outlook.why.total() == round(outlook.p_no_school * 100)


def test_a_model_with_a_situation_nothing_backs_is_refused() -> None:
    artifact = world.model()
    bare = artifact.model_copy(
        update={"settings": artifact.settings.model_copy(update={"fallback": {}})}
    )
    with pytest.raises(ServeError, match="no labeled days"):
        build_model(world.directory(), bare, world.CONFIG, lambda _lon, _lat: None)


def built_cells() -> int:
    """The served cells of the world model."""
    return int(model().p.size)


def test_a_model_whose_served_sentence_would_be_false_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_model checks every served cell's share against the place it names (on the
    served neighbors and the published chance) and refuses to serve a false one."""
    cells = built_cells()
    calls: list[int] = []

    real = share_says_true

    def one_false(
        points: npt.NDArray[np.int64],
        y: npt.NDArray[np.float64],
        n: npt.NDArray[np.float64],
        almost: float,
    ) -> npt.NDArray[np.bool_]:
        true = real(points, y, n, almost)
        calls.append(int(true.sum()))
        true.flat[0] = False
        return true

    monkeypatch.setattr(serve_module, "says_true", one_false)
    with pytest.raises(ServeError, match="1 served base sentences are not true"):
        build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    # Every cell was true before the one turned false.
    assert calls == [cells]


def test_the_day_after_comes_from_the_live_day_timeline() -> None:
    built = model()
    assert closed_districts(world.timeline(), built, 0.5) == frozenset({1})
    other = world.STAMP.model_copy(update={"generated_on": date(2026, 9, 25)})
    # A timeline of another directory that shows a closing cannot be read against this one:
    # the pass goes dark rather than drop the day after.
    with pytest.raises(ServeError, match="another directory"):
        closed_districts(world.timeline(other), built, 0.5)
    quiet = world.timeline(other).model_copy(
        update={"gaps": (), "counts": (), "minutes": (), "statuses": (), "reasons": (),
                "shifts": (), "clocks": ()}
    )  # fmt: skip
    assert closed_districts(quiet, built, 0.5) == frozenset()
    # The same stamp with another content digest is another directory too.
    digested = DeployedDirectory(
        built.directory.stamp, built.directory.district_ids, built.directory.points, "a" * 64
    )
    moved = build_model(digested, world.model(), world.CONFIG, lambda _lon, _lat: None)
    with pytest.raises(ServeError, match="another directory"):
        closed_districts(
            world.timeline().model_copy(update={"content_sha256": "b" * 64}), moved, 0.5
        )
    assert closed_districts(
        world.timeline().model_copy(update={"content_sha256": "a" * 64}), moved, 0.5
    ) == frozenset({1})
