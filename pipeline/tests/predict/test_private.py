"""Private schools (contract C3): their own chance from the private chain, the districts' rates
around them where the private schools have too few recorded days, the contiguous states only,
their shared outlooks, the day after, and the cap on distinct outlooks. SYNTHETIC world."""

from dataclasses import replace
from datetime import date, time
from typing import Any

import numpy as np
import pytest

from predict import world
from snowlight.predict import serve
from snowlight.predict.alerts_live import UgcIndex, live_events
from snowlight.predict.opens import SaidOpen
from snowlight.predict.pool import SCOPES
from snowlight.predict.serve import (
    build_model,
    closed_private,
    counted_over_private,
    forecast_file,
    pass_days,
    unit_classes,
)
from snowlight.predict.share import points_of, says_true
from snowlight.predict.situations import SITUATIONS, Window
from snowlight.schemas.live import DayTimeline
from snowlight.schemas.predictions import MAX_OUTLOOKS, Forecast, PooledBase, PredictionsFile
from snowlight.schemas.vocab import Reason, Status
from snowlight.sources.nws.alerts import parse_active

NOW = world.utc("2026-01-07T02:00:00")  # 8 PM in Chicago, Tuesday
WINDOW = Window(time(18), time(9), 21)
SNOW = [item.key for item in SITUATIONS].index("snow_warning")


def storm() -> list[Any]:
    """A SYNTHETIC winter storm warning over the Kansas City zone."""
    feed = parse_active(
        world.feed_bytes(
            [
                world.feature(
                    "/O.NEW.KEAX.WS.W.0004.260107T0600Z-260108T0000Z/",
                    ("MOZ028",),
                    sent="2026-01-07T01:10:00+00:00",
                    onset="2026-01-07T06:00:00+00:00",
                    ends="2026-01-08T00:00:00+00:00",
                )
            ],
            "2026-01-07T01:12:00+00:00",
        )
    )
    return live_events(feed)


def made(model: serve.ServeModel, events: list[Any], **kwargs: Any) -> PredictionsFile:
    lon, lat = world.lon_lat()
    index = UgcIndex.build(lon, lat, world.ugc_areas())
    days = pass_days(NOW, world.CONFIG)
    classes, private = unit_classes(model, events, index, days, NOW, WINDOW, 0.5)
    return forecast_file(
        model,
        classes,
        days,
        NOW,
        closed_on=lambda _day: None,
        last=kwargs.pop("last", None),
        private_classes=private,
        **kwargs,
    )


def chicago(_lon: float, _lat: float) -> str:
    return "America/Chicago"


def test_every_private_school_of_the_contiguous_states_is_served() -> None:
    model = build_model(world.directory(), world.model(), world.CONFIG, chicago)
    private = model.private
    assert private is not None
    # Alaska's private school is left out: the lower 48 only.
    assert private.positions.tolist() == [7, 8, 9]
    assert private.time_zone == ("America/Chicago", "America/Chicago", "America/Denver")
    assert private.known == 3
    # Districts next door, nearest first, a short list.
    assert private.neighbors[0][0] == 1
    assert all(len(found) <= 4 for found in private.neighbors)
    assert private.neighbors[2] == (4,)


def test_private_schools_are_counted_over_private_schools() -> None:
    model = build_model(world.directory(), world.model(), world.CONFIG, chicago)
    private = model.private
    assert private is not None
    assert private.of_private[SNOW]
    # The first school's own record (6 of 6 snow days) gives its own base; the second's 3 days
    # are too few: it names the private schools around it.
    assert private.own[0, SNOW]
    assert not private.own[1, SNOW]
    found = made(model, storm())
    first, second, utah = (found.outlook_of(entry)[1] for entry in found.schools)
    assert isinstance(first, Forecast)
    assert first.why.base.kind == "alert"
    assert first.record is not None
    assert [day.day for day in first.record.days] == [date(2024, 1, 9), date(2025, 1, 6)]
    assert isinstance(second, Forecast)
    assert isinstance(second.why.base, PooledBase)
    assert second.why.base.of == "private_schools"
    assert second.reasons == (Reason.WINTER_STORM,)
    # Utah's school has no warning: a clear day, at the floor, counted over private schools.
    assert isinstance(utah, Forecast)
    assert utah.reasons == ()
    assert isinstance(utah.why.base, PooledBase)
    assert utah.why.base.of == "private_schools"
    for entry in found.schools:
        for day in found.outlook_of(entry):
            assert isinstance(day, Forecast)
            assert day.why.total() == round(day.p_no_school * 100)


def test_the_days_own_weather_comes_before_another_weathers_private_days() -> None:
    # Effective situations: the private schools' as the committed model has them (none,
    # advisory, snow_warning and blizzard held; cold, ice, tropical and lake snow falling back
    # to snow_warning, none_after to none, advisory_after to advisory); made-up districts
    # holding every situation but tropical themselves.
    key = [item.key for item in SITUATIONS].index
    held = ("none", "none", "advisory", "advisory", "snow_warning", "snow_warning",
            "snow_warning", "snow_warning", "snow_warning", "blizzard")  # fmt: skip
    private = [key(k) for k in held]
    districts = list(range(len(SITUATIONS)))
    districts[key("tropical")] = key("snow_warning")
    keys = [item.key for item in SITUATIONS]
    found = dict(zip(keys, counted_over_private(private, districts), strict=True))
    mine = {k for k, v in found.items() if v}
    # Held by private schools: theirs. Neither chain holds tropical days: the private chain's
    # fallback, said truly. An extreme cold warning is counted over the districts' cold days
    # around the school, not private schools' winter storm warning days; the day after a snow
    # day over the districts' days after one, not private schools' clear days.
    assert mine == {"none", "advisory", "snow_warning", "blizzard", "tropical"}
    # No private chain, or one that backs nothing: the districts'.
    assert counted_over_private(None, districts) == (False,) * len(SITUATIONS)
    assert not any(counted_over_private([-1] * len(SITUATIONS), districts))


def test_without_private_days_a_school_takes_the_districts_around_it() -> None:
    model = build_model(world.directory(), world.model(private=False), world.CONFIG, chicago)
    private = model.private
    assert private is not None
    assert not any(private.of_private)
    assert not private.own.any()
    found = made(model, storm())
    kc = found.outlook_of(found.schools[0])[1]
    assert isinstance(kc, Forecast)
    assert isinstance(kc.why.base, PooledBase)
    assert kc.why.base.of == "districts"
    assert kc.record is None
    # The same chance a district with no record of its own there would get.
    assert kc.p_no_school > 0.3


def test_a_school_the_model_does_not_know_still_gets_a_chance() -> None:
    directory = world.directory()
    unknown = serve.DeployedDirectory(
        directory.stamp, directory.district_ids, directory.points, school_ids=None
    )
    model = build_model(unknown, world.model(), world.CONFIG, chicago)
    private = model.private
    assert private is not None
    # Without ids no school is known: Alaska's is left out by its point, the rest served.
    assert private.positions.tolist() == [7, 8, 9]
    assert private.known == 0
    assert not private.own.any()
    found = made(model, [])
    for entry in found.schools:
        day = found.outlook_of(entry)[1]
        assert isinstance(day, Forecast)
        assert isinstance(day.why.base, PooledBase)


def test_schools_share_outlooks_and_keep_their_previous() -> None:
    model = build_model(world.directory(), world.model(), world.CONFIG, chicago)
    calm = made(model, [])
    # The two calm Kansas City schools and Utah's name few outlooks between them.
    assert len(calm.outlooks) < len(calm.schools) * len(calm.days)
    later = NOW.replace(minute=30)
    lon, lat = world.lon_lat()
    index = UgcIndex.build(lon, lat, world.ugc_areas())
    days = pass_days(NOW, world.CONFIG)
    classes, private = unit_classes(model, storm(), index, days, later, WINDOW, 0.5)
    found = forecast_file(
        model, classes, days, later, closed_on=lambda _d: None, last=calm, private_classes=private
    )
    moved = found.outlook_of(found.schools[1])[1]
    assert isinstance(moved, Forecast)
    assert moved.previous is not None
    assert moved.previous.p_no_school == 0.01
    assert moved.previous.at == NOW
    still = found.outlook_of(found.schools[2])[1]
    assert isinstance(still, Forecast)
    assert still.previous is None


def test_a_school_said_open_drops_to_the_floor() -> None:
    model = build_model(world.directory(), world.model(), world.CONFIG, chicago)
    days = pass_days(NOW, world.CONFIG)
    found = made(model, storm(), said=SaidOpen(schools={days[1]: frozenset({7})}))
    said, usual = (found.outlook_of(entry)[1] for entry in found.schools[:2])
    assert isinstance(said, Forecast)
    assert isinstance(usual, Forecast)
    assert (said.p_no_school, said.p_delay) == (0.01, 0.0)
    assert said.why.base.points > 1
    assert [(r.kind, r.points) for r in said.why.reasons] == [
        ("said_open", 1 - said.why.base.points)
    ]
    assert usual.p_no_school > 0.3


def test_the_day_after_a_private_school_closed() -> None:
    model = build_model(world.directory(), world.model(), world.CONFIG, chicago)
    timeline = DayTimeline(
        schema_version=1,
        day=date(2026, 1, 5),
        generated_at=world.utc("2026-01-06T05:00:00"),
        directory=world.STAMP,
        content_sha256=None,
        final=True,
        gaps=(7, 0),
        counts=(1, 1),
        minutes=(-120, -100),
        statuses=(Status.CLOSED, Status.CLOSED),
        reasons=(Reason.WINTER_STORM, None),
        shifts=(),
        clocks=(),
    )
    # SYNTHETIC: school 7 closed for snow; school 8 closed with no reason named (not counted).
    assert closed_private(timeline, model) == frozenset({7})
    lon, lat = world.lon_lat()
    index = UgcIndex.build(lon, lat, world.ugc_areas())
    days = pass_days(NOW, world.CONFIG)
    classes, private = unit_classes(model, [], index, days, NOW, WINDOW, 0.5)
    found = forecast_file(
        model,
        classes,
        days,
        NOW,
        closed_on=lambda _d: None,
        last=None,
        private_classes=private,
        closed_schools=lambda day: frozenset({7}) if day == date(2026, 1, 5) else None,
    )
    after = found.outlook_of(found.schools[0])[0]
    assert isinstance(after, Forecast)
    # The day after a recorded closing borrows the plain day's days, and says so.
    assert after.why.base.kind in {"similar_days", "day_after", "pooled"}
    assert getattr(after.why.base, "borrowed", True)


def test_more_outlooks_than_the_table_holds_stop_before_any_school_entry() -> None:
    # B1 (S7-2 round 4): more distinct outlooks than the shared table may hold raise the typed
    # error the Fit ladder steps down on, never the schema's index check (a ValidationError a
    # pass could only go dark on). SYNTHETIC: one more school than the table holds, each with
    # its own chance, delay chance and scope.
    cells = [(p, q, scope) for scope in range(len(SCOPES)) for p in range(1, 100)
             for q in range(0, 100 - p, 2)][: MAX_OUTLOOKS + 1]  # fmt: skip
    assert len(cells) == MAX_OUTLOOKS + 1
    count, situations = len(cells), len(SITUATIONS)

    def column(values: list[float]) -> np.ndarray[Any, Any]:
        return np.repeat(np.array(values)[:, None], situations, axis=1)

    private = serve.PrivateServe(
        positions=np.arange(count, dtype=np.int64),
        time_zone=("America/Chicago",) * count,
        neighbors=((),) * count,
        p=column([p / 100 for p, _, _ in cells]),
        q=column([q / 100 for _, q, _ in cells]),
        own=np.zeros((count, situations), dtype=np.bool_),
        scope=column([scope for _, _, scope in cells]).astype(np.int64),
        of_private=(True,) * situations,
        effective=tuple(range(situations)),
        live=(False,) * situations,
        records=({},) * count,
        named_y=np.zeros((count, situations)),
        named_n=np.zeros((count, situations)),
        known=count,
    )
    days = (date(2026, 1, 7), date(2026, 1, 8))
    with pytest.raises(serve.TableError, match=f"over {MAX_OUTLOOKS:,} distinct outlooks"):
        serve._schools(
            private,
            np.zeros((count, 2), dtype=np.int64),
            days,
            NOW,
            earlier={},
            closed_on=None,
            said=SaidOpen(),
        )
    found, table, _zones = serve._schools(
        replace(private, positions=private.positions[:-1], time_zone=private.time_zone[:-1],
                neighbors=private.neighbors[:-1], p=private.p[:-1], q=private.q[:-1],
                own=private.own[:-1], scope=private.scope[:-1], records=private.records[:-1]),
        np.zeros((count - 1, 2), dtype=np.int64), days, NOW, earlier={}, closed_on=None,
        said=SaidOpen(),
    )  # fmt: skip
    assert len(table) == MAX_OUTLOOKS
    assert max(max(entry.days) for entry in found) == MAX_OUTLOOKS - 1


def test_the_private_rates_are_true_of_the_days_they_name() -> None:
    model = build_model(world.directory(), world.model(), world.CONFIG, chicago)
    private = model.private
    assert private is not None
    share = world.SETTINGS.almost_share
    assert says_true(points_of(private.p), private.named_y, private.named_n, share).all()
