"""Piece 3, the reasons: the alert text parser, the terms, Shapley points, the neighbors and
announcement rules, backtest v2's seasons, and the serving pass with the reasons on and off.

Every text, number and place here is made up for the tests (the alert sentences are written in
the NWS's public product style); nothing comes from a real list or a real storm.
"""

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from itertools import permutations

import numpy as np
import polars as pl
import pytest

from predict import world
from predict.test_serve import WINDOW, index, storm
from snowlight.predict import (
    alert_text,
    announce,
    backtest,
    backtest_terms,
    forecast_live,
    ndfd,
    nowcast,
    posts,
    reasons,
    shapley,
    term_rows,
    terms,
    terms_file,
)
from snowlight.predict import artifact as artifact_module
from snowlight.predict import forecast_history as history
from snowlight.predict.forecast_values import DistrictForecast, Forecasts
from snowlight.predict.labels import ReadRecord
from snowlight.predict.pool import Rows
from snowlight.predict.serve import (
    Fit,
    ServeModel,
    build_model,
    district_classes,
    forecast_file,
    with_terms,
)
from snowlight.predict.situations import WeatherClass
from snowlight.predict.terms import UNKNOWN, Design, Levels, Shape, Term, TermFit
from snowlight.schemas.live import ClosingsDay, ClosingsFile
from snowlight.schemas.predictions import (
    Forecast,
    IceReason,
    NeighborsReason,
    PredictionsFile,
    SnowTotalReason,
    WindChillReason,
)
from snowlight.schemas.vocab import Reason, Status

# --- the alert text -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [
        ("* WHAT...Heavy snow. Total snow accumulations of 6 to 10 inches.", 6.0, 10.0),
        ("Snow accumulations between 4 and 8 inches are expected.", 4.0, 8.0),
        ("* WHAT...Snow expected. Total snow accumulations of up to 3 inches.", 0.0, 3.0),
        ("Total snow accumulations of 2 to 4 inches and ice accumulations of a light glaze.", 2, 4),
        ("Additional snow accumulations of one to two inches.", 1.0, 2.0),
    ],
)
def test_the_parser_reads_snow_low_to_high(text: str, low: float, high: float) -> None:
    found = alert_text.amounts(text)
    assert (found.snow_low, found.snow_high) == (low, high)


@pytest.mark.parametrize(
    ("text", "inches"),
    [
        ("* WHAT...Freezing rain. Ice accumulations of around a tenth of an inch of ice.", 0.1),
        ("Freezing rain with around a tenth of an inch of ice expected.", 0.1),
        ("Significant icing. Ice accumulations of a quarter to one half inch.", 0.5),
        ("Expect 0.25 inches of ice on elevated surfaces.", 0.25),
    ],
)
def test_the_parser_reads_ice(text: str, inches: float) -> None:
    assert alert_text.amounts(text).ice == inches


@pytest.mark.parametrize(
    ("text", "chill"),
    [
        ("* WHAT...Dangerously cold wind chills as low as 25 below zero.", -25),
        ("Wind chills as low as minus 30 expected.", -30),
        ("Wind chills near 5 above zero this morning.", 5),
    ],
)
def test_the_parser_reads_wind_chill(text: str, chill: int) -> None:
    assert alert_text.amounts(text).wind_chill == chill


def test_a_text_range_is_a_level_only_inside_one_bucket() -> None:
    assert (
        alert_text.snow_level(alert_text.amounts("Total snow accumulations of 6 to 9 inches")) == 4
    )
    assert alert_text.snow_level(alert_text.amounts("snow accumulations of 2 to 4 inches")) == 2
    assert (
        alert_text.snow_level(alert_text.amounts("Total snow accumulations of 6 to 10 inches"))
        == -1
    )
    assert alert_text.snow_level(alert_text.amounts("No snow is expected.")) == -1
    assert alert_text.amounts("A cold front passes.") == alert_text.Amounts()


# --- levels and bands ---------------------------------------------------------------------------


def test_a_code_hides_what_its_bucket_outranks() -> None:
    assert terms.levels_of(0) == (0, 0, 0)
    assert terms.levels_of(3) == (3, 0, UNKNOWN)
    assert terms.levels_of(6) == (UNKNOWN, 0, UNKNOWN)  # freezing drizzle: no snow level
    assert terms.levels_of(8) == (UNKNOWN, 2, UNKNOWN)
    assert terms.levels_of(11) == (0, 0, 3)
    assert terms.levels_of(13) == (UNKNOWN, UNKNOWN, UNKNOWN)
    assert terms.levels_of(None) == (UNKNOWN, UNKNOWN, UNKNOWN)
    with pytest.raises(ValueError, match="bucket code"):
        terms.levels_of(14)


def test_neighbor_levels() -> None:
    assert [terms.neighbor_level(x) for x in (0.0, 0.2, 0.25, 0.4, 0.5, 0.6, 1.0)] == [
        0, 1, 1, 2, 2, 3, 3
    ]  # fmt: skip
    assert terms.neighbor_level(None) == UNKNOWN
    assert terms.neighbor_level(math.nan) == UNKNOWN


def test_the_zero_band_is_neither_above_nor_below_most_counted_days() -> None:
    assert terms.zero_band([0, 1, 8, 1, 0, 0]) == (2, 2)
    assert terms.zero_band([5, 0, 0, 0, 0, 5]) == (0, 5)
    assert terms.zero_band([1, 1, 1, 1, 0, 0]) == (1, 2)
    assert terms.zero_band([0, 0, 0, 0, 0, 0]) == (0, 5)


def _design(
    n: int, seed: int, weather: int = 1, own: int | None = None
) -> tuple[Design, np.ndarray]:
    rng = np.random.default_rng(seed)
    snow = rng.integers(0, 6, n)
    p = 1 / (1 + np.exp(-(-0.5 + 0.6 * (snow - 2))))
    y = (rng.random(n) < p).astype(float)
    levels = {term: np.full(n, UNKNOWN, dtype=np.int64) for term in terms.TERM_ORDER}
    levels[Term.SNOW_ADVISORY] = snow.astype(np.int64)
    levels[Term.SNOW_STORM] = snow.astype(np.int64)
    design = Design(
        offset=np.full(n, -0.5),
        y=y,
        weather=np.full(n, weather, dtype=np.int64),
        levels=levels,
        own=None if own is None else np.full(n, own, dtype=np.int64),
    )
    return design, rng.integers(2019, 2023, n).astype(np.int64)


def test_a_fit_keeps_every_sign_and_is_zero_on_its_band() -> None:
    design, seasons = _design(3000, 1)
    model = terms.fit(design, seasons)
    snow = model.fits[Term.SNOW_ADVISORY]
    values = [snow.value(level) for level in range(6)]
    assert values == sorted(values)  # monotone
    assert snow.value(snow.shape.low) == 0.0
    assert values[0] < 0 < values[-1]
    for term in terms.ADD_ONLY:
        found = model.fits[term]
        assert all(found.value(level) >= 0 for level in range(found.shape.levels))
    assert backtest_terms.signs_hold(model)
    assert model.fits[Term.SNOW_ADVISORY].value(UNKNOWN) == 0.0


def test_an_unknown_level_adds_nothing_and_other_weather_has_no_snow_term() -> None:
    design, seasons = _design(800, 2, weather=int(WeatherClass.COLD))
    model = terms.fit(design, seasons)
    assert model.values(WeatherClass.COLD, WeatherClass.COLD, Levels(snow=5)) == {}
    assert model.values(WeatherClass.NONE, WeatherClass.NONE, Levels(snow=5, ice=2)) == {}


@pytest.mark.parametrize(
    "own", [WeatherClass.TROPICAL, WeatherClass.LAKE_SNOW, WeatherClass.ICE, WeatherClass.COLD]
)
def test_a_day_that_falls_back_to_winter_storm_days_takes_no_snow_term(own: WeatherClass) -> None:
    # Hurricane, lake effect snow, ice storm and cold days that are not modeled publish the
    # winter storm warning days' rates; the storm's snow term is not theirs.
    every = Levels(snow=0, ice=0, cold=0, neighbors=0)
    found = MODEL.values(own, WeatherClass.SNOW_WARNING, every)
    assert Term.SNOW_STORM not in found
    assert Term.SNOW_ADVISORY not in found
    light = DistrictForecast(code=0, snow_low=0.0, snow_high=1.0, ice=0.0, feels=30)
    moved = reasons.moved(
        0.95, 0.0, own, WeatherClass.SNOW_WARNING, MODEL, reasons.DayInputs(light), 0.01, 0.99
    )
    assert moved is None or all(line.kind != "snow_total" for line in moved.reasons)
    # An advisory day counted over winter storm days has neither snow term (its band and its
    # words are of the advisory days), and a storm day keeps its own.
    assert not {Term.SNOW_STORM, Term.SNOW_ADVISORY} & set(
        MODEL.values(WeatherClass.ADVISORY, WeatherClass.SNOW_WARNING, Levels(snow=0)).keys()
    )
    assert Term.SNOW_STORM in MODEL.values(
        WeatherClass.BLIZZARD, WeatherClass.SNOW_WARNING, Levels(snow=5)
    )


def test_the_fit_reads_snow_only_on_days_of_its_own_class() -> None:
    # Cold days counted over winter storm days: in the rows, but never in the storm snow term's
    # band or its columns, so their snow levels cannot move the storm term.
    storm, seasons = _design(600, 3, weather=int(WeatherClass.SNOW_WARNING))
    cold, cold_seasons = _design(600, 4, weather=int(WeatherClass.SNOW_WARNING))
    cold_rows = Design(
        offset=np.full(600, 3.0),  # cold days: rarely open whatever the snow
        y=np.ones(600),
        weather=cold.weather,
        levels={t: np.zeros(600, dtype=np.int64) for t in terms.TERM_ORDER},
        own=np.full(600, int(WeatherClass.COLD), dtype=np.int64),
    )
    both = Design(
        offset=np.concatenate([storm.offset, cold_rows.offset]),
        y=np.concatenate([storm.y, cold_rows.y]),
        weather=np.concatenate([storm.weather, cold_rows.weather]),
        levels={t: np.concatenate([storm.levels[t], cold_rows.levels[t]]) for t in storm.levels},
        own=np.concatenate([storm.weather, cold_rows.own_weather()]),
    )
    alone = terms.shapes_for(storm)[Term.SNOW_STORM]
    assert terms.shapes_for(both)[Term.SNOW_STORM] == alone
    has = terms.applies(Term.SNOW_STORM, both.own_weather(), both.weather)
    assert has[:600].all()
    assert not has[600:].any()
    found = terms.fit(both, np.concatenate([seasons, cold_seasons]))
    assert (
        found.fits[Term.SNOW_STORM].counts == terms.fit(storm, seasons).fits[Term.SNOW_STORM].counts
    )


def test_the_storm_snow_term_only_adds() -> None:
    design, seasons = _design(3000, 6, weather=int(WeatherClass.SNOW_WARNING))
    model = terms.fit(design, seasons)
    storm = model.fits[Term.SNOW_STORM]
    assert storm.shape.low == 0
    assert storm.down == ()
    assert all(storm.value(level) >= 0 for level in range(6))
    assert storm.value(5) > 0
    assert backtest_terms.signs_hold(model)


def test_each_inner_fit_takes_its_bands_from_its_own_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    design, seasons = _design(600, 7)
    calls: list[tuple[int, object]] = []
    real = terms.fit_with

    def spy(
        found: Design, penalty: float, shapes: object = None, support: object = None
    ) -> terms.Model:
        calls.append((found.y.size, shapes))
        assert support is None
        return real(found, penalty, None if shapes is None else shapes)  # type: ignore[arg-type]

    monkeypatch.setattr(terms, "fit_with", spy)
    terms.fit(design, seasons, penalties=(1.0, 10.0))
    inner = calls[:-1]
    assert inner
    assert all(size < 600 and shapes is None for size, shapes in inner)
    assert calls[-1][0] == 600


# --- Shapley points -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("p_base", "values"),
    [
        (0.3, {"a": 0.8, "b": -0.4, "c": 0.2}),
        (0.74, {"snow": -1.1}),
        (0.05, {"ice": 2.0, "near": 0.5, "snow": 0.7, "cold": 0.1, "x": -0.3}),
    ],
)
def test_shapley_values_add_up_and_follow_their_signs(
    p_base: float, values: dict[str, float]
) -> None:
    found = shapley.shapley(p_base, values)
    z = math.log(p_base / (1 - p_base)) + sum(values.values())
    assert sum(found.values()) == pytest.approx(100 * (1 / (1 + math.exp(-z)) - p_base))
    for key, value in values.items():
        assert found[key] * value >= 0
    # exact: the average marginal value over every order
    keys = list(values)
    average = dict.fromkeys(keys, 0.0)
    orders = list(permutations(keys))
    for order in orders:
        seen: list[str] = []
        for key in order:
            before = 100 / (
                1 + math.exp(-(math.log(p_base / (1 - p_base)) + sum(values[k] for k in seen)))
            )
            seen.append(key)
            after = 100 / (
                1 + math.exp(-(math.log(p_base / (1 - p_base)) + sum(values[k] for k in seen)))
            )
            average[key] += (after - before) / len(orders)
    for key in keys:
        assert found[key] == pytest.approx(average[key])


def test_whole_points_add_up_and_never_cross_sides() -> None:
    assert shapley.whole_points({"a": 3.6, "b": 2.6, "c": -0.3}, 6) == {"a": 4, "b": 2, "c": 0}
    assert sum(shapley.whole_points({"a": 0.4, "b": 0.3}, 1).values()) == 1
    assert shapley.whole_points({"a": 0.4}, 0) == {"a": 0}
    scaled = shapley.whole_points({"a": 30.0, "b": 10.0}, 20)  # a clamp took points away
    assert sum(scaled.values()) == 20
    assert all(v >= 0 for v in scaled.values())
    with pytest.raises(ValueError, match="other side"):
        shapley.whole_points({"a": 2.0}, -3)
    with pytest.raises(ValueError, match="at most"):
        shapley.shapley(0.5, dict.fromkeys("abcdef", 0.1))


# --- a day's reasons ----------------------------------------------------------------------------

MODEL = terms.Model(
    {
        Term.SNOW_ADVISORY: TermFit(
            Term.SNOW_ADVISORY, Shape(6, 2, 2), up=(0.0, 0.3, 0.0), down=(0.5, 0.6)
        ),
        Term.SNOW_STORM: TermFit(Term.SNOW_STORM, Shape(6, 0, 4), up=(0.9,), down=()),
        Term.ICE: TermFit(Term.ICE, Shape(3, 0, 0), up=(1.2, 0.4), down=()),
        Term.COLD: TermFit(Term.COLD, Shape(5, 0, 0), up=(0.1, 0.2, 0.3, 0.4), down=()),
        Term.NEIGHBORS: TermFit(Term.NEIGHBORS, Shape(4, 0, 0), up=(0.4, 0.4, 0.4), down=()),
    },
    1.0,
)


def _moved(p: float, weather: WeatherClass, inputs: reasons.DayInputs) -> reasons.Moved | None:
    return reasons.moved(p, round((1 - p) * 0.2, 2), weather, weather, MODEL, inputs, 0.01, 0.99)


def test_a_light_advisory_takes_points_away_and_the_parts_add_up() -> None:
    light = DistrictForecast(code=0, snow_low=0.0, snow_high=1.0)
    found = _moved(0.74, WeatherClass.ADVISORY, reasons.DayInputs(forecast=light))
    assert found is not None
    (line,) = found.reasons
    assert isinstance(line, SnowTotalReason)
    assert line.points < 0
    assert 74 + line.points == round(found.p_no_school * 100)
    assert found.p_no_school + found.p_delay <= 1


def test_every_line_keeps_its_side_and_they_add_up_to_the_chance() -> None:
    near = nowcast.Posted(share=0.75, status=Status.CLOSED, districts=(3, 1))
    heavy = DistrictForecast(
        code=5,
        snow_low=9.0,
        snow_high=13.0,
        snow_night=10.0,
        snow_night_low=9.4,
        snow_night_high=10.6,
        ice=0.0,
    )
    found = _moved(0.62, WeatherClass.SNOW_WARNING, reasons.DayInputs(heavy, near))
    assert found is not None
    kinds = {type(line) for line in found.reasons}
    assert kinds == {SnowTotalReason, NeighborsReason}
    assert all(line.points > 0 for line in found.reasons)
    assert 62 + sum(line.points for line in found.reasons) == round(found.p_no_school * 100)
    iced = DistrictForecast(code=8, ice=0.37, ice_low=0.31, ice_high=0.39)
    found = _moved(0.4, WeatherClass.ICE, reasons.DayInputs(iced))
    assert found is not None
    (ice,) = found.reasons
    assert isinstance(ice, IceReason)
    assert ice.inches == 0.3
    assert ice.points > 0
    cold = DistrictForecast(code=12, feels=-27, feels_low=-27.4, feels_high=-26.6)
    found = _moved(0.5, WeatherClass.COLD, reasons.DayInputs(cold))
    assert found is not None
    (chill,) = found.reasons
    assert isinstance(chill, WindChillReason)
    assert chill.feels_like == -27


def test_a_snow_line_states_an_amount_only_where_every_school_has_it() -> None:
    # The terms read the code alone, as in training (the history keeps nothing else), so a
    # line is never dropped for its words; the words state the code's bucket cut to the
    # schools' range only where every deciding school's amount, as read, is in the bucket, and
    # otherwise only the comparison.
    for code, low, high, words in (
        (0, 0.0, 0.4, (0.0, 0.5)),
        (0, 0.0, 0.0, (0.0, 0.0)),  # no new snow at all: still the under-half-inch step
        (0, 0.3, 2.3, None),  # schools reach 2.3 in; the district's 50% is under 0.5
        (0, 0.0, 0.7, None),  # whole inches (0 to 1) would have hidden the 0.7
        (0, 0.0, 0.49, (0.0, 0.5)),  # the bucket's top, said, holds the school at 0.49
        (0, 0.0, 0.5, None),  # a school at 0.5 is the next bucket's, as the codes read it
    ):
        found = _moved(
            0.74,
            WeatherClass.ADVISORY,
            reasons.DayInputs(DistrictForecast(code=code, snow_low=low, snow_high=high)),
        )
        assert found is not None
        (line,) = found.reasons
        assert isinstance(line, SnowTotalReason)
        assert line.points < 0
        assert (line.low, line.high) == (None, None) if words is None else words
        if line.high is not None:
            assert line.high >= high  # never a high below a deciding school's amount
            assert line.low is not None
            assert line.low <= low
        assert line.against == "advisory"
    # Training's points whatever the words: the same day with and without an amount said.
    said = _moved(0.74, WeatherClass.ADVISORY, reasons.DayInputs(DistrictForecast(0, 0.0, 0.4)))
    unsaid = _moved(0.74, WeatherClass.ADVISORY, reasons.DayInputs(DistrictForecast(0, 0.3, 2.3)))
    assert said is not None
    assert unsaid is not None
    assert [r.points for r in said.reasons] == [r.points for r in unsaid.reasons]
    assert said.p_no_school == unsaid.p_no_school
    # Freezing drizzle (code 6): the advisory is for the ice, never "lighter than most".
    drizzle = DistrictForecast(code=6, snow_low=0.0, snow_high=1.0, ice=0.05)
    assert _moved(0.74, WeatherClass.ADVISORY, reasons.DayInputs(drizzle)) is None
    # A heavy storm whose lightest school is under the band's top: only the comparison.
    mixed = DistrictForecast(code=5, snow_low=7.0, snow_high=12.0, snow_night=10.0, ice=0.0)
    found = _moved(0.6, WeatherClass.SNOW_WARNING, reasons.DayInputs(mixed))
    assert found is not None
    (line,) = found.reasons
    assert isinstance(line, SnowTotalReason)
    assert (line.low, line.high, line.overnight, line.against) == (None, None, False, "storms")
    heavy = DistrictForecast(code=5, snow_low=9.2, snow_high=12.4, ice=0.0)
    found = _moved(0.6, WeatherClass.SNOW_WARNING, reasons.DayInputs(heavy))
    assert found is not None
    (line,) = found.reasons
    assert isinstance(line, SnowTotalReason)
    assert (line.low, line.high) == (9.0, 13.0)


@pytest.mark.parametrize(
    ("level", "low", "high", "words"),
    [
        (0, 0.0, 0.0, (0.0, 0.0)),
        (0, 0.0, 0.3, (0.0, 0.5)),
        (0, 0.0, 1.0, None),  # a school at 1 in: the bucket's 0 to 0.5 leaves it out
        (0, 0.3, 2.3, None),
        (0, None, None, None),  # amounts nobody read are never said (the reader always has them)
        (1, 0.6, 1.0, (0.5, 1.0)),
        (1, 0.5, 1.99, (0.5, 2.0)),
        (1, 0.5, 2.0, None),  # 2.0 in is in most advisory days' 2 to 4: never "lighter than"
        (1, 1.0, 5.0, None),
        (2, 2.0, 3.0, (2.0, 3.0)),
        (2, 1.0, 3.0, None),
        (3, 4.2, 5.9, (4.0, 6.0)),
        (3, 3.0, 7.0, None),
        (4, 6.0, 8.9, (6.0, 9.0)),
        (4, 6.0, 9.0, None),
        (5, 9.3, 13.2, (9.0, 14.0)),
        (5, 7.0, 14.0, None),
        (3, None, None, None),  # a snow code without its amounts: the reader never gives it
        (UNKNOWN, 0.0, 0.3, None),
    ],
)
def test_snow_words_state_a_range_only_where_it_holds_every_school(
    level: int, low: float | None, high: float | None, words: tuple[float, float] | None
) -> None:
    assert reasons.snow_words(level, low, high) == words


def test_every_stated_amount_holds_every_deciding_schools_forecast() -> None:
    # Random school amounts, each district's code from its 50% value as the reader codes it:
    # a stated range holds every school's amount as read, or the line states none; "overnight"
    # holds every school's overnight part; the comparison's side holds every school's amount
    # where an amount is stated; an ice or wind chill amount is stated only where every school
    # reads it at the line's precision, and a wind chill's never with a school not read.
    rng = np.random.default_rng(11)
    stated = unstated = said_overnight = said_by = 0
    for trial in range(4000):
        size = int(rng.integers(1, 9))
        scale = (0.4, 1.0, 3.0, 6.0, 12.0)[trial % 5]
        snow = np.round(rng.uniform(0, scale, size) * rng.uniform(0.2, 1.0), int(trial % 3))
        # Each school's overnight part: all of its snow, none, or some, never more than all.
        share = rng.choice(np.array([1.0, 0.0, 0.5, 0.9]), size) * rng.uniform(0.8, 1.0, size)
        night = np.minimum(snow, np.round(snow * np.where(trial % 4 == 0, 1.0, share), 2))
        half = float(np.sort(snow)[::-1][math.ceil(0.5 * size) - 1])
        night_half = float(np.sort(night)[::-1][math.ceil(0.5 * size) - 1])
        code = int(ndfd.bucket_codes(np.array([half]), np.zeros(1), np.full(1, 40.0))[0])
        weather = WeatherClass.ADVISORY if code <= 2 else WeatherClass.SNOW_WARNING
        found = DistrictForecast(
            code=code,
            snow_low=float(snow.min()),
            snow_high=float(snow.max()),
            snow_night=night_half,
            snow_night_low=float(night.min()),
            snow_night_high=float(night.max()),
            ice=0.0,
        )
        moved = _moved(0.6, weather, reasons.DayInputs(found))
        for line in () if moved is None else moved.reasons:
            assert isinstance(line, SnowTotalReason)
            if line.low is None or line.high is None:
                unstated += 1
                assert not line.overnight
                continue
            stated += 1
            assert line.low <= float(snow.min())
            assert float(snow.max()) <= line.high, (snow, code, line)
            if line.overnight:
                said_overnight += 1
                assert all(line.low <= value <= line.high for value in night), (night, line)
                assert line.high > 0
            else:
                said_by += 1
            # The side: "more than most" only where every school is past the band's top,
            # "less" only where every school is under its bottom.
            term = Term.SNOW_STORM if line.against == "storms" else Term.SNOW_ADVISORY
            shape = MODEL.fits[term].shape
            if line.points > 0:
                assert all(value >= reasons.SNOW_START[shape.high + 1] for value in snow)
            else:
                assert all(value < reasons.SNOW_START[shape.low] for value in snow), (
                    snow,
                    code,
                    line,
                )
        ice = rng.uniform(0.08, 0.6, size)
        ice_half = float(np.sort(ice)[::-1][math.ceil(0.5 * size) - 1])
        amount = reasons.ice_amount(round(ice_half, 2), float(ice.min()), float(ice.max()))
        if amount is not None:
            assert all(math.floor(value * 10 + 1e-9) / 10 == amount for value in ice)
        feels = rng.uniform(-35, -15, size)
        cold = round(float(np.sort(feels)[math.ceil(0.5 * size) - 1]))
        chill = reasons.chill_amount(cold, float(feels.min()), float(feels.max()))
        if chill is not None:
            assert all(round(value) == chill for value in feels)
    assert stated > 0
    assert unstated > 0
    assert said_overnight > 0
    assert said_by > 0


def test_an_ice_or_wind_chill_line_states_only_what_every_school_reads() -> None:
    assert reasons.ice_amount(0.27, 0.21, 0.29) == 0.2
    assert reasons.ice_amount(0.27, 0.18, 0.41) is None  # schools read 0.1 to 0.4
    assert reasons.ice_amount(None, None, None) is None
    assert reasons.chill_amount(-27, -27.4, -26.6) == -27
    assert reasons.chill_amount(-27, -31.0, -24.0) is None
    iced = DistrictForecast(code=8, ice=0.37, ice_low=0.12, ice_high=0.52)
    found = _moved(0.4, WeatherClass.ICE, reasons.DayInputs(iced))
    assert found is not None
    (ice,) = found.reasons
    assert isinstance(ice, IceReason)
    assert ice.inches is None
    assert ice.points > 0  # the term's points whatever the words
    cold = DistrictForecast(code=12, feels=-27, feels_low=-33.0, feels_high=-22.0)
    found = _moved(0.5, WeatherClass.COLD, reasons.DayInputs(cold))
    assert found is not None
    (chill,) = found.reasons
    assert isinstance(chill, WindChillReason)
    assert chill.feels_like is None
    assert chill.points > 0


def test_overnight_is_said_only_of_snow_that_falls_overnight() -> None:
    # "10 to 11 inches overnight" must be true of every deciding school's overnight snow, not
    # only of the window's or of the district's 50% value.
    assert reasons.overnight((10.0, 11.0), 10.2, 10.1, 10.6)
    assert not reasons.overnight((10.0, 11.0), 5.4, 5.0, 5.9)  # half of it falls after 6 AM
    assert not reasons.overnight((0.0, 0.0), 0.0, 0.0, 0.0)
    assert not reasons.overnight((6.0, 9.0), None, None, None)
    assert not reasons.overnight((6.0, 9.0), 7.0, None, None)  # schools' parts not read
    assert not reasons.overnight(None, 7.0, 6.5, 7.5)  # no amount: never "overnight"
    # The district's 50% value is in the range, but one school's overnight snow is under it.
    assert not reasons.overnight((10.0, 12.0), 10.2, 9.8, 10.2)
    heavy = DistrictForecast(
        code=5,
        snow_low=10.0,
        snow_high=11.0,
        snow_night=5.4,
        snow_night_low=5.0,
        snow_night_high=5.9,
        ice=0.0,
    )
    found = _moved(0.6, WeatherClass.SNOW_WARNING, reasons.DayInputs(heavy))
    assert found is not None
    (line,) = found.reasons
    assert isinstance(line, SnowTotalReason)
    assert not line.overnight


def _two_schools(window: tuple[float, float], night: tuple[float, float]) -> history.RunValues:
    """A run over two schools of one district: each school's window snow ``window``, of which
    ``night`` falls in the periods ending 06 and 12 UTC and the rest by 18 UTC."""
    day = date(2026, 1, 7)
    run = ndfd.Run(world.utc("2026-01-07T02:30:00"), {}, world.utc("2026-01-07T02:40:00"))
    ends = ndfd.window_ends(day)
    values = history.RunValues(run)
    values.snow = {}
    for end in ends:
        if end.hour == 6:  # the first overnight period
            values.snow[end] = np.array([n / 2 for n in night])
        elif end.hour == 12:  # the second
            values.snow[end] = np.array([n - n / 2 for n in night])
        else:
            values.snow[end] = np.array([w - n for w, n in zip(window, night, strict=True)])
    values.ice = {end: np.zeros(2) for end in ends}
    values.feels = {ndfd.bus_time(day, "America/Chicago"): np.array([20.0, 21.0])}
    return values


def _two_school_line(window: tuple[float, float], night: tuple[float, float]) -> SnowTotalReason:
    schools = history.Schools(
        lat=np.array([39.1, 39.11]),
        lon=np.array([-94.58, -94.57]),
        district=np.array([0, 0], dtype=np.int64),
        districts=("2900001",),
        zone_of_district=("America/Chicago",),
    )
    day = date(2026, 1, 7)
    values = _two_schools(window, night)
    found = forecast_live.forecasts(
        schools,
        {"2900001": 1},
        (day,),
        world.utc("2026-01-07T12:00:00"),
        lambda _day: [values.run],
        _reading(values),
        0.5,
    )
    one = found.get(day, 1)
    assert one is not None
    assert (one.snow_night_low, one.snow_night_high) == pytest.approx(night)
    moved = _moved(0.6, WeatherClass.SNOW_WARNING, reasons.DayInputs(one))
    assert moved is not None
    (line,) = moved.reasons
    assert isinstance(line, SnowTotalReason)
    return line


def test_overnight_needs_every_schools_overnight_snow_in_the_range() -> None:
    # Two schools whose window totals (9.2 and 10.5 in) are in "9 to 11 inches", but whose
    # overnight parts are 7.99 and 9.09: the lighter school gets under 9 inches overnight, so
    # the line says "by" the window's end, never "overnight".
    line = _two_school_line((9.2, 10.5), (7.99, 9.09))
    assert (line.low, line.high) == (9.0, 11.0)
    assert not line.overnight
    # The 2302820 shape: window 10.79 to 11.38, overnight 9.8 to 10.2 (50% value 10.2).
    line = _two_school_line((10.79, 11.38), (9.8, 10.2))
    assert (line.low, line.high) == (10.0, 12.0)
    assert not line.overnight
    # Both schools' overnight snow in the range: "overnight" holds every school.
    line = _two_school_line((9.2, 10.5), (9.1, 10.4))
    assert (line.low, line.high) == (9.0, 11.0)
    assert line.overnight


def test_an_ice_line_never_says_more_ice_than_forecast() -> None:
    assert reasons.ice_words(0.12) == 0.1
    assert reasons.ice_words(0.27) == 0.2  # tenths, rounded down: never more than forecast
    assert reasons.ice_words(0.34) == 0.3
    assert reasons.ice_words(None) is None
    for inches in (0.1, 0.24, 0.25, 0.27, 1.3):
        IceReason(kind="ice", points=5, inches=reasons.ice_words(inches) or 0.0)  # tenths


def test_every_forecast_line_names_its_run() -> None:
    issued = datetime(2026, 1, 7, 2, 16, tzinfo=UTC)
    near = nowcast.Posted(share=0.75, status=Status.CLOSED, districts=(3, 1))
    heavy = DistrictForecast(
        code=5,
        snow_low=9.0,
        snow_high=13.0,
        snow_night=10.0,
        snow_night_low=9.4,
        snow_night_high=10.6,
        ice=0.0,
        run_time=issued,
    )
    found = _moved(0.62, WeatherClass.SNOW_WARNING, reasons.DayInputs(heavy, near))
    assert found is not None
    for line in found.reasons:
        if isinstance(line, SnowTotalReason):
            assert line.at == issued
            assert line.overnight
    iced = _moved(
        0.4, WeatherClass.ICE, reasons.DayInputs(DistrictForecast(8, ice=0.3, run_time=issued))
    )
    assert iced is not None
    assert all(isinstance(line, IceReason) and line.at == issued for line in iced.reasons)
    cold = _moved(
        0.5, WeatherClass.COLD, reasons.DayInputs(DistrictForecast(12, feels=-27, run_time=issued))
    )
    assert cold is not None
    assert all(isinstance(line, WindChillReason) and line.at == issued for line in cold.reasons)


def test_a_term_with_no_level_moves_nothing() -> None:
    assert _moved(0.74, WeatherClass.ADVISORY, reasons.DayInputs(DistrictForecast(code=13))) is None
    empty = nowcast.Posted(share=0.0, status=Status.CLOSED, districts=())
    assert _moved(0.3, WeatherClass.NONE, reasons.DayInputs(posted=empty)) is None
    assert _moved(0.3, WeatherClass.NONE, reasons.DayInputs()) is None


def test_the_neighbors_term_never_takes_away() -> None:
    for share in (0.1, 0.3, 0.6, 1.0):
        posted = nowcast.Posted(share=share, status=Status.REMOTE, districts=(2,))
        for p in (0.01, 0.2, 0.9, 0.99):
            found = _moved(p, WeatherClass.NONE, reasons.DayInputs(posted=posted))
            assert found is None or all(line.points > 0 for line in found.reasons)


def test_a_storm_forecast_lighter_than_most_storms_says_nothing() -> None:
    # The 9 PM window counts only the snow still to fall: a storm mostly fallen by then reads
    # light, so a warning day never takes a snow line away.
    for low, high, code in ((0.0, 1.0, 1), (1.0, 3.0, 2), (2.0, 4.0, 3)):
        light = DistrictForecast(code=code, snow_low=low, snow_high=high, ice=0.0)
        assert _moved(0.95, WeatherClass.SNOW_WARNING, reasons.DayInputs(light)) is None


def test_a_clamped_chance_still_adds_up() -> None:
    heavy = DistrictForecast(code=5, snow_low=12.0, snow_high=20.0, ice=0.0)
    near = nowcast.Posted(share=1.0, status=Status.CLOSED, districts=(1,))
    found = _moved(0.97, WeatherClass.SNOW_WARNING, reasons.DayInputs(heavy, near))
    assert found is not None
    assert found.p_no_school == 0.99
    assert 97 + sum(line.points for line in found.reasons) == 99


# --- the neighbors live -------------------------------------------------------------------------


def _closings(
    rows: Sequence[tuple[int, Status] | tuple[int, Status, Reason | None]],
    day: date,
    generated: datetime,
) -> ClosingsFile:
    found = sorted((row[0], row[1], row[2] if len(row) > 2 else None) for row in rows)
    gaps, last = [], -1
    for school, _status, _reason in found:
        gaps.append(school - last - 1)
        last = school
    shifted = sum(status == Status.DELAYED for _s, status, _r in found)
    return ClosingsFile(
        schema_version=1,
        generated_at=generated,
        directory=world.STAMP,
        days=(
            ClosingsDay(
                day=day,
                gaps=tuple(gaps),
                statuses=tuple(status for _s, status, _r in found),
                announced=tuple(None for _ in found),
                reasons=tuple(reason for _s, _status, reason in found),
                shifts=tuple(None for _ in range(shifted)),
                clocks=tuple(None for _ in range(shifted)),
            ),
        ),
    )


def _posted(
    built: ServeModel, closings: ClosingsFile, now: datetime, **extra: float
) -> nowcast.Neighbors:
    return nowcast.neighbors_posted(
        closings,
        stamp=world.STAMP,
        eligible=built.eligible,
        neighbors=built.neighbors,
        days=(date(2026, 1, 7),),
        now=now,
        max_age=timedelta(hours=1),
        **extra,
    )


def test_neighbors_posted_from_the_closings_file() -> None:
    built = build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    day = date(2026, 1, 7)
    now = world.utc("2026-01-07T04:00:00")
    assert built.neighbors[3]
    assert set(built.neighbors[3]) & {1, 2}
    # District 2's school (2) closed; district 1's (0) remote.
    closings = _closings([(2, Status.CLOSED), (0, Status.REMOTE)], day, now)
    found = _posted(built, closings, now)
    assert found.get(day, 1) is None  # district 1 posted itself: unknown
    three = found.get(day, 3)
    assert three is not None
    assert set(three.districts) <= {1, 2}
    assert three.share == pytest.approx(
        sum(1 for e in built.neighbors[3] if e in {1, 2}) / len(built.neighbors[3])
    )
    # District 3's school posted a delay: any status of its own makes its level unknown.
    delayed = _closings([(2, Status.CLOSED), (4, Status.DELAYED)], day, now)
    assert _posted(built, delayed, now).get(day, 3) is None
    # One school closed for a power outage, one for heat: neither district canceled for the
    # weather, so district 3 reads none of its neighbors as canceled.
    building = _closings(
        [(0, Status.CLOSED, Reason.POWER_OUTAGE), (2, Status.CLOSED, Reason.HEAT)], day, now
    )
    quiet = _posted(built, building, now).get(day, 3)
    assert quiet is not None
    assert (quiet.share, quiet.districts) == (0.0, ())
    # One of district 1's two eligible schools is half of it: it canceled at the label's
    # share (half), not at three quarters.
    assert len(built.eligible[1]) == 2
    one = _closings([(0, Status.CLOSED, Reason.WINTER_STORM)], day, now)
    at_half = _posted(built, one, now).get(day, 3)
    assert at_half is not None
    assert (1 in at_half.districts) == (1 in built.neighbors[3])
    above = _posted(built, one, now, share=0.75).get(day, 3)
    assert above is not None
    assert 1 not in above.districts
    stale = _posted(built, closings, now + timedelta(hours=2))
    assert stale.get(day, 3) is None
    assert nowcast.UNREAD.get(day, 3) is None


# --- the archive's snapshots and posting times --------------------------------------------------


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_a_snapshot_is_the_morning_pass_whatever_the_day_turned_out() -> None:
    window = posts.snapshot_window(date(2025, 1, 6), "America/Chicago", time(9, 30))
    assert window == (_at("2025-01-06T00:00:00"), _at("2025-01-06T12:00:00"))  # 6 AM CST
    captures = [_at(t) for t in ("2025-01-05T23:00", "2025-01-06T02:00", "2025-01-06T11:00")]
    # Posted after the pass, or never: the same snapshot, the last capture before 6 AM.
    assert posts.snapshot_time(captures, window, _at("2025-01-06T13:00")) == captures[2]
    assert posts.snapshot_time(captures, window, None) == captures[2]
    # Posted by the pass: the pass reads the district's own status, not the term.
    assert posts.snapshot_time(captures, window, _at("2025-01-06T10:00")) is None
    assert posts.snapshot_time(captures, window, _at("2025-01-06T01:00")) is None
    assert posts.snapshot_time(captures[:1], window, None) is None  # 5 PM: before the window
    share, named = posts.neighbor_share(
        ("a", "b", "c", "d"),
        {"a": _at("2025-01-06T01:00"), "b": _at("2025-01-06T05:00")},
        captures[1],
    )
    assert (share, named) == (0.25, ("a",))


def test_a_district_cancels_when_half_its_schools_close_for_the_weather() -> None:
    assert posts.counts_as_no_school(Status.CLOSED, None)
    assert posts.counts_as_no_school(Status.REMOTE, Reason.ICE)
    assert not posts.counts_as_no_school(Status.CLOSED, Reason.POWER_OUTAGE)
    assert not posts.counts_as_no_school(Status.DELAYED, None)
    times = [_at("2025-01-06T11:00"), _at("2025-01-06T09:00"), _at("2025-01-06T10:00")]
    assert posts.no_school_at(times[:1], 4, 0.5) is None  # one building of four
    assert posts.no_school_at(times[:2], 4, 0.5) == _at("2025-01-06T11:00")
    assert posts.no_school_at(times, 5, 0.5) == _at("2025-01-06T11:00")
    assert posts.no_school_at(times, 2, 0.5) == _at("2025-01-06T09:00")
    assert posts.no_school_at([], 0, 0.5) is None


def test_snapshots_count_only_kept_reads_of_lists_that_carry_the_district() -> None:
    day = date(2025, 1, 6)
    reads = [
        ReadRecord("s1", _at("2025-01-06T02:00"), "populated", 40),
        ReadRecord("s1", _at("2025-01-06T03:00"), "populated", 40),  # dropped by the replay
        ReadRecord("s2", _at("2025-01-06T04:00"), "empty", 0),  # s2 does not carry it
        ReadRecord("s1", _at("2025-01-06T05:00"), "deferred", 0),
    ]
    frame = posts.snapshots(
        [("2900001", day)],
        {"2900001": "America/Chicago"},
        {"s1": {"2900001": date(2024, 12, 1)}, "s2": {"2900002": date(2024, 12, 1)}},
        reads,
        {day: frozenset({("s1", _at("2025-01-06T02:00"))})},
        {("2900001", day): _at("2025-01-06T13:00")},
        time(9, 30),
    )
    assert frame["snapshot_at"].to_list() == [_at("2025-01-06T02:00")]


def test_the_usual_posting_time_needs_three_days() -> None:
    zone = {"2900001": "America/Chicago"}
    rows = [
        ("2900001", date(2025, 1, 6), _at("2025-01-06T11:30")),  # 5:30 AM CST
        (
            "2900001",
            date(2025, 1, 6),
            _at("2025-01-06T12:30"),
        ),  # later that day: the earliest counts
        ("2900001", date(2025, 2, 18), _at("2025-02-18T11:00")),  # 5:00 AM
    ]
    assert announce.usual_minutes(rows, zone, time(9, 30)) == {}
    rows.append(
        ("2900001", date(2025, 1, 9), _at("2025-01-09T02:00"))
    )  # 8:00 PM the evening before
    assert announce.usual_minutes(rows, zone, time(9, 30)) == {"2900001": 300}
    rows += [("2900001", date(2025, 1, 10), _at("2025-01-09T17:00"))] * 3  # 11 AM the day before
    assert announce.usual_minutes(rows, zone, time(9, 30)) == {"2900001": 300}
    assert announce.announces_at(300, date(2026, 1, 7), "America/Chicago") == _at(
        "2026-01-07T11:00"
    )
    assert announce.announces_at(-240, date(2026, 3, 9), "America/Chicago") == _at(
        "2026-03-09T01:00"
    )
    assert announce.announces_at(None, date(2026, 1, 7), "America/Chicago") is None


# --- backtest v2 --------------------------------------------------------------------------------


def test_backtest_v2_fits_each_season_on_earlier_seasons_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n = 400
    rng = np.random.default_rng(5)
    season = np.repeat(np.array([2018, 2019, 2020, 2021]), n // 4).astype(np.int64)
    snow = rng.integers(0, 6, n).astype(np.int64)
    rows = Rows(
        district=np.zeros(n, dtype=np.int64),
        situation=np.ones(n, dtype=np.int64) * 2,
        season=season,
        y=(rng.random(n) < 0.5).astype(float),
    )
    base = backtest_terms.Base(
        p=np.where(season == 2018, np.nan, 0.6),
        p_raw=np.full(n, 0.6),
        counted=np.full(n, int(WeatherClass.ADVISORY), dtype=np.int64),
    )
    levels = {term: np.full(n, UNKNOWN, dtype=np.int64) for term in terms.TERM_ORDER}
    levels[Term.SNOW_ADVISORY] = snow
    seen: list[tuple[int, ...]] = []
    real = backtest_terms.fit

    def spy(design: Design, seasons: np.ndarray) -> terms.Model:
        seen.append(tuple(sorted(set(seasons.tolist()))))
        return real(design, seasons)

    monkeypatch.setattr(backtest_terms, "fit", spy)
    folds = backtest_terms.walk_forward(rows, base, levels, [2020, 2021], world.CONFIG.model)
    assert [fold.season for fold in folds] == [2020, 2021]
    assert seen == [(2019,), (2019, 2020)]  # 2018 has no earlier season to fit its base on
    for fold in folds:
        assert set(rows.season[fold.rows].tolist()) == {fold.season}
        assert np.all((fold.p_terms >= 0.01) & (fold.p_terms <= 0.99))
    judged, _bins = backtest_terms.judge(
        folds,
        rows,
        [(0, 0)] * n,
        np.zeros(n, dtype=bool),
        bins=10,
        min_rows=300,
        apart=(2020,),
        min_storm_rows=150,
        test_seasons=(2019, 2020, 2021),
    )
    assert judged.storm_rows == sum(len(fold.rows) for fold in folds)
    assert judged.gated_seasons == ()  # 100 storm rows each: reported, not gated
    assert judged.worse_seasons == 0
    assert judged.no_storm_seasons == (2019,)
    kept = rows.season[np.concatenate([f.rows for f in folds])] != 2020
    assert judged.brier_base_without_apart == pytest.approx(
        backtest.brier(
            np.concatenate([f.p_base for f in folds])[kept],
            rows.y[np.concatenate([f.rows for f in folds])][kept],
        )
    )
    for fold in folds:  # G2 bins the terms on piece 1's unclamped base
        assert fold.p_terms_unclamped.size == fold.rows.size
    table = backtest_terms.advisory_table(folds, rows, base, snow)
    assert table[-1]["rows"] == judged.storm_rows
    final = folds[-1].model
    evidence = backtest_terms.advisory_evidence(folds, rows, base, levels, final)
    assert [season for season, *_rest in evidence.by_fold] == [2020, 2021]
    for (_season, count, *_rest), fold in zip(evidence.by_fold, folds, strict=True):
        assert count == len(fold.rows)
    report = backtest_terms.report_markdown(judged, folds, table, final, 0, evidence)
    assert "Piece 3 gate" in report
    assert "without 2020-21" in report
    assert "no storm rows: 2019-20" in report
    assert "reported, not gated" in report
    assert "What the advisory change rests on" in report
    assert "The season gate covers 0 of 2 seasons with storm rows (none)" in report


# --- the forecast at the snapshot ---------------------------------------------------------------


def test_the_snapshot_is_9_pm_the_evening_before_or_now() -> None:
    day = date(2026, 1, 7)
    evening = forecast_live.snapshot_at(day, "America/Chicago", world.utc("2026-01-07T12:00:00"))
    assert evening == world.utc("2026-01-07T03:00:00")
    early = world.utc("2026-01-06T20:00:00")
    assert forecast_live.snapshot_at(day, "America/Chicago", early) == early


def test_district_forecasts_from_one_run() -> None:
    schools = history.Schools(
        lat=np.array([39.1, 39.11, 39.12]),
        lon=np.array([-94.58, -94.57, -94.5]),
        district=np.array([0, 0, 1], dtype=np.int64),
        districts=("2900001", "2900002"),
        zone_of_district=("America/Chicago", "America/Chicago"),
    )
    day = date(2026, 1, 7)
    run = ndfd.Run(world.utc("2026-01-07T02:30:00"), {}, world.utc("2026-01-07T02:40:00"))
    ends = ndfd.window_ends(day)
    values = history.RunValues(run)
    values.snow = {
        ends[0]: np.array([2.0, 3.0, 0.2]),
        ends[1]: np.array([3.0, 4.5, 0.1]),
        ends[2]: np.zeros(3),
    }
    values.ice = {end: np.zeros(3) for end in ends}
    values.feels = {ndfd.bus_time(day, "America/Chicago"): np.array([8.0, 5.0, 20.0])}
    found = forecast_live.forecasts(
        schools,
        {"2900001": 1, "2900002": 2},
        (day,),
        world.utc("2026-01-07T12:00:00"),
        lambda _day: [run],
        lambda _run, _day: values,
        0.5,
    )
    assert found.problems == ()
    one = found.get(day, 1)
    assert one is not None
    assert (one.snow_low, one.snow_high) == (5.0, 7.5)  # its two schools, as read
    assert (one.ice_low, one.ice_high) == (0.0, 0.0)
    assert (one.feels_low, one.feels_high, one.feels) == (5.0, 8.0, 5)
    assert one.code == ndfd.Bucket.SNOW_6  # the 50% value: 7.5 inches
    assert one.snow_night == 7.5  # all of it in the periods ending 06 and 12 UTC
    assert (one.snow_night_low, one.snow_night_high) == (5.0, 7.5)  # each school's, as read
    assert one.run_time == run.time
    two = found.get(day, 2)
    assert two is not None
    assert two.code == 0
    assert two.snow_high == pytest.approx(0.3)  # never rounded up to a whole inch
    none = forecast_live.forecasts(
        schools,
        {"2900001": 1},
        (day,),
        world.utc("2026-01-07T12:00:00"),
        lambda _d: [],
        lambda _r, _d: values,
        0.5,
    )
    assert none.get(day, 1) is None
    assert none.problems
    unlisted = forecast_live.forecasts(
        schools,
        {"2900001": 1},
        (day,),
        world.utc("2026-01-07T12:00:00"),
        lambda _d: None,
        lambda _r, _d: values,
        0.5,
    )
    assert unlisted.problems == (f"{day}: the forecast runs did not list",)


# --- the serving pass ---------------------------------------------------------------------------


def _pass(reasons_on: bool, fit: Fit = Fit.WHOLE) -> tuple[Forecast, Forecast]:
    built = build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    with_terms(built, MODEL, {"2900001": 330})
    now = world.utc("2026-01-07T04:00:00")
    days = (date(2026, 1, 6), date(2026, 1, 7))
    classes = district_classes(built, storm(), index(), days, now, WINDOW, 0.5)
    light = DistrictForecast(code=1, snow_low=1.0, snow_high=2.0)
    heavy = DistrictForecast(
        code=5,
        snow_low=9.0,
        snow_high=12.0,
        snow_night=9.5,
        snow_night_low=9.2,
        snow_night_high=9.8,
        ice=0.0,
    )
    forecasts = Forecasts({days[1]: {1: heavy, 3: light}})
    near = nowcast.Neighbors({days[1]: {1: nowcast.Posted(0.5, Status.CLOSED, (2,))}}, read=True)
    made = forecast_file(
        built,
        classes,
        days,
        now,
        closed_on=lambda _day: None,
        last=None,
        forecasts=forecasts,
        posted=near,
        reasons=reasons_on,
        announces=reasons_on,
        fit=fit,
    )
    one, three = made.districts[1].days[1], made.districts[3].days[1]
    assert isinstance(one, Forecast)
    assert isinstance(three, Forecast)
    return one, three


def test_with_the_reasons_off_the_pass_is_the_base_alone() -> None:
    one, three = _pass(False)
    assert one.why.reasons == ()
    assert three.why.reasons == ()
    assert one.announces_at is None
    off, _ = _pass(True, Fit.NO_REASONS)  # no reasons, no record days: the base's chance
    assert (off.p_no_school, off.p_delay, off.why) == (one.p_no_school, one.p_delay, one.why)
    assert off.record is None


def test_with_the_reasons_on_the_lines_add_up_to_the_chance() -> None:
    base_one, _ = _pass(False)
    one, three = _pass(True)
    assert one.why.base == base_one.why.base
    assert one.why.reasons
    assert one.why.total() == round(one.p_no_school * 100)
    assert one.p_no_school > base_one.p_no_school
    assert {line.kind for line in one.why.reasons} <= {"snow_total", "neighbors"}
    assert one.announces_at == world.utc("2026-01-07T11:30:00")
    assert three.why.total() == round(three.p_no_school * 100)
    data = Forecast.model_validate_json(one.model_dump_json())
    assert data == one


def test_the_terms_file_round_trips() -> None:
    found = terms_file.TermsArtifact(
        schema_version=1,
        model_sha256="0" * 64,
        seasons=(2019, 2020),
        rows=10,
        penalty=1.0,
        terms={term.value: terms_file.entry_of(fit) for term, fit in MODEL.fits.items()},
        announce={"2900001": 330},
        gate=_FAILED,
    )
    again = terms_file.TermsArtifact.from_bytes(found.to_bytes())
    assert again.gate == _FAILED
    assert again == found
    assert again.to_bytes() == found.to_bytes()
    assert again.model().fits[Term.ICE].value(2) == pytest.approx(1.6)
    with pytest.raises(ValueError, match="only adds"):
        terms_file.TermsArtifact(
            schema_version=1, model_sha256="0" * 64, seasons=(), rows=0, penalty=1.0,
            terms={"ice": terms_file.TermEntry(levels=3, low=1, high=1, up=(0.1,), down=(0.2,))},
        )  # fmt: skip
    with pytest.raises(ValueError, match="evening before"):
        terms_file.TermsArtifact(
            schema_version=1, model_sha256="0" * 64, seasons=(), rows=0, penalty=1.0, terms={},
            announce={"2900001": 600},
        )  # fmt: skip


def test_term_levels_from_the_labels_codes_and_snapshots() -> None:
    day = date(2025, 1, 6)
    usable = pl.DataFrame({"district": ["a", "b", "c"], "day": [day, day, day]})
    codes = pl.DataFrame({"district": ["a", "b"], "day": [day, day], "code": [3, 7]})
    snaps = pl.DataFrame(
        {
            "district": ["a", "b", "c"],
            "day": [day] * 3,
            "snapshot_at": [_at("2025-01-06T10:00"), None, None],
        },
        schema={"district": pl.String, "day": pl.Date, "snapshot_at": pl.Datetime("us", "UTC")},
    )
    found_posts = pl.DataFrame(
        {
            "unit": ["b", "c"],
            "day": [day, day],
            "first_no_school": [_at("2025-01-06T09:00"), _at("2025-01-06T11:00")],
        },
        schema={"unit": pl.String, "day": pl.Date, "first_no_school": pl.Datetime("us", "UTC")},
    )
    found = term_rows.term_levels(usable, codes, snaps, found_posts, {"a": ("b", "c")})
    assert found[Term.SNOW_ADVISORY].tolist() == [3, UNKNOWN, UNKNOWN]
    assert found[Term.ICE].tolist() == [0, 1, UNKNOWN]
    assert found[Term.NEIGHBORS].tolist() == [2, UNKNOWN, UNKNOWN]  # b had posted by 10:00, c not


def test_the_size_ladder_drops_the_reasons_only_after_previous_chances() -> None:
    order = list(Fit)
    assert order.index(Fit.NO_REASONS) == order.index(Fit.NO_PREVIOUS) + 1
    assert [fit.reasons for fit in order] == [True, True, True, True, True, False, False, False]
    step = Fit.NO_REASONS
    assert (step.records, step.previous, step.private_previous, step.schools) == (
        False, False, False, True
    )  # fmt: skip


def test_the_committed_terms_name_the_committed_model_and_keep_their_signs() -> None:
    found = terms_file.load()
    assert found is not None
    model_bytes = artifact_module.ARTIFACT_PATH.read_bytes()
    assert found.model_sha256 == artifact_module.sha256_of(model_bytes)
    assert backtest_terms.signs_hold(found.model())
    assert set(found.terms) == {term.value for term in Term}


# --- training and serving move the same rows ----------------------------------------------------

# Reader-shaped amounts for each code: the schools' lowest and highest window snow around the
# district's 50% value, including no snow at all and ranges that cross the band.
_AMOUNTS: dict[int, tuple[tuple[float | None, float | None], ...]] = {
    0: ((0.0, 0.0), (0.0, 1.0), (0.0, 3.0)),
    1: ((0.0, 1.0), (1.0, 5.0)),
    2: ((1.0, 3.0), (2.0, 4.0)),
    3: ((3.0, 7.0),),
    4: ((6.0, 9.0), (2.0, 12.0)),
    5: ((7.0, 14.0),),
    6: ((0.0, 1.0),),
    7: ((0.0, 0.0),),
    8: ((0.0, 2.0),),
    9: ((0.0, 0.0),),
    12: ((0.0, 0.0),),
    13: ((None, None),),
}


def test_training_and_serving_give_every_row_the_same_levels_and_chance() -> None:
    # The rows a fit and backtest v2 move (term_rows from the history's codes) are the rows a
    # pass moves (reasons.levels from the live code), with the same terms and the same chance.
    day = date(2025, 1, 6)
    cases = [
        (f"d{n}", code, low, high)
        for n, (code, low, high) in enumerate(
            (code, low, high) for code, amounts in _AMOUNTS.items() for low, high in amounts
        )
    ]
    usable = pl.DataFrame({"district": [c[0] for c in cases], "day": [day] * len(cases)})
    codes = pl.DataFrame(
        {
            "district": [c[0] for c in cases],
            "day": [day] * len(cases),
            "code": [c[1] for c in cases],
        }
    )
    nothing = pl.DataFrame(
        schema={"district": pl.String, "day": pl.Date, "snapshot_at": pl.Datetime("us", "UTC")}
    )
    no_posts = pl.DataFrame(
        schema={"unit": pl.String, "day": pl.Date, "first_no_school": pl.Datetime("us", "UTC")}
    )
    trained = term_rows.term_levels(usable, codes, nothing, no_posts, {})
    for weather in (
        WeatherClass.ADVISORY,
        WeatherClass.SNOW_WARNING,
        WeatherClass.ICE,
        WeatherClass.COLD,
    ):
        for p_base in (0.12, 0.5, 0.74, 0.95):
            design = Design(
                offset=terms.logit(np.full(len(cases), p_base)),
                y=np.zeros(len(cases)),
                weather=np.full(len(cases), int(weather), dtype=np.int64),
                levels=trained,
            )
            p_train = terms.predict(MODEL, design)
            parts = terms.contributions(MODEL, design)
            for k, (_name, code, low, high) in enumerate(cases):
                inputs = reasons.DayInputs(
                    DistrictForecast(code=code, snow_low=low, snow_high=high, ice=0.3, feels=-25)
                )
                served = reasons.levels(inputs)
                assert served == Levels(
                    snow=int(trained[Term.SNOW_ADVISORY][k]),
                    ice=int(trained[Term.ICE][k]),
                    cold=int(trained[Term.COLD][k]),
                    neighbors=int(trained[Term.NEIGHBORS][k]),
                ), (code, low, high)
                moving = {t for t, v in parts.items() if v[k] != 0.0}
                assert set(MODEL.values(weather, weather, served)) == moving
                found = reasons.moved(p_base, 0.05, weather, weather, MODEL, inputs, 0.01, 0.99)
                shown = p_base if found is None else found.p_no_school
                expected = min(max(round(float(p_train[k]), 2), 0.01), 0.99)
                assert round(shown * 100) == round(expected * 100), (weather, p_base, code, low)
                if found is not None:
                    kinds = {type(line) for line in found.reasons}
                    assert len(kinds) <= len(moving)


def _reading(values: history.RunValues) -> forecast_live.ReadRun:
    return lambda _run, _day: values


def _words_hold_every_school(
    one: DistrictForecast,
    values: history.RunValues,
    mine: np.ndarray[tuple[int], np.dtype[np.bool_]],
    day: date,
    at: datetime,
) -> None:
    """What a line states holds every deciding school's forecast, recomputed from the run."""
    snow = terms.levels_of(one.code)[0]
    school = np.nan_to_num(ndfd.window_total(values.snow, day, at)[mine])  # type: ignore[index]
    assert (one.snow_low, one.snow_high) == (school.min(), school.max())
    words = reasons.snow_words(snow, one.snow_low, one.snow_high)
    if words is not None:
        assert words[0] <= school.min()
        assert school.max() <= words[1]
    # Each school's overnight part: "overnight" holds them all.
    part = np.zeros(int(mine.sum()))
    for end in ndfd.window_ends(day):
        if end.hour in forecast_live.OVERNIGHT_ENDS and end > at:
            part = part + np.nan_to_num(values.snow[end][mine])
    part = np.minimum(part, school)
    assert (one.snow_night_low, one.snow_night_high) == (part.min(), part.max())
    if reasons.overnight(words, one.snow_night, one.snow_night_low, one.snow_night_high):
        assert words is not None
        assert all(words[0] <= value <= words[1] for value in part)
    ice_said = reasons.ice_amount(one.ice, one.ice_low, one.ice_high)
    if ice_said is not None:
        read = np.nan_to_num(ndfd.window_total(values.ice, day, at)[mine])  # type: ignore[index]
        assert all(math.floor(v * 10 + 1e-9) / 10 == ice_said for v in read)
    chill = reasons.chill_amount(one.feels, one.feels_low, one.feels_high)
    if chill is not None:
        felt = values.feels[ndfd.bus_time(day, "America/Chicago")][mine]
        assert not np.isnan(felt).any()  # never a degree of a school not read
        assert all(round(v) == chill for v in felt)


def test_the_reader_gives_words_for_every_code_it_gives() -> None:
    # Random school amounts through the live reader: every district's code has words, the
    # words hold its 50% value, and its overnight snow is never more than its window's.
    rng = np.random.default_rng(7)
    count = 60
    schools = history.Schools(
        lat=np.full(count, 39.1) + rng.uniform(0, 0.3, count),
        lon=np.full(count, -94.6) + rng.uniform(0, 0.3, count),
        district=np.repeat(np.arange(12, dtype=np.int64), 5),
        districts=tuple(f"29{n:05d}" for n in range(12)),
        zone_of_district=("America/Chicago",) * 12,
    )
    day = date(2026, 1, 7)
    run = ndfd.Run(world.utc("2026-01-07T02:30:00"), {}, world.utc("2026-01-07T02:40:00"))
    ends = ndfd.window_ends(day)
    at = forecast_live.snapshot_at(day, "America/Chicago", world.utc("2026-01-07T12:00:00"))
    for trial in range(20):
        values = history.RunValues(run)
        scale = (0.2, 1.0, 3.0, 6.0)[trial % 4]
        values.snow = {end: rng.uniform(0, scale, count) for end in ends}
        if trial % 5 == 0:
            values.snow[ends[1]][rng.integers(0, count, 6)] = np.nan
        values.ice = {end: rng.uniform(0, 0.12 * (trial % 3), count) for end in ends}
        values.feels = {ndfd.bus_time(day, "America/Chicago"): rng.uniform(-30, 30, count)}
        if trial % 4 == 1:
            values.feels[ndfd.bus_time(day, "America/Chicago")][rng.integers(0, count, 4)] = np.nan
        found = forecast_live.forecasts(
            schools,
            {d: i for i, d in enumerate(schools.districts)},
            (day,),
            world.utc("2026-01-07T12:00:00"),
            lambda _day: [run],
            _reading(values),
            0.5,
        )
        for k in range(12):
            one = found.get(day, k)
            assert one is not None
            snow, ice, cold = terms.levels_of(one.code)
            if ice > 0:
                assert one.ice is not None
                assert (reasons.ice_words(one.ice) or 0.0) >= 0.1
            if cold > 0:
                assert one.feels is not None
            if snow < 0:
                continue
            assert one.snow_low is not None, (trial, k, one)
            assert one.snow_night is not None
            assert one.snow_high is not None
            assert one.snow_night <= one.snow_high
            assert one.snow_night_low is not None
            assert one.snow_night_high is not None
            _words_hold_every_school(one, values, schools.district == k, day, at)


def test_the_chance_holds_across_the_10_pm_edge() -> None:
    # The forecast lines keep the 9 PM forecast all night, so a pass at 9:37 PM, 10:37 PM or
    # 6 AM reads the same run and moves the chance the same: no change is shown, as nothing in
    # the weather changed.
    schools = history.Schools(
        lat=np.array([39.1]),
        lon=np.array([-94.58]),
        district=np.array([0], dtype=np.int64),
        districts=("2900001",),
        zone_of_district=("America/Chicago",),
    )
    day = date(2026, 1, 7)
    early = ndfd.Run(world.utc("2026-01-07T01:16:00"), {}, world.utc("2026-01-07T01:26:00"))
    nine = ndfd.Run(world.utc("2026-01-07T02:16:00"), {}, world.utc("2026-01-07T02:26:00"))
    later = ndfd.Run(world.utc("2026-01-07T05:16:00"), {}, world.utc("2026-01-07T05:26:00"))
    read: list[datetime] = []

    def values_of(run: ndfd.Run, found: date) -> history.RunValues:
        read.append(run.time)
        values = history.RunValues(run)
        ends = ndfd.window_ends(found)
        values.snow = {end: np.array([0.1]) for end in ends}
        values.ice = {end: np.zeros(1) for end in ends}
        values.feels = {ndfd.bus_time(found, "America/Chicago"): np.array([20.0])}
        return values

    seen = []
    for now in ("2026-01-07T03:37:00", "2026-01-07T04:37:00", "2026-01-07T12:00:00"):
        found = forecast_live.forecasts(
            schools,
            {"2900001": 1},
            (day,),
            world.utc(now),
            lambda _d: [early, nine, later],
            values_of,
            0.5,
        )
        one = found.get(day, 1)
        assert one is not None
        seen.append(one)
    assert {one.run_time for one in seen} == {nine.time}
    assert len(set(seen)) == 1
    chances = [_moved(0.74, WeatherClass.ADVISORY, reasons.DayInputs(one)) for one in seen]
    assert chances[0] is not None
    assert len({c.p_no_school for c in chances if c is not None}) == 1
    assert all(c is not None for c in chances)


def test_a_pass_across_10_pm_shows_no_previous_chance() -> None:
    built = build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    with_terms(built, MODEL, {})
    days = (date(2026, 1, 6), date(2026, 1, 7))
    issued = world.utc("2026-01-07T02:16:00")
    light = DistrictForecast(code=1, snow_low=1.0, snow_high=2.0, run_time=issued)
    forecasts = Forecasts({days[1]: {1: light}})

    def made(now: datetime, last: PredictionsFile | None) -> PredictionsFile:
        classes = district_classes(built, storm(), index(), days, now, WINDOW, 0.5)
        return forecast_file(
            built,
            classes,
            days,
            now,
            closed_on=lambda _day: None,
            last=last,
            forecasts=forecasts,
            reasons=True,
        )

    first = made(world.utc("2026-01-07T03:37:00"), None)
    second = made(world.utc("2026-01-07T04:37:00"), first)
    one = second.districts[1].days[1]
    before = first.districts[1].days[1]
    assert isinstance(one, Forecast)
    assert isinstance(before, Forecast)
    assert one.p_no_school == before.p_no_school
    assert one.previous is None
    assert one.why.reasons == before.why.reasons


_PASSED = terms_file.GateRecord(passed=True, gain=0.031, report_sha256="c" * 64)
_FAILED = terms_file.GateRecord(passed=False, gain=-0.063, report_sha256="c" * 64)


def test_the_terms_serve_only_over_the_archive_rates_they_were_fit_on() -> None:
    from snowlight.predict.cli import terms_refused  # noqa: PLC0415

    assert terms_refused("a" * 64, "a" * 64, learned=False, gate=_PASSED) is None
    assert terms_refused("a" * 64, "b" * 64, learned=False, gate=_PASSED) is not None
    assert terms_refused("a" * 64, None, learned=False, gate=_PASSED) is not None
    refused = terms_refused("a" * 64, "a" * 64, learned=True, gate=_PASSED)
    assert refused is not None
    assert "learned" in refused
    # An override never serves terms over another model or over learned rates.
    assert (
        terms_refused("a" * 64, "b" * 64, learned=False, gate=_FAILED, override="lead") is not None
    )
    assert (
        terms_refused("a" * 64, "a" * 64, learned=True, gate=_FAILED, override="lead") is not None
    )


def test_terms_whose_gate_failed_serve_only_under_the_leads_override() -> None:
    from snowlight.predict.cli import terms_refused  # noqa: PLC0415

    refused = terms_refused("a" * 64, "a" * 64, learned=False, gate=_FAILED)
    assert refused is not None
    assert "gate" in refused
    assert "-6.3%" in refused
    unrecorded = terms_refused("a" * 64, "a" * 64, learned=False, gate=None)
    assert unrecorded is not None
    assert "gate" in unrecorded
    assert terms_refused("a" * 64, "a" * 64, learned=False, gate=_FAILED, override="  ") is not None
    named = "lead 2026-11-02"
    assert terms_refused("a" * 64, "a" * 64, learned=False, gate=_FAILED, override=named) is None
    assert terms_refused("a" * 64, "a" * 64, learned=False, gate=None, override=named) is None
    # The committed config sets no override, and the committed terms record their failing gate,
    # so turning the reasons on alone still serves the base alone.
    assert world.CONFIG.serve.reasons_gate_override == ""
    from snowlight.predict.config import CONFIG_PATH, PredictConfig  # noqa: PLC0415

    committed_config = PredictConfig.load(CONFIG_PATH)
    assert committed_config.serve.reasons_gate_override == ""
    assert not committed_config.serve.reasons
    found = terms_file.load()
    assert found is not None
    assert found.gate is not None
    assert not found.gate.passed
    assert terms_refused(
        found.model_sha256,
        found.model_sha256,
        learned=False,
        gate=found.gate,
        override=committed_config.serve.reasons_gate_override,
    ) is not None  # fmt: skip


def test_the_web_ends_the_forecast_window_where_the_pipeline_does() -> None:
    # The web words "by 1 PM" from the window's last period end; the pipeline counts to it.
    import re  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    chance = Path(__file__).resolve().parents[3] / "web" / "src" / "app" / "chance.ts"
    found = re.search(r"FORECAST_WINDOW_END_UTC_HOUR = (\d+);", chance.read_text())
    assert found is not None
    assert int(found.group(1)) == ndfd.WINDOW_END_HOURS[-1]
    assert ndfd.WINDOW_END_HOURS[:2] == forecast_live.OVERNIGHT_ENDS
