"""The forecast adjustment (advisory-sane L5, Addendum A item 3): the terms move the chance the
right way and by bounded amounts, the same inches matter more where snow is rare, each
district's days still average its class level, the lines are true, and a missing or unknown
forecast leaves the class level."""

import gzip
import itertools
import json
import math
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import polars as pl
import pytest

from predict import test_forecast_history as fh_test
from predict import world
from snowlight.predict import anchor as an
from snowlight.predict import cli, forecast_live, ndfd, outlook_live, serve
from snowlight.predict import forecast_adjust as fa
from snowlight.predict import forecast_history as history
from snowlight.predict.anchor_labels import serving_anchor
from snowlight.predict.artifact import ARTIFACT_PATH, ModelArtifact
from snowlight.predict.config import PredictConfig
from snowlight.predict.exposure import Exposure
from snowlight.predict.forecast_values import (
    NO_FORECASTS,
    DistrictForecast,
    Forecasts,
    SnowPart,
    commute_share,
)
from snowlight.predict.geography import REGION_OF
from snowlight.predict.opens import SaidOpen
from snowlight.predict.serve import SITUATION_POSITION, ServeModel, build_model, forecast_file
from snowlight.predict.situations import SITUATIONS, Situation, WeatherClass
from snowlight.schemas.predictions import (
    ClassBase,
    Forecast,
    IceReason,
    PredictionsFile,
    SnowHoursReason,
    SnowTotalReason,
    TimingReason,
    WindChillReason,
)

CONFIG = PredictConfig.load()
SETTINGS = fa.AdjustSettings.of(CONFIG)
DAY = date(2026, 1, 14)
EAST = "America/New_York"
RUN = world.utc("2026-01-14T01:00:00")
SNAPSHOT = world.utc("2026-01-14T02:00:00")  # 9 PM EST the evening before
ATLANTA_USUAL = 0.68  # the committed climate's advisory usual snow at a 10% level (below)
BUFFALO_USUAL = 1.93
ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")


def parts(day: date, at: datetime, amounts: tuple[float, ...]) -> tuple[SnowPart, ...]:
    """The window's three periods' parts still to come at ``at``, with ``amounts`` (the
    district's 50% values of each part, as the reader gives them)."""
    found = []
    for end, amount in zip(ndfd.window_ends(day), amounts, strict=True):
        if end > at:
            found.append(SnowPart(max(end - ndfd.PERIOD, at), end, amount))
    return tuple(found)


def commute_of(found: Sequence[SnowPart], zone: str, day: date = DAY) -> float:
    """A one-school district's snow in the commute hours: each period's by its share in them."""
    return sum(part.snow * commute_share(part.start, part.end, day, zone) for part in found)


def forecast(  # noqa: PLR0913 - a forecast's parts
    snow: float,
    *,
    split: tuple[float, float, float] | None = None,
    ice: float = 0.0,
    feels: int = 25,
    code: int | None = None,
    spread: float = 0.0,
) -> DistrictForecast:
    """A district's forecast at the 9 PM EST snapshot: ``snow`` inches still to come, by default
    even over the window's time still to come (``split``: the share of each period)."""
    hours = [(e - max(e - ndfd.PERIOD, SNAPSHOT)).total_seconds() for e in ndfd.window_ends(DAY)]
    shares = split or tuple(h / sum(hours) for h in hours)
    amounts = tuple(snow * share for share in shares)
    if code is None:
        snow_code = int(ndfd.snow_bucket(np.array([snow]))[0])
        code = snow_code if snow_code > 0 else 0
    return DistrictForecast(
        code=code,
        snow_low=max(snow - spread, 0.0),
        snow_high=snow + spread,
        snow_night=snow * sum(shares[:2]),
        snow_night_low=max(snow - spread, 0.0) * sum(shares[:2]),
        snow_night_high=(snow + spread) * sum(shares[:2]),
        ice=ice,
        ice_low=ice,
        ice_high=ice,
        feels=feels,
        feels_low=float(feels),
        feels_high=float(feels),
        run_time=RUN,
        snow=snow,
        snow_parts=parts(DAY, SNAPSHOT, amounts),
        snow_commute=commute_of(parts(DAY, SNAPSHOT, amounts), EAST),
    )


def zoned(
    zone: str, amounts: Sequence[float], *, ice: float = 0.0, feels: int = 25
) -> DistrictForecast:
    """A district's forecast in ``zone`` at its 9 PM snapshot: ``amounts`` inches in each window
    period still to come (as many as there are), every school alike."""
    at = fa.snapshot(DAY, zone)
    found = parts(DAY, at, tuple(amounts) + (0.0,) * (3 - len(amounts)))
    snow = sum(part.snow for part in found)
    return DistrictForecast(
        code=max(int(ndfd.snow_bucket(np.array([snow]))[0]), 0),
        snow_low=snow,
        snow_high=snow,
        snow_night=0.0,
        snow_night_low=0.0,
        snow_night_high=0.0,
        ice=ice,
        ice_low=ice,
        ice_high=ice,
        feels=feels,
        feels_low=float(feels),
        feels_high=float(feels),
        run_time=at,
        snow=snow,
        snow_parts=found,
        snow_commute=commute_of(found, zone),
    )


def periods(zone: str) -> int:
    at = fa.snapshot(DAY, zone)
    return sum(end > at for end in ndfd.window_ends(DAY))


def chance(
    p0: float, found: DistrictForecast | None, usual: float, klass: str = "advisory"
) -> float:
    moved = fa.adjusted(p0, 0.11, klass, usual, found, DAY, EAST, SETTINGS, 0.01, 0.99)
    return p0 if moved is None else moved.p_no_school


def total(found: DistrictForecast, usual: float, klass: str = "advisory") -> float:
    terms = fa.day_terms(found, usual, klass, DAY, EAST, SETTINGS)
    assert terms is not None
    return sum(terms.values.values())


# --- direction and size -------------------------------------------------------------------------


def test_more_snow_raises_the_chance_and_a_dusting_lowers_it() -> None:
    amounts = [0.0, 0.1, 0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 9.0, 14.0]
    moved = [total(forecast(s), ATLANTA_USUAL) for s in amounts]
    assert all(b >= a - 1e-12 for a, b in itertools.pairwise(moved))  # never down with more snow
    assert total(forecast(0.2), ATLANTA_USUAL) < 0 < total(forecast(2.0), ATLANTA_USUAL)
    assert chance(0.10, forecast(0.1), ATLANTA_USUAL) < 0.10 < chance(0.10, forecast(4), 0.67)


def test_the_same_inches_matter_more_where_snow_is_rare() -> None:
    for inches in (1.0, 2.0, 4.0, 6.0):
        assert total(forecast(inches), ATLANTA_USUAL) > total(forecast(inches), BUFFALO_USUAL)
    # The worked example: a dusting and 6 inches under a 10% advisory level.
    assert chance(0.10, forecast(0.2), ATLANTA_USUAL) == 0.06
    assert chance(0.10, forecast(0.2), BUFFALO_USUAL) == 0.05  # at the -0.7 bound (PHYS-R3-S2)
    assert chance(0.10, forecast(6.0), ATLANTA_USUAL) == 0.38
    assert chance(0.10, forecast(6.0), BUFFALO_USUAL) == 0.23


def test_snow_into_the_commute_raises_it_and_snow_ending_by_evening_lowers_it() -> None:
    usual = BUFFALO_USUAL
    even = total(forecast(3.0), usual)
    overnight = total(forecast(3.0, split=(0.0, 1.0, 0.0)), usual)  # 1 AM to 7 AM EST
    evening = total(forecast(3.0, split=(1.0, 0.0, 0.0)), usual)  # 9 PM to 1 AM EST
    afternoon = total(forecast(3.0, split=(0.0, 0.0, 1.0)), usual)  # 7 AM to 1 PM EST
    assert afternoon < even < overnight
    assert evening < overnight
    terms = fa.day_terms(
        forecast(3.0, split=(0.0, 0.0, 1.0)), usual, "advisory", DAY, EAST, SETTINGS
    )
    assert terms is not None
    assert terms.values[fa.Term.TIMING] < 0
    assert terms.period is not None
    assert terms.heaviest
    assert terms.period.end == ndfd.window_ends(DAY)[2]
    # Timing phases in with the snow: a dusting's is smaller than an inch's, and none moves
    # the even snow.
    light = fa.day_terms(
        forecast(0.3, split=(0.0, 1.0, 0.0)), usual, "advisory", DAY, EAST, SETTINGS
    )
    inch = fa.day_terms(
        forecast(1.0, split=(0.0, 1.0, 0.0)), usual, "advisory", DAY, EAST, SETTINGS
    )
    assert light is not None
    assert inch is not None
    assert 0 < light.values[fa.Term.TIMING] < inch.values[fa.Term.TIMING]
    flat = fa.day_terms(forecast(3.0), usual, "advisory", DAY, EAST, SETTINGS)
    assert flat is not None
    assert abs(flat.values.get(fa.Term.TIMING, 0.0)) < 0.01


@pytest.mark.parametrize("zone", [*ZONES, "America/Anchorage", "Pacific/Honolulu"])
def test_snow_between_10_pm_and_9_am_never_lowers_the_chance_in_any_zone(zone: str) -> None:
    # PHYS-S3: all the snow in one period wholly or mostly (80% or more of its hours) inside
    # 10 PM to 9 AM on the school's clock: never a timing term that lowers.
    count = periods(zone)
    for k in range(count):
        amounts = [0.0] * count
        amounts[k] = 4.0
        found = zoned(zone, amounts)
        part = found.snow_parts[k]
        inside = fa.commute_weight(part.start, part.end, DAY, zone, SETTINGS)
        terms = fa.day_terms(found, 3.0, "advisory", DAY, zone, SETTINGS)
        assert terms is not None
        if inside >= SETTINGS.timing_even_max:
            assert terms.values.get(fa.Term.TIMING, 0.0) >= 0, (zone, part)
    # The overnight period itself raises it in the lower 48.
    if zone in ZONES:
        local = [
            p for p in zoned(zone, [1.0] * count).snow_parts
            if p.start.astimezone(ZoneInfo(zone)).hour in {22, 23, 0, 1}
            and (p.end - p.start) == ndfd.PERIOD
        ]  # fmt: skip
        assert local
        amounts = [4.0 if p in local else 0.0 for p in zoned(zone, [1.0] * count).snow_parts]
        terms = fa.day_terms(zoned(zone, amounts), 3.0, "advisory", DAY, zone, SETTINGS)
        assert terms is not None
        assert terms.values[fa.Term.TIMING] > 0


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("klass", ["advisory", "warning"])
def test_more_snow_in_any_period_more_ice_or_more_cold_never_lowers_the_chance(
    zone: str, klass: str
) -> None:
    # PHYS-B1: adding snow to any one period never lowers the day's total or its published
    # chance (the timing line names a period on its side, never drops its term).
    grid = (0.0, 0.2, 0.5, 1.0, 3.0, 8.0)
    count = periods(zone)
    for usual in (0.3, 1.67, 4.28):
        for base in itertools.product(grid, repeat=count):
            found = zoned(zone, list(base))
            before = fa.day_terms(found, usual, klass, DAY, zone, SETTINGS)
            assert before is not None
            low = sum(before.values.values())
            p0 = 0.38 if klass == "warning" else 0.16
            shown = fa.adjusted(p0, 0.1, klass, usual, found, DAY, zone, SETTINGS, 0.01, 0.99)
            was = p0 if shown is None else shown.p_no_school
            for k in range(count):
                for add in (0.01, 0.25, 2.0):
                    more = list(base)
                    more[k] += add
                    bigger = zoned(zone, more)
                    after = fa.day_terms(bigger, usual, klass, DAY, zone, SETTINGS)
                    assert after is not None
                    assert sum(after.values.values()) >= low - 1e-12, (base, k, add)
                    now = fa.adjusted(
                        p0, 0.1, klass, usual, bigger, DAY, zone, SETTINGS, 0.01, 0.99
                    )
                    assert (p0 if now is None else now.p_no_school) >= was
            for ice in (0.005, 0.01, 0.1, 0.3):
                iced = fa.day_terms(
                    zoned(zone, list(base), ice=ice), usual, klass, DAY, zone, SETTINGS
                )
                assert iced is not None
                assert sum(iced.values.values()) >= low - 1e-12
            for feels in (10, -5, -30):
                cold = fa.day_terms(
                    zoned(zone, list(base), feels=feels), usual, klass, DAY, zone, SETTINGS
                )
                assert cold is not None
                assert sum(cold.values.values()) >= low - 1e-12


def test_the_critic_s_cases_no_longer_fall_when_snow_is_added_after_6_am() -> None:
    # PHYS-B1's probe: Central, 9 PM snapshot, [evening, overnight, 6 AM to noon].
    zone = "America/Chicago"
    for klass, p0, usual, before, after in (
        ("warning", 0.38, 4.28, [0, 8, 8], [0, 8, 8.25]),
        ("warning", 0.38, 4.28, [0, 4, 4], [0, 4, 4.25]),
        ("warning", 0.45, 6.0, [0, 8, 8], [0, 8, 8.25]),
        ("advisory", 0.16, 3.0, [0, 8, 8], [0, 8, 8.25]),
        ("advisory", 0.16, 3.0, [0, 4, 4], [0, 4, 4.25]),
    ):
        was = fa.adjusted(
            p0, 0.1, klass, usual, zoned(zone, before), DAY, zone, SETTINGS, 0.01, 0.99
        )
        now = fa.adjusted(
            p0, 0.1, klass, usual, zoned(zone, after), DAY, zone, SETTINGS, 0.01, 0.99
        )
        assert was is not None
        assert now is not None
        assert now.p_no_school >= was.p_no_school
        # The timing line stays: where the heaviest snow by the hour is after 6 AM, it names
        # the overnight snow that raises the chance instead.
        hours = [r for r in now.reasons if isinstance(r, SnowHoursReason | TimingReason)]
        assert len(hours) <= 1
        for line in hours:
            assert line.points > 0
            assert line.start.astimezone(ZoneInfo(zone)).hour == 0


# --- many deciding schools, through the reader (PHYS-R2-B1) -------------------------------------


def read_districts(zone: str, amounts: Sequence[np.ndarray]) -> list[DistrictForecast | None]:
    """Each district's forecast through the live reader (:func:`forecast_live.forecasts`, its
    50% values over the deciding schools): ``amounts[d]`` is district ``d``'s schools by the
    window's three periods (inches in each whole period, as a run holds them)."""
    district = np.concatenate(
        [np.full(len(item), d, dtype=np.int64) for d, item in enumerate(amounts)]
    )
    stacked = np.concatenate(list(amounts))
    count = stacked.shape[0]
    leaids = tuple(f"{d:07d}" for d in range(len(amounts)))
    schools = history.Schools(
        lat=np.full(count, 40.0),
        lon=np.full(count, -90.0),
        district=district,
        districts=leaids,
        zone_of_district=(zone,) * len(amounts),
    )
    at = fa.snapshot(DAY, zone)
    run = ndfd.Run(at - timedelta(minutes=30), {}, at - timedelta(minutes=20))
    values = history.RunValues(run)
    ends = ndfd.window_ends(DAY)
    values.snow = {end: stacked[:, k].copy() for k, end in enumerate(ends)}
    values.ice = {end: np.zeros(count) for end in ends}
    values.feels = {ndfd.bus_time(DAY, zone): np.full(count, 25.0)}
    found = forecast_live.forecasts(
        schools,
        {leaid: d for d, leaid in enumerate(leaids)},
        (DAY,),
        world.utc("2026-01-14T14:00:00"),
        lambda _d: [run],
        lambda _r, _d: values,
        0.5,
    )
    return [found.get(DAY, d) for d in range(len(amounts))]


@pytest.mark.parametrize("zone", ZONES)
def test_more_snow_at_any_school_in_any_period_never_lowers_a_district_s_chance(zone: str) -> None:
    # PHYS-R2-B1: districts of 2 to 7 deciding schools, each school's amounts its own, through
    # the reader's 50% values: adding snow to any period at one school, or at every school,
    # never lowers the day's total or its published chance, in either class.
    rng = np.random.default_rng(7)
    size = 240
    amounts = [
        rng.choice([0.0, 0.0, 0.1, 0.5, 1.0, 2.0, 4.0, 8.0], size=(n, 3)) * rng.random((n, 3))
        for n in rng.integers(2, 8, size=size)
    ]
    usual = rng.choice([0.3, 0.7, 1.5, 3.0, 5.0], size=size)
    levels = {"advisory": rng.choice([0.06, 0.1, 0.16], size=size),
              "warning": rng.choice([0.3, 0.45, 0.6], size=size)}  # fmt: skip
    one = [int(rng.integers(0, len(item))) for item in amounts]

    def measured(found: list[DistrictForecast | None]) -> dict[str, list[tuple[float, float]]]:
        out: dict[str, list[tuple[float, float]]] = {}
        for klass, p0 in levels.items():
            rows = []
            for d, item in enumerate(found):
                assert item is not None
                terms = fa.day_terms(item, float(usual[d]), klass, DAY, zone, SETTINGS)
                assert terms is not None
                moved = fa.adjusted(
                    float(p0[d]), 0.1, klass, float(usual[d]), item, DAY, zone, SETTINGS,
                    0.01, 0.99,
                )  # fmt: skip
                rows.append(
                    (sum(terms.values.values()), p0[d] if moved is None else moved.p_no_school)
                )
            out[klass] = rows
        return out

    base = measured(read_districts(zone, amounts))
    for period in range(3):
        for every in (False, True):
            for add in (0.1, 1.0, 3.0):
                more = []
                for d, item in enumerate(amounts):
                    grown = item.copy()
                    if every:
                        grown[:, period] += add
                    else:
                        grown[one[d], period] += add
                    more.append(grown)
                after = measured(read_districts(zone, more))
                for klass in levels:
                    for d, (was, now) in enumerate(zip(base[klass], after[klass], strict=True)):
                        assert now[0] >= was[0] - 1e-12, (klass, d, period, every, add)
                        assert now[1] >= was[1], (klass, d, period, every, add)


def test_the_critic_s_two_school_cases_no_longer_fall() -> None:
    # PHYS-R2-B1's probe: two deciding schools, snow added at one of them.
    for zone, klass, p0, usual, school, before, after in (
        ("America/New_York", "advisory", 0.12, 1.0, [0, 1.5, 0.1], [0, 3.0, 0.2], [0, 3.0, 2.1]),
        ("America/Chicago", "advisory", 0.12, 1.5, [0.3, 2.0, 0.4], [0.4, 4.0, 0.5],
         [0.4, 4.0, 2.6]),
        ("America/Los_Angeles", "warning", 0.45, 0.3, [0, 0.55, 0.51], [0, 1.48, 0.72],
         [6.0, 1.48, 0.72]),
    ):  # fmt: skip
        was, now = (
            read_districts(zone, [np.array([school, other])])[0] for other in (before, after)
        )
        assert was is not None
        assert now is not None
        assert now.snow is not None
        assert was.snow is not None
        assert now.snow >= was.snow
        moved = [
            fa.adjusted(p0, 0.1, klass, usual, item, DAY, zone, SETTINGS, 0.01, 0.99)
            for item in (was, now)
        ]
        shown = [p0 if item is None else item.p_no_school for item in moved]
        assert shown[1] >= shown[0], (zone, shown)


def test_the_reader_weighs_each_school_s_hours_before_the_district_s_value() -> None:
    zone = "America/Los_Angeles"
    # PHYS-R2-S3's case: the periods' 50% values (0.09 in all) stand for none of the 5.4 in.
    found = read_districts(zone, [np.array([[0, 0.09, 5.31], [0, 0, 0], [5.37, 3.21, 0]])])[0]
    assert found is not None
    assert found.snow is not None
    assert found.snow_commute is not None
    assert 0 < found.snow_commute <= found.snow
    assert sum(part.snow for part in found.snow_parts) < fa.NAMED_SHARE * found.snow
    for klass, p0, usual in (("advisory", 0.12, 1.5), ("warning", 0.45, 3.0)):
        terms = fa.day_terms(found, usual, klass, DAY, zone, SETTINGS)
        assert terms is not None
        # No hours are named from periods that stand for none of the snow: the timing's part
        # is said with the snow's line, and the chance is the same.
        assert fa.Term.TIMING not in terms.values
        assert terms.period is None
        moved = fa.adjusted(p0, 0.1, klass, usual, found, DAY, zone, SETTINGS, 0.01, 0.99)
        assert moved is not None
        assert all(r.kind in {"snow_total", "wind_chill"} for r in moved.reasons)
        assert sum(r.points for r in moved.reasons) == round(moved.p_no_school * 100) - round(
            p0 * 100
        )
    # Every school alike: the district's values are its schools', and the commute snow is the
    # snow in the commute hours.
    alike = read_districts(zone, [np.array([[1.0, 2.0, 3.0]] * 3)])[0]
    assert alike is not None
    assert alike.snow_commute == pytest.approx(commute_of(alike.snow_parts, zone))


def test_a_deciding_school_with_no_forecast_leaves_the_district_at_its_class_level() -> None:
    # S-R2-1: a school off the grid (Alaska, Hawaii) or masked is unknown, never no snow.
    zone = "America/New_York"
    found = read_districts(zone, [np.array([[1.0, 2.0, 0.0], [np.nan, np.nan, np.nan]])])[0]
    assert found is not None
    assert found.snow is None
    assert found.snow_commute is None
    assert fa.day_terms(found, 1.0, "advisory", DAY, zone, SETTINGS) is None
    assert fa.adjusted(0.1, 0.1, "advisory", 1.0, found, DAY, zone, SETTINGS, 0.01, 0.99) is None


def test_even_snow_s_timing_is_in_the_solve_where_the_cap_holds_the_even_weight() -> None:
    # PHYS-R2-S2: the even weight's cap gives even snow a timing term in Alaska, Hawaii and
    # the West; the solve counts it there, so their days still average the class level.
    for zone in ("America/New_York", "America/Chicago", "America/Denver"):
        assert fa.even_factor(zone, SETTINGS) == 1.0
    for zone in ("America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu"):
        assert fa.even_factor(zone, SETTINGS) > 1.0
    zone = "America/Anchorage"
    even = np.array([fa.even_factor(zone, SETTINGS)])
    counts = np.array([[20.0, 10, 8, 4, 2, 1] + [0.0] * 7])
    scale = np.array([1.0])
    p0 = np.array([0.12])
    usual = fa.usual_snow(p0, counts, scale, "advisory", SETTINGS, even=even)
    assert np.isfinite(usual).all()
    weight = counts[0] / counts[0].sum()
    terms = fa.climate_terms(usual, scale, "advisory", SETTINGS, even)[0, :, 0]
    mean = float((weight / (1 + np.exp(-(math.log(0.12 / 0.88) + terms)))).sum())
    assert mean == pytest.approx(0.12, abs=1e-6)
    # And live even snow there has the term the solve gave it.
    found = zoned(zone, [1.0, 1.0, 1.0])
    live = fa.day_terms(found, float(usual[0]), "advisory", DAY, zone, SETTINGS)
    assert live is not None
    flat = fa.day_terms(
        replace(found, snow_commute=None), float(usual[0]), "advisory", DAY, zone, SETTINGS
    )
    assert flat is not None
    assert sum(live.values.values()) > flat.values[fa.Term.SNOW]


def test_the_timing_band_only_widens_with_snow_and_settings_that_would_not_are_refused() -> None:
    s = np.linspace(0.0, 3.0, 301)
    for weighted in (s * 0.5, s * 2.0, s * 1.1, np.zeros_like(s), s + 1.0):
        held = fa.timed(s, weighted, SETTINGS)
        assert (np.diff(held) >= -1e-12).all()
    assert fa.timed(0.0, 5.0, SETTINGS) == 0.0  # no snow, no timing
    block = dict(CONFIG.live_score["forecast_adjustment"])
    block["timing_max"] = 1.0  # (0.5 + 0.5) 1.0 > 1.0 x 0.5: the band's lower edge would fall
    wide = CONFIG.model_copy(
        update={"live_score": {**CONFIG.live_score, "forecast_adjustment": block}}
    )
    with pytest.raises(ValueError, match="too wide"):
        fa.AdjustSettings.of(wide)


def test_a_snow_line_says_less_than_usual_only_against_the_snow_alone_too() -> None:
    # PHYS-R2-S1: where ice days set the usual snow (Memphis), "less snow than usual here" is
    # said only where the forecast is under the usual snow alone (ice days as quiet) too.
    counts = np.array([[10.0, 6, 3, 1, 0, 0, 4, 6, 3] + [0.0] * 4])
    alone = fa.ice_as_quiet(counts)
    assert alone[0, 6:9].sum() == 0
    assert alone.sum() == counts.sum()
    scale = np.array([1.0])
    p0 = np.array([0.45])
    usual = float(fa.usual_snow(p0, counts, scale, "warning", SETTINGS)[0])
    snow_alone = float(fa.usual_snow(p0, alone, scale, "warning", SETTINGS)[0])
    assert snow_alone < usual
    between = (snow_alone + usual) / 2
    found = forecast(between)
    # The snow alone's usual is the snow line's second bar only, never the snow term's anchor
    # (the lead's ruling of Nov 1: the anchor let more snow lower the chance with ice in the
    # forecast). So between the two usuals the chance is what it is with one usual, lowered:
    # PHYS-R3-S1 (i), the documented limit (counted in the ice-heavy test below), with no
    # "less than usual" said.
    barred = fa.adjusted(
        0.45, 0.1, "warning", usual, found, DAY, EAST, SETTINGS, 0.01, 0.99,
        snow_usual=snow_alone,
    )  # fmt: skip
    one = fa.adjusted(0.45, 0.1, "warning", usual, found, DAY, EAST, SETTINGS, 0.01, 0.99)
    assert one is not None
    assert barred is not None
    assert one.p_no_school < 0.45
    assert barred.p_no_school == one.p_no_school
    line = next(r for r in barred.reasons if isinstance(r, SnowTotalReason))
    assert (line.points < 0, line.against) == (True, "none")
    for anchor in (snow_alone, math.nan, None):
        terms = fa.day_terms(found, usual, "warning", DAY, EAST, SETTINGS)
        assert terms is not None
        held = fa.adjusted(
            0.45, 0.1, "warning", usual, found, DAY, EAST, SETTINGS, 0.01, 0.99,
            snow_usual=anchor,
        )  # fmt: skip
        assert held is not None
        raw = 1 / (1 + math.exp(-(math.log(0.45 / 0.55) + sum(terms.values.values()))))
        assert held.p_no_school == round(raw, 2)
    over = fa.adjusted(
        0.45, 0.1, "warning", usual, forecast(usual * 2), DAY, EAST, SETTINGS, 0.01, 0.99,
        snow_usual=snow_alone,
    )  # fmt: skip
    assert over is not None
    line = next(r for r in over.reasons if isinstance(r, SnowTotalReason))
    assert (line.points > 0, line.against) == (True, "here")
    under = fa.adjusted(
        0.45, 0.1, "warning", usual, forecast(snow_alone / 3), DAY, EAST, SETTINGS, 0.01, 0.99,
        snow_usual=snow_alone,
    )  # fmt: skip
    assert under is not None
    low = next(r for r in under.reasons if isinstance(r, SnowTotalReason))
    assert (low.points < 0, low.against) == (True, "here")
    nan = fa.adjusted(
        0.45, 0.1, "warning", usual, forecast(snow_alone / 3), DAY, EAST, SETTINGS, 0.01, 0.99,
        snow_usual=math.nan,
    )  # fmt: skip
    assert nan is not None
    assert next(r for r in nan.reasons if isinstance(r, SnowTotalReason)).against == "none"


def test_cold_at_the_bus_stop_and_ice_only_add_and_a_trace_of_ice_never_jumps() -> None:
    usual = BUFFALO_USUAL
    warm = total(forecast(2.0, feels=30), usual)
    assert total(forecast(2.0, feels=15), usual) == warm
    assert total(forecast(2.0, feels=5), usual) > warm
    assert total(forecast(2.0, feels=-20), usual) == pytest.approx(warm + SETTINGS.chill_max)
    quiet = total(forecast(0.0), usual)
    assert quiet < 0
    glaze = fa.day_terms(forecast(0.0, ice=0.15, code=7), usual, "advisory", DAY, EAST, SETTINGS)
    assert glaze is not None
    assert glaze.values[fa.Term.ICE] > 0
    # The ice counts as snow on top of the day's: 0.15 inches as 3.75 inches of snow.
    assert sum(glaze.values.values()) == pytest.approx(
        math.log((0.15 * SETTINGS.ice_snow + 0.5) / (usual + 0.5))
    )
    # PHYS-S2: a trace of ice adds a little to a dusting's term, never a jump to a raise.
    chances = [chance(0.06, forecast(0.0, ice=ice), usual) for ice in (0.0, 0.009, 0.01, 0.02)]
    assert chances == sorted(chances)
    assert chances[-1] - chances[0] <= 0.02


def test_a_blizzard_warning_day_keeps_its_class_level() -> None:
    # PHYS-S8: a ground blizzard (little new snow) is never lowered; its wind is the hazard as
    # much as the snow, and the climate cannot tell its days apart, so it is not moved at all.
    assert {"blizzard", "tropical"} <= fa.SKIP
    assert chance(0.45, forecast(0.0), 4.0, "warning") < 0.45  # a snow warning is lowered
    built, _anchor = adjusting_model(NATION)
    assert np.isnan(built.usual_snow[:, SITUATION_POSITION["blizzard"]]).all()
    assert np.isfinite(built.usual_snow[:, SITUATION_POSITION["snow_warning"]]).all()


# --- calibration --------------------------------------------------------------------------------


def climate_mean(
    p0: float,
    counts: np.ndarray,
    usual: float,
    klass: str,
    scale: float,
) -> float:
    """A place's adjusted chance averaged over its climate's days and mornings, written out."""
    terms = fa.climate_terms(np.array([usual]), np.array([scale]), klass, SETTINGS)[0]
    weight = (counts / counts.sum())[:, None] * fa.cold_mix(counts[None, :])[0]
    z0 = math.log(p0 / (1 - p0))
    return float((weight / (1 + np.exp(-(z0 + terms)))).sum())


@pytest.mark.parametrize("klass", ["advisory", "warning"])
def test_each_place_s_days_still_average_its_class_level(klass: str) -> None:
    rng = np.random.default_rng(11)
    count = 300
    counts = rng.poisson(rng.uniform(0, 12, (count, fa.CODES - 1))).astype(np.float64)
    counts[:, 0] += 1  # every place has a day
    p0 = rng.uniform(0.02, 0.9, count)
    scale = rng.choice(np.array([0.889, 0.833, 0.778, 0.722]), count).astype(np.float64)
    usual = fa.usual_snow(p0, counts, scale, klass, SETTINGS)
    inside = np.isfinite(usual)
    assert inside.mean() > 0.8
    for i in np.flatnonzero(inside):
        mean = climate_mean(float(p0[i]), counts[i], float(usual[i]), klass, float(scale[i]))
        assert mean == pytest.approx(float(p0[i]), abs=1e-6)
    # PHYS-S9: days that are all ice are balanced too (their little snow against the usual
    # snow, with the ice on top), so an icy place is adjusted and keeps its level.
    icy = np.zeros((1, fa.CODES - 1))
    icy[0, 8] = 20
    usual_ice = fa.usual_snow(np.array([0.1]), icy, np.ones(1), klass, SETTINGS)[0]
    assert climate_mean(0.1, icy[0], float(usual_ice), klass, 1.0) == pytest.approx(0.1, abs=1e-6)
    # No climate: no usual snow, and the day is never moved.
    assert math.isnan(
        fa.usual_snow(np.array([0.1]), np.zeros((1, 13)), np.ones(1), klass, SETTINGS)[0]
    )


def test_a_snowy_morning_is_as_cold_as_the_place_s_quiet_and_cold_mornings() -> None:
    # PHYS-S1: the codes keep a morning's feel only on a day with under half an inch of snow,
    # but the live cold term counts a cold snowy morning too: the climate gives each snow and
    # ice day the place's own mix of quiet and cold mornings, so the cold is in the solve.
    counts = np.zeros((1, fa.CODES - 1))
    counts[0, 0], counts[0, 9], counts[0, 12], counts[0, 3] = 6, 3, 1, 10
    mix = fa.cold_mix(counts)[0]
    assert mix[3].tolist() == pytest.approx([0.6, 0.3, 0.0, 0.0, 0.1])
    assert mix[9].tolist() == [0.0, 1.0, 0.0, 0.0, 0.0]
    assert mix[0].tolist() == [1.0, 0.0, 0.0, 0.0, 0.0]
    usual = fa.usual_snow(np.array([0.1]), counts, np.ones(1), "advisory", SETTINGS)
    assert climate_mean(0.1, counts[0], float(usual[0]), "advisory", 1.0) == pytest.approx(0.1)
    # Without the cold in the snow days' mornings, the same usual snow would leave them
    # under the level: the cold term on cold snowy mornings is what the solve balances.
    plain = fa.climate_terms(usual, np.ones(1), "advisory", SETTINGS)[0][:, 0]
    weight = counts[0] / counts[0].sum()
    assert float((weight / (1 + np.exp(-(math.log(0.1 / 0.9) + plain)))).sum()) < 0.1


def test_the_committed_climate_keeps_the_class_average_and_the_plausibility_rules() -> None:
    climate = fa.load()
    assert climate.window == "whole"
    districts = sorted(climate.districts)
    for klass, level in (("advisory", 0.10), ("warning", 0.45)):
        counts = np.array([climate.counts(klass, (d, None, None), SETTINGS) for d in districts])
        p0 = np.full(len(districts), level)
        scale = np.full(len(districts), climate.scale(EAST))
        usual = fa.usual_snow(p0, counts, scale, klass, SETTINGS)
        has = counts.sum(axis=1) > 0
        solved = np.isfinite(usual) & has
        assert solved[has].mean() > 0.9
        means = np.array(
            [
                climate_mean(level, counts[i], float(usual[i]), klass, float(scale[i]))
                for i in np.flatnonzero(solved)[:: max(1, int(solved.sum()) // 400)]
            ]
        )
        # Each district's days average its level, so its implied closures a winter (its days
        # times its chance, G6) are what they were at its level.
        assert np.abs(means - level).max() < 1e-4


def test_a_place_with_few_days_borrows_its_county_s_and_then_its_region_s() -> None:
    climate = fa.Climate(
        seasons=("2018-19", "2025-26"),
        window="whole",
        districts={"1": {"advisory": (1,) + (0,) * 12}},
        counties={
            "c": {"advisory": (0, 0, 40) + (0,) * 10},
            "thin": {"advisory": (0, 5) + (0,) * 11},
        },
        regions={"r": {"advisory": (0, 0, 0, 30) + (0,) * 9}},
    )
    own = climate.counts("advisory", ("1", "c", "r"), SETTINGS)
    assert own.tolist() == [1, 0, 10] + [0] * 10
    thin = climate.counts("advisory", (None, "thin", "r"), SETTINGS)
    assert thin.tolist() == [0, 0, 0, 10] + [0] * 9  # the county holds under 30 days
    # S-R2-1: a place with no region of its own (Alaska, Hawaii) never borrows the nation's.
    assert climate.counts("advisory", (None, None, None), SETTINGS).sum() == 0
    assert climate.counts("advisory", (None, None, "alaska"), SETTINGS).sum() == 0
    assert climate.counts("warning", ("1", "c", "r"), SETTINGS).sum() == 0


def test_the_usual_snow_is_more_in_buffalo_than_in_atlanta() -> None:
    climate = fa.load()
    places = {
        "atlanta": ("1300120", "13121", "southeast"),
        "buffalo": ("3605850", "36029", "northeast"),
    }
    found = {}
    for name, place in places.items():
        counts = climate.counts("advisory", place, SETTINGS)[None, :]
        found[name] = float(
            fa.usual_snow(
                np.array([0.1]), counts, np.array([climate.scale(EAST)]), "advisory", SETTINGS
            )[0]
        )
    assert found["atlanta"] == pytest.approx(ATLANTA_USUAL, abs=0.01)
    assert found["buffalo"] == pytest.approx(BUFFALO_USUAL, abs=0.01)
    # The usual is solved with the ice days counted and no anchor (the lead's ruling of Nov 1:
    # serving passes no ``alone``), so it is over the snow alone's (ice days as quiet), which
    # is the snow line's second bar only (PHYS-R2-S1); the gap is PHYS-R3-S1 (i)'s limit.
    for name, place in places.items():
        counts = climate.counts("advisory", place, SETTINGS)[None, :]
        scale = np.array([climate.scale(EAST)])
        alone = fa.usual_snow(np.array([0.1]), fa.ice_as_quiet(counts), scale, "advisory", SETTINGS)
        usual = fa.usual_snow(np.array([0.1]), counts, scale, "advisory", SETTINGS)
        assert float(usual[0]) == found[name]
        assert float(alone[0]) < found[name]


def test_the_climate_says_how_its_codes_counted_the_window_and_is_scaled_only_then() -> None:
    # PHYS-S5, S2, S10: a climate whose codes counted the period under way whole is scaled to
    # the fixed window by each zone's share still to come at 9 PM over a winter (daylight time
    # in November and March; Hawaii's and Alaska's later periods); one counted the fixed way is
    # not scaled again; one that does not say is refused.
    body = json.loads(gzip.decompress(fa.CLIMATE_PATH.read_bytes()))
    assert body["window"] == "whole"
    fixed = fa.parse({**body, "window": "still_to_come"})
    assert fixed.scale(EAST) == 1.0
    whole = fa.parse(body)
    # Eastern: 9 PM EST is 02Z (4 of the first period's 6 hours to come), EDT 01Z (5 of 6).
    assert whole.scale(EAST) == pytest.approx((4 * (4 / 6 + 2) / 3 + (5 / 6 + 2) / 3) / 5)
    # Hawaii: 9 PM is 07Z, after the first period: of the two left, 5 of 6 hours and all.
    assert whole.scale("Pacific/Honolulu") == pytest.approx((5 / 6 + 1) / 2)
    assert whole.scale("America/Los_Angeles") < whole.scale("America/Chicago") < whole.scale(EAST)
    for missing in ({k: v for k, v in body.items() if k != "window"}, {**body, "window": "x"}):
        with pytest.raises(ValueError, match="window"):
            fa.parse(missing)
    with pytest.raises(ValueError, match="window"):
        fa.build(pl.DataFrame(), pl.DataFrame(), pl.DataFrame(), [], "half")


def test_the_climate_file_holds_codes_and_counts_only_and_builds_the_same_bytes(
    tmp_path: Path,
) -> None:
    codes = pl.DataFrame(
        {
            "district": ["0100005", "0100005", "0100005", "0100006"],
            "night": [date(2024, 1, 9), date(2024, 1, 9), date(2024, 1, 10), date(2024, 1, 9)],
            "sample": [13, 12, 13, 13],
            "code_filled": [2, 5, 13, 0],
        },
        schema={"district": pl.String, "night": pl.Date, "sample": pl.Int8, "code_filled": pl.Int8},
    )
    weather = pl.DataFrame(
        {
            "district": ["0100005", "0100005", "0100006"],
            "day": [date(2024, 1, 9), date(2024, 1, 10), date(2024, 1, 9)],
            "weather": [1, 5, 2],  # advisory, snow warning (unknown code: left out), tropical
        },
        schema={"district": pl.String, "day": pl.Date, "weather": pl.Int8},
    )
    districts = pl.DataFrame(
        {"district": ["0100005", "0100006"], "state": ["AL", "AL"], "county": ["01001", "01001"]}
    )
    body = fa.build(codes, weather, districts, ["2023-24", "2023-24"], "still_to_come")
    assert body["window"] == "still_to_come"
    assert body["districts"] == {"0100005": {"advisory": [0, 0, 1] + [0] * 10}}
    assert body["counties"] == {"01001": {"advisory": [0, 0, 1] + [0] * 10}}
    assert body["regions"] == {"southeast": {"advisory": [0, 0, 1] + [0] * 10}}
    first, second = tmp_path / "a.json.gz", tmp_path / "b.json.gz"
    fa.write(body, first)
    fa.write(body, second)
    assert first.read_bytes() == second.read_bytes()
    assert fa.load(first).districts["0100005"]["advisory"][2] == 1
    text = json.dumps(json.loads(gzip.decompress(fa.CLIMATE_PATH.read_bytes())))
    assert not any(word in text.lower() for word in ("http", "closed", "name"))


# --- the lines ----------------------------------------------------------------------------------


def test_the_lines_add_up_and_say_the_snow_against_the_usual_here() -> None:
    moved = fa.adjusted(
        0.10,
        0.11,
        "advisory",
        BUFFALO_USUAL,
        forecast(5.0, spread=0.4),
        DAY,
        EAST,
        SETTINGS,
        0.01,
        0.99,
    )
    assert moved is not None
    (line,) = [r for r in moved.reasons if isinstance(r, SnowTotalReason)]
    assert line.against == "here"
    assert line.points > 0
    assert (line.low, line.high) == (4.0, 6.0)  # every school's 4.6 to 5.4 inches, over 1.76
    assert line.at == RUN
    assert round(moved.p_no_school * 100) - 10 == sum(r.points for r in moved.reasons)
    assert moved.p_delay == round((1 - moved.p_no_school) * 0.11, 2)
    # SF-R4-1: a deciding school under the usual snow and another over it: the line states the
    # schools' range with no comparison, never "more snow than usual here" of a district one
    # of whose deciding schools gets less (or "less" where one gets more).
    for snow, spread in ((3.0, 1.5), (1.0, 1.5)):
        straddle = fa.adjusted(
            0.10, 0.11, "advisory", 2.0, forecast(snow, spread=spread), DAY, EAST, SETTINGS,
            0.01, 0.99,
        )  # fmt: skip
        assert straddle is not None
        (said,) = [r for r in straddle.reasons if isinstance(r, SnowTotalReason)]
        assert said.against == "none"
        assert said.low is not None
        assert said.high is not None
        assert said.low <= max(snow - spread, 0.0) < 2.0 < snow + spread <= said.high
    # The critic's case: deciding schools at 0, 0 and 6 inches, the district's 50% value 0,
    # usual 1 inch: the chance falls, and the line says 0 to 6 inches, no comparison.
    split = replace(forecast(0.0), snow_low=0.0, snow_high=6.0)
    moved = fa.adjusted(0.10, 0.11, "advisory", 1.0, split, DAY, EAST, SETTINGS, 0.01, 0.99)
    assert moved is not None
    (only,) = moved.reasons
    assert isinstance(only, SnowTotalReason)
    assert (only.points < 0, only.low, only.high, only.against) == (True, 0.0, 6.0, "none")
    # A dusting: less than usual, with its amount where every school is under it.
    dust = fa.adjusted(
        0.10, 0.11, "advisory", BUFFALO_USUAL, forecast(0.2), DAY, EAST, SETTINGS, 0.01, 0.99
    )
    assert dust is not None
    (less,) = dust.reasons
    assert isinstance(less, SnowTotalReason)
    assert less.points < 0
    assert (less.low, less.high) == (0.0, 1.0)


def test_timing_ice_and_cold_lines_carry_their_points_and_kinds() -> None:
    moved = fa.adjusted(
        0.10,
        0.11,
        "advisory",
        BUFFALO_USUAL,
        forecast(3.0, split=(0.0, 1.0, 0.0), feels=-5),
        DAY,
        EAST,
        SETTINGS,
        0.01,
        0.99,
    )
    assert moved is not None
    kinds = {type(r): r for r in moved.reasons}
    assert set(kinds) == {SnowTotalReason, TimingReason, WindChillReason}
    timing = kinds[TimingReason]
    assert isinstance(timing, TimingReason)
    assert timing.points > 0
    assert (timing.start, timing.end) == (ndfd.window_ends(DAY)[0], ndfd.window_ends(DAY)[1])
    chill = kinds[WindChillReason]
    assert isinstance(chill, WindChillReason)
    assert chill.feels_like == -5
    ice = fa.adjusted(
        0.10,
        0.11,
        "advisory",
        BUFFALO_USUAL,
        forecast(0.0, ice=0.12, code=7),
        DAY,
        EAST,
        SETTINGS,
        0.01,
        0.99,
    )
    assert ice is not None
    (glaze,) = [r for r in ice.reasons if isinstance(r, IceReason)]
    assert glaze.points > 0
    assert glaze.inches == 0.1
    assert round(ice.p_no_school * 100) - 10 == sum(r.points for r in ice.reasons)


def test_a_timing_line_names_the_heaviest_snow_only_where_it_is_on_the_term_s_side() -> None:
    # S6: the heaviest snow is by the hour (a short first part at a high rate can be it).
    # PHYS-B1: where the heaviest by the hour is on the other side of the term, the line names
    # the period on the term's side (snow_hours), never "the heaviest snow", and the term stays.
    zone = "America/Chicago"  # 9 PM to midnight, midnight to 6 AM, 6 AM to noon
    moved = fa.adjusted(
        0.16, 0.1, "advisory", 3.0, zoned(zone, [3.5, 6.0, 0.0]), DAY, zone, SETTINGS, 0.01, 0.99
    )
    assert moved is not None
    (hours,) = [r for r in moved.reasons if isinstance(r, SnowHoursReason | TimingReason)]
    assert isinstance(hours, SnowHoursReason)  # 3.5 inches in 3 evening hours is heavier
    assert hours.points > 0
    assert (hours.start, hours.end) == (ndfd.window_ends(DAY)[0], ndfd.window_ends(DAY)[1])
    heaviest = fa.adjusted(
        0.16, 0.1, "advisory", 3.0, zoned(zone, [2.0, 6.0, 0.0]), DAY, zone, SETTINGS, 0.01, 0.99
    )
    assert heaviest is not None
    (timing,) = [r for r in heaviest.reasons if isinstance(r, SnowHoursReason | TimingReason)]
    assert isinstance(timing, TimingReason)
    assert (timing.start, timing.end) == (hours.start, hours.end)
    # 0.6 inches in the hour before 10 PM (Pacific) is a heavier rate than 3 inches over the
    # next 6 hours, which a total would have named the heaviest.
    pacific = "America/Los_Angeles"
    found = zoned(pacific, [0.6, 3.0, 0.0])
    terms = fa.day_terms(found, 3.0, "advisory", DAY, pacific, SETTINGS)
    assert terms is not None
    assert terms.values[fa.Term.TIMING] > 0
    assert terms.period == found.snow_parts[1]
    assert not terms.heaviest


# --- SF-R5-1 through the reader -----------------------------------------------------------------


def test_the_reader_s_snow_and_parts_never_count_snow_already_down() -> None:
    schools = history.Schools(
        lat=np.array([39.1, 39.11]),
        lon=np.array([-94.58, -94.57]),
        district=np.array([0, 0], dtype=np.int64),
        districts=("2900001",),
        zone_of_district=("America/Chicago",),
    )
    day = date(2026, 1, 7)
    run = ndfd.Run(world.utc("2026-01-07T02:30:00"), {}, world.utc("2026-01-07T02:40:00"))
    ends = ndfd.window_ends(day)
    values = history.RunValues(run)
    # 6 inches in the period under way at 9 PM CST (03Z): only its half still to come counts.
    values.snow = {
        ends[0]: np.array([6.0, 6.0]),
        ends[1]: np.array([1.0, 1.0]),
        ends[2]: np.zeros(2),
    }
    values.ice = {end: np.zeros(2) for end in ends}
    values.feels = {ndfd.bus_time(day, "America/Chicago"): np.array([20.0, 20.0])}
    found = forecast_live.forecasts(
        schools,
        {"2900001": 0},
        (day,),
        world.utc("2026-01-07T12:00:00"),
        lambda _d: [run],
        lambda _r, _d: values,
        0.5,
    )
    one = found.get(day, 0)
    assert one is not None
    assert one.snow == 4.0  # 3 + 1, never the 6 + 1 the period holds
    at = world.utc("2026-01-07T03:00:00")
    assert one.snow_parts[0] == SnowPart(at, ends[0], 3.0)
    assert one.snow_parts[1] == SnowPart(ends[0], ends[1], 1.0)


# --- serving ------------------------------------------------------------------------------------


def adjusting_model(climate: fa.Climate) -> tuple[ServeModel, an.Anchor]:
    anchor = an.fit(
        an.AnchorSettings.of(CONFIG), Exposure((), {}, {}, {}, {}, {}), an.NO_LABELS, {}
    )
    anchor = replace(anchor, climate=climate, adjust=SETTINGS)
    return build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    ), anchor


MIX: dict[str, tuple[int, ...]] = {
    "advisory": (5, 10, 10, 3) + (0,) * 9,
    "warning": (2, 5, 10, 10, 5, 2) + (0,) * 7,
}
NATION = fa.Climate(
    seasons=("2018-19", "2025-26"),
    window="whole",
    districts={},
    counties={},
    # The test world's regions: Kansas, Missouri and Utah.
    regions=dict.fromkeys(("south", "ohio_valley", "southwest"), MIX),
)


def test_a_pass_moves_an_advisory_day_by_its_forecast_and_keeps_the_rest() -> None:
    built, _anchor = adjusting_model(NATION)
    advisory = SITUATION_POSITION["advisory"]
    assert built.usual_snow.shape == built.p.shape
    assert np.isfinite(built.usual_snow[:, advisory]).all()
    assert np.isnan(built.usual_snow[:, SITUATION_POSITION["cold"]]).all()
    assert np.isnan(built.usual_snow[:, SITUATION_POSITION["tropical"]]).all()
    assert np.isnan(built.usual_snow[:, SITUATION_POSITION["none"]]).all()
    days = (date(2026, 1, 14), date(2026, 1, 15))
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    heavy = replace(forecast(6.0), run_time=RUN)
    forecasts = Forecasts({days[0]: {1: heavy, 2: forecast(0.0)}})
    at = world.utc("2026-01-14T03:00:00")  # 9 PM CST: Missouri's and Kansas's snapshot
    made = forecast_file(
        built, classes, days, at, closed_on=lambda _d: None, last=None, forecasts=forecasts,
        adjust=True,
    )  # fmt: skip
    by = {entry.district: entry.days for entry in made.districts}
    # Turn-on items 8 and 10: a minute before the snapshot, and for the day after, the class
    # level alone, whatever was read.
    early = forecast_file(
        built, classes, days, at - timedelta(minutes=1), closed_on=lambda _d: None, last=None,
        forecasts=forecasts, adjust=True,
    )  # fmt: skip
    assert all(
        isinstance(d, Forecast) and (d.p_no_school, d.why.reasons) == (0.1, ())
        for e in early.districts
        for d in e.days
    )
    first = by[1][0]
    assert isinstance(first, Forecast)
    assert first.p_no_school > 0.1
    assert isinstance(first.why.base, ClassBase)
    assert first.why.total() == round(first.p_no_school * 100)
    assert any(isinstance(r, SnowTotalReason) and r.against == "here" for r in first.why.reasons)
    quiet = by[2][0]
    assert isinstance(quiet, Forecast)
    assert quiet.p_no_school < 0.1
    for index in (0, 3, 4):  # no forecast read: the class level, no line
        found = by[index][0]
        assert isinstance(found, Forecast)
        assert (found.p_no_school, found.why.reasons) == (0.1, ())
    later = by[1][1]  # the next day has no forecast
    assert isinstance(later, Forecast)
    assert later.p_no_school == 0.1
    assert PredictionsFile.from_json_bytes(made.to_json_bytes()) == made
    off = forecast_file(built, classes, days, world.utc("2026-01-14T03:00:00"),
                        closed_on=lambda _d: None, last=None, forecasts=forecasts)  # fmt: skip
    assert all(
        isinstance(d, Forecast) and d.p_no_school == 0.1 for e in off.districts for d in e.days
    )


def test_a_district_the_adjustment_would_put_over_the_plausibility_limit_is_not_adjusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Kansas has so many advisory days that its class level already sits at the limit (G6);
    # an adjustment that came to more closures on its days would put it over: not adjusted.
    # (Its 90 days also hold the test world's national advisory mean at its limit: that clause
    # is the next test's; here only the district's.)
    monkeypatch.setattr(serve, "failing_clauses", lambda *_args: ())
    exposure = Exposure(
        ("2018-19", "2025-26"),
        {"2000004": (90.0, 4.0, 0.0), "2900001": (2.0, 0.5, 0.0)},
        {},
        {"advisory": 2.0, "warning": 0.5, "cold": 1.0},
        {},
        {},
    )
    anchor = an.fit(an.AnchorSettings.of(CONFIG), exposure, an.NO_LABELS, {})
    anchor = replace(anchor, climate=NATION, adjust=SETTINGS)
    limit = anchor.settings.plausibility.district_max
    real = fa.expected

    def more(*args: object, **kwargs: object) -> object:
        found = real(*args, **kwargs).copy()  # type: ignore[arg-type]
        found[world.DISTRICTS.index("2000004")] += 0.05  # Kansas's days alone
        return found

    monkeypatch.setattr(fa, "expected", more)
    built = build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    )
    kansas, missouri = world.DISTRICTS.index("2000004"), world.DISTRICTS.index("2900001")
    level = built.p[kansas, SITUATION_POSITION["advisory"]] * 90 + (
        built.p[kansas, SITUATION_POSITION["snow_warning"]] * 4
    )
    assert level > limit - 0.05 * 94
    assert np.isnan(built.usual_snow[kansas]).all()
    assert np.isfinite(built.usual_snow[missouri, SITUATION_POSITION["advisory"]])
    # Without the extra closures both keep their usual snow.
    monkeypatch.setattr(fa, "expected", real)
    again = build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    )
    assert np.isfinite(again.usual_snow[kansas, SITUATION_POSITION["advisory"]])


def test_every_plausibility_clause_is_held_on_the_adjusted_chances_or_the_levels_serve(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # PHYS-R3-S3: G6's national clauses (advisory mean and p99, advisory and warning mean)
    # and the most of any district are asserted on the adjusted means; where one fails and
    # the adjustment made it worse than the class levels, no district is adjusted and the
    # pass warns.
    exposure = Exposure(
        ("2018-19", "2025-26"),
        dict.fromkeys(world.DISTRICTS, (6.0, 1.5, 0.5)),
        {},
        {"advisory": 6.0, "warning": 1.5, "cold": 0.5},
        {},
        {},
    )
    anchor = replace(
        an.fit(an.AnchorSettings.of(CONFIG), exposure, an.NO_LABELS, {}),
        climate=NATION,
        adjust=SETTINGS,
    )
    passing = build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    )
    check = passing.adjust_check
    assert check is not None
    assert check.failing == ()
    assert set(check.summary) >= {"advisory_mean", "advisory_p99", "advisory_warning_mean"}
    assert check.summary["advisory_mean"] <= anchor.settings.plausibility.advisory_mean
    assert np.isfinite(passing.usual_snow[:, SITUATION_POSITION["advisory"]]).all()
    cli.said_plausible(passing)
    said = capsys.readouterr()
    assert "forecast adjustment plausibility: advisory mean" in said.out
    assert "forecast adjustment" not in said.err  # no warning
    real = fa.expected

    def more(*args: object, **kwargs: object) -> object:
        return real(*args, **kwargs) + 0.2  # type: ignore[arg-type]

    monkeypatch.setattr(fa, "expected", more)
    failing = build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    )
    check = failing.adjust_check
    assert check is not None
    assert "advisory_mean" in check.failing
    assert np.isnan(failing.usual_snow).all()
    assert np.isnan(failing.snow_usual).all()
    cli.said_plausible(failing)
    said = capsys.readouterr()
    assert "FAILS advisory_mean" in said.out
    assert "forecast adjustment plausibility" in said.err  # the warning
    # The class levels serve: a 6-inch forecast moves nothing.
    days = (date(2026, 1, 14), date(2026, 1, 15))
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    made = forecast_file(
        failing, classes, days, world.utc("2026-01-14T03:07:00"), closed_on=lambda _d: None,
        last=None, forecasts=Forecasts({days[0]: {1: forecast(6.0)}}), adjust=True,
    )  # fmt: skip
    item = made.districts[1].days[0]
    assert isinstance(item, Forecast)
    assert item.why.reasons == ()


LEVELS = ((0.06, 0.33), (0.10, 0.45), (0.19, 0.44), (0.13, 0.28))
"""Advisory and warning levels spanning the deployed directory's (L3 dry run: advisory 6% to
19%, warning 28% to 53%), one to a district in turn."""
AMOUNTS = (0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0)


@pytest.fixture(scope="module")
def committed() -> SimpleNamespace:
    """Every district of the committed climate, solved as serving solves it
    (:func:`serve._usual_snow`), with its class levels from :data:`LEVELS`."""
    artifact = ModelArtifact.from_bytes(ARTIFACT_PATH.read_bytes())
    climate = fa.load()
    leaids = sorted(set(climate.districts) & set(artifact.districts))
    places = [
        (d, artifact.districts[d].county, REGION_OF.get(artifact.districts[d].state or ""))
        for d in leaids
    ]
    zones = [artifact.districts[d].time_zone or EAST for d in leaids]
    p = np.full((len(leaids), len(SITUATIONS)), 0.05)
    anchor = replace(
        an.fit(an.AnchorSettings.of(CONFIG), Exposure((), {}, {}, {}, {}, {}), an.NO_LABELS, {}),
        climate=climate,
        adjust=SETTINGS,
    )
    for k, situation in enumerate(SITUATIONS):
        klass = anchor.class_of(situation.key)
        for i in range(len(leaids)):
            advisory, warning = LEVELS[i % len(LEVELS)]
            p[i, k] = {"advisory": advisory, "warning": warning, "cold": 0.1}.get(klass or "", 0.05)
    usual, alone, check = serve._usual_snow(anchor, p, places, zones, an.Grid(0.01, 0.99))
    return SimpleNamespace(
        leaids=leaids, zones=zones, p=p, usual=usual, alone=alone, check=check, anchor=anchor
    )


LIMIT_I = 5394
"""PHYS-R3-S1 (i), the documented limit (the lead's ruling of Nov 1): the snow-only warning
cells (a district of the committed climate at its level from :data:`LEVELS`, an amount of
:data:`AMOUNTS` over its snow alone's usual, even snow, no ice, 30 F) whose published chance
is under the class level. With the round-4 anchor it was 0, but the anchor let more snow
lower the chance where ice is forecast; with one usual (round 3 and now) it is this."""


def test_an_icy_district_s_snow_warning_between_its_two_usuals_is_lowered_a_documented_limit(
    committed: SimpleNamespace,
) -> None:
    # PHYS-R3-S1 (i) is a documented limit since the lead's ruling of Nov 1: where a district's
    # warning days are often icy, its usual snow counts the ice days, so a snow-only warning
    # over what the snow alone makes usual but under that usual is lowered (Memphis-Shelby and
    # 0502880 by name), with no "less than usual" said; at its usual and over, never.
    k = SITUATION_POSITION["snow_warning"]
    index = {leaid: i for i, leaid in enumerate(committed.leaids)}
    for leaid in ("4700148", "0502880"):
        i = index[leaid]
        usual, alone = float(committed.usual[i, k]), float(committed.alone[i, k])
        assert math.isfinite(usual)
        assert alone < usual  # icy: its ice days raise the usual
        p0 = float(committed.p[i, k])
        between = fa.adjusted(
            p0, 0.1, "warning", usual, forecast((alone + usual) / 2, feels=30), DAY, EAST,
            SETTINGS, 0.01, 0.99, snow_usual=alone,
        )  # fmt: skip
        assert between is not None
        assert between.p_no_school < p0, leaid
        line = next(r for r in between.reasons if isinstance(r, SnowTotalReason))
        assert line.against == "none"  # under the usual, over the snow alone's: no comparison
        for inches in (usual, usual * 1.5, usual + 3.0):
            moved = fa.adjusted(
                p0, 0.1, "warning", usual, forecast(inches, feels=30), DAY, EAST, SETTINGS,
                0.01, 0.99, snow_usual=alone,
            )  # fmt: skip
            assert moved is None or moved.p_no_school >= p0, (leaid, inches)
    # The limit's count over every district of the committed climate, pinned.
    shown: dict[tuple[float, float, float], float] = {}
    lowered = 0
    for i in map(int, np.flatnonzero(np.isfinite(committed.usual[:, k]))):
        p0, usual = float(committed.p[i, k]), float(committed.usual[i, k])
        alone = float(committed.alone[i, k])
        for inches in AMOUNTS:
            if inches <= alone:
                continue
            key = (p0, usual, inches)
            if key not in shown:
                moved = fa.adjusted(
                    p0, 0.1, "warning", usual, forecast(inches, feels=30), DAY, EAST,
                    SETTINGS, 0.01, 0.99, snow_usual=alone,
                )  # fmt: skip
                shown[key] = p0 if moved is None else moved.p_no_school
            lowered += int(shown[key] < p0)
            assert inches < usual or shown[key] >= p0
    assert lowered == LIMIT_I
    # The round-4 anchor's successor (predict-next SNOW-AMOUNT, registered off): with
    # ``snow_amount`` on the snow alone's floor holds the snow term from the snow alone's usual
    # up at 0 or more (:func:`fa.floor_lift`, its anchor never under u / 3).
    on = replace(SETTINGS, snow_amount=True)
    solved = np.isfinite(committed.usual[:, k])
    usual_k, alone_k = committed.usual[solved, k], committed.alone[solved, k]
    anchor = np.minimum(np.maximum(alone_k, usual_k / on.snow_amount_floor_ratio), usual_k)
    for inches in AMOUNTS:
        terms = fa.snow_term(inches, usual_k, on)
        terms = terms + fa.floor_lift(terms, inches, usual_k, alone_k, on)
        over = inches > anchor
        assert (terms[over] >= -1e-12).all()


def test_an_advisory_day_is_never_over_the_same_district_s_warning_day(
    committed: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PHYS-R3-S1 (ii), the class order: for the same forecast in the same district, the
    # advisory chance (as published) is never above any winter warning situation's, over every
    # district of the committed climate at 0 to 8 inches, with and without ice, on every kind
    # of morning (the solve's code amounts replaced by these forecasts).
    places = len(committed.leaids)
    zones = committed.zones
    even = np.array([fa.even_factor(zone, SETTINGS) for zone in zones])
    ones = np.ones(places)
    counted = 0
    for ice in (0.0, 0.1):
        snow = (*AMOUNTS, *AMOUNTS[:6])
        monkeypatch.setattr(fa, "SNOW_CODE", snow)
        monkeypatch.setattr(fa, "ICE_CODE", (ice,) * len(snow))
        warned = []
        for key in serve.ORDERED:
            k = SITUATION_POSITION[key]
            if key in fa.SKIP:
                warned.append(np.broadcast_to(committed.p[:, k, None, None], (places, 13, 5)))
                continue
            # As serving solves the class order: no snow-alone anchor (the lead's ruling).
            warned.append(
                fa.climate_chances(
                    committed.p[:, k], committed.usual[:, k], ones, "warning", SETTINGS, even
                )
            )
        k = SITUATION_POSITION["advisory"]
        p0, usual = committed.p[:, k], committed.usual[:, k]
        most = fa.order_cap(p0, warned)
        has = np.isfinite(usual)
        terms = fa.climate_terms(
            np.where(has, usual, 0.0), ones, "advisory", SETTINGS, even, None, most
        )
        advisory = np.where(
            has[:, None, None], 1 / (1 + np.exp(-(np.log(p0 / (1 - p0))[:, None, None] + terms))),
            p0[:, None, None],
        )  # fmt: skip
        shown = np.clip(np.round(advisory, 2), 0.01, 0.99)
        for chances in warned:
            over = shown > np.clip(np.round(chances, 2), 0.01, 0.99) + 1e-9
            assert not over.any(), np.argwhere(over)[:5]
            counted += over.size
    assert counted == 2 * len(serve.ORDERED) * places * 13 * 5
    assert committed.check.failing == ()


SNOWS = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)
ICES = (0.0, 0.05, 0.1, 0.25)
SERVED = ("advisory", *sorted(serve.ORDERED))
"""The advisory and every winter warning situation, as the served path publishes them."""


def spread(
    zone: str, snow: float, where: str, *, ice: float = 0.0, feels: int = 25
) -> DistrictForecast:
    """``snow`` inches still to come at ``zone``'s 9 PM snapshot: ``even`` over the window's
    hours still to come, or ``late``: all of it in the window's last period (into the late
    morning, mostly after the commute)."""
    at = fa.snapshot(DAY, zone)
    ends = [end for end in ndfd.window_ends(DAY) if end > at]
    hours = [(end - max(end - ndfd.PERIOD, at)).total_seconds() for end in ends]
    if where == "even":
        amounts = [snow * h / sum(hours) for h in hours]
    else:
        amounts = [0.0] * (len(ends) - 1) + [snow]
    return zoned(zone, amounts, ice=ice, feels=feels)


def served_model(committed: SimpleNamespace) -> ServeModel:
    """A model whose rates and usuals are the committed climate's districts' (``committed``),
    for :func:`serve._order_cap`, which reads only those."""
    built, _anchor = adjusting_model(NATION)
    return replace(
        built,
        p=committed.p,
        usual_snow=committed.usual,
        snow_usual=committed.alone,
        anchor=committed.anchor,
    )


def picked(committed: SimpleNamespace) -> list[int]:
    """The committed climate's districts the served-path test runs through: the named ones
    (Memphis-Shelby, 0502880, Atlanta, Buffalo, and the round-4 verifier's worst cases), the 30
    whose warning usual is most over their snow alone's and the 10 whose advisory usual is (the
    icy districts, where the round-4 anchor broke the direction rule), and every 400th."""
    index = {leaid: i for i, leaid in enumerate(committed.leaids)}
    named = [
        index[leaid]
        for leaid in ("4700148", "0502880", "1300120", "3605850", "2900008", "0500052")
        if leaid in index
    ]
    assert len(named) >= 4
    found = set(named)
    for key, most in (("snow_warning", 30), ("advisory", 10)):
        k = SITUATION_POSITION[key]
        gap = np.nan_to_num(committed.usual[:, k] - committed.alone[:, k], nan=-np.inf)
        found.update(int(i) for i in np.argsort(-gap)[:most])
    found.update(range(0, len(committed.leaids), 400))
    return sorted(found)


def served_chance(
    model: ServeModel, index: int, key: str, found: DistrictForecast, zone: str
) -> float:
    """District ``index``'s published chance on a day of situation ``key`` with ``found`` as
    serving makes it (:func:`serve._forecast_day`): fa.adjusted with its snow alone's usual
    as ``snow_usual`` and serve._order_cap's cap; the class level where no term moves it."""
    anchor = model.anchor
    assert anchor is not None
    k = SITUATION_POSITION[key]
    klass = anchor.class_of(key)
    assert klass is not None
    p0, usual = float(model.p[index, k]), float(model.usual_snow[index, k])
    if key in fa.SKIP or not math.isfinite(usual):
        return p0
    cap = serve._order_cap(model, anchor, index, klass, DAY, zone, found)
    assert (cap is None) == (klass != "advisory")
    moved = fa.adjusted(
        p0, 0.1, klass, usual, found, DAY, zone, SETTINGS, 0.01, 0.99,
        snow_usual=float(model.snow_usual[index, k]), cap=cap,
    )  # fmt: skip
    return p0 if moved is None else moved.p_no_school


def test_through_the_served_path_more_snow_ice_or_cold_never_lowers_a_chance_and_the_order_holds(
    committed: SimpleNamespace,
) -> None:
    # PHYS-R4-DIRECTION: through the path serving takes (fa.adjusted with the snow alone's
    # usual as ``snow_usual`` and serve._order_cap's cap), over the committed climate's
    # districts (:func:`picked`; every district in the round's dry run), even and late snow 0
    # to 8 in, ice 0 to 0.25 in, 25 F down to -20 F: more snow, more ice or more cold never
    # lowers a published chance, and an advisory day is never over the same district's
    # warning day for the same forecast. With the round-4 anchor, 0.1 in of ice made
    # Memphis-Shelby's warning fall from 65% at 1.5 in to 55% at 5 in.
    model = served_model(committed)
    feels = (25, 0, -20)
    falls = order = checked = 0
    for i in picked(committed):
        zone = committed.zones[i]
        memo: dict[tuple[object, ...], float] = {}

        def published(  # noqa: PLR0913, PLR0917 - the cell, and the district bound at definition
            key: str,
            snow: float,
            where: str,
            ice: float,
            cold: int,
            i: int = i,
            zone: str = zone,
            memo: dict[tuple[object, ...], float] = memo,
        ) -> float:
            # Warning situations at the same level and usual (today all of them) are read once.
            k = SITUATION_POSITION[key]
            same = (key,) if key == "advisory" else (model.p[i, k], model.usual_snow[i, k])
            known = (*same, snow, where, ice, cold)
            if known not in memo:
                found = spread(zone, snow, where, ice=ice, feels=cold)
                memo[known] = served_chance(model, i, key, found, zone)
            return memo[known]

        cells = [
            (where, ice, cold)
            for where in ("even", "late")
            for ice in ICES
            for cold in feels
            if cold == 25 or (where == "even" and ice in (0.0, 0.1))
        ]
        grid = {
            (key, cell): [published(key, snow, *cell) for snow in SNOWS]
            for key in SERVED
            for cell in cells
        }
        for (key, (where, ice, cold)), row in grid.items():
            falls += sum(b < a for a, b in itertools.pairwise(row))  # more snow
            if cold == 25 and ice < ICES[-1]:  # more ice
                more = grid[key, (where, ICES[ICES.index(ice) + 1], cold)]
                falls += sum(b < a for a, b in zip(row, more, strict=True))
            if cold != feels[-1] and (key, (where, ice, feels[feels.index(cold) + 1])) in grid:
                colder = grid[key, (where, ice, feels[feels.index(cold) + 1])]
                falls += sum(b < a for a, b in zip(row, colder, strict=True))  # more cold
            if key != "advisory":
                advisory = grid["advisory", (where, ice, cold)]
                order += sum(a > w for a, w in zip(advisory, row, strict=True))
            checked += len(row)
    assert (falls, order) == (0, 0)
    assert checked == len(picked(committed)) * len(SERVED) * 12 * len(SNOWS)


def test_a_pass_publishes_no_advisory_day_over_its_warning_day_and_no_fall_with_more_weather(
    committed: SimpleNamespace,
) -> None:
    # PHYS-R4-DIRECTION through forecast_file: the world's five districts given the rates and
    # usuals of five committed-climate districts (Memphis-Shelby and 0502880, icy; Atlanta;
    # Buffalo; the most icy of the rest), every class of the class order on the same day with
    # the same forecast: the published advisory chance is never over a warning's, and no
    # class's published chance falls with more snow or more ice.
    index = {leaid: i for i, leaid in enumerate(committed.leaids)}
    k = SITUATION_POSITION["snow_warning"]
    gap = np.nan_to_num(committed.usual[:, k] - committed.alone[:, k], nan=-np.inf)
    named = [index[leaid] for leaid in ("4700148", "0502880", "1300120", "3605850")]
    rows = [*named, next(int(i) for i in np.argsort(-gap) if int(i) not in named)]
    built, _anchor = adjusting_model(NATION)
    model = replace(
        built,
        p=committed.p[rows],
        usual_snow=committed.usual[rows],
        snow_usual=committed.alone[rows],
        anchor=committed.anchor,
    )
    kinds = (
        WeatherClass.ADVISORY, WeatherClass.SNOW_WARNING, WeatherClass.LAKE_SNOW,
        WeatherClass.ICE, WeatherClass.BLIZZARD,
    )  # fmt: skip
    at = world.utc("2026-01-14T05:00:00")  # past every zone's 9 PM snapshot
    shown = np.zeros((len(kinds), len(ICES), len(SNOWS), len(world.DISTRICTS)))
    for a, kind in enumerate(kinds):
        classes = np.full((len(world.DISTRICTS), 1), int(kind), dtype=np.int64)
        for b, ice in enumerate(ICES):
            for c, snow in enumerate(SNOWS):
                found = Forecasts(
                    {DAY: {d: forecast(snow, ice=ice) for d in range(len(world.DISTRICTS))}}
                )
                made = forecast_file(
                    model, classes, (DAY,), at, closed_on=lambda _d: None, last=None,
                    forecasts=found, adjust=True,
                )  # fmt: skip
                for entry in made.districts:
                    day = entry.days[0]
                    assert isinstance(day, Forecast)
                    shown[a, b, c, entry.district] = day.p_no_school
    assert (np.diff(shown, axis=2) >= 0).all()  # more snow
    assert (np.diff(shown, axis=1) >= 0).all()  # more ice
    assert (shown[0] <= shown[1:].min(axis=0)).all()  # the class order
    assert (shown[0] != shown[0, 0, 0]).any()  # the forecast moved the advisory days


def test_an_advisory_day_with_no_snow_ahead_is_lowered_to_about_half_its_level_no_less() -> None:
    # PHYS-R3-S2: snow that fell before 9 PM is not counted (SF-R5-1), so a 9 PM read of 0.00
    # in lowers an advisory day by at most 0.7 log-odds (about half its level), as the
    # warning's -0.4 does.
    low, _high = SETTINGS.bounds["advisory"]
    assert low == -0.7
    for p0, usual in ((0.10, ATLANTA_USUAL), (0.10, BUFFALO_USUAL), (0.06, 3.0), (0.19, 0.4)):
        floor = round(1 / (1 + math.exp(-(math.log(p0 / (1 - p0)) + low))), 2)
        shown = chance(p0, forecast(0.0), usual)
        assert shown >= floor
        assert shown >= p0 / 2 - 0.005
    # Each pass notes the share of the class's district-days at the bound.
    built, _anchor = adjusting_model(NATION)
    days = (date(2026, 1, 14), date(2026, 1, 15))
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    found = Forecasts({days[0]: {1: forecast(0.0), 2: forecast(6.0)}})
    made = forecast_file(
        built, classes, days, world.utc("2026-01-14T03:07:00"), closed_on=lambda _d: None,
        last=None, forecasts=found, adjust=True,
    )  # fmt: skip
    note = fa.shift_note(made, SETTINGS)
    assert note is not None
    assert "advisory 10 days, 2 moved" in note
    assert "at the lower bound 10.0%" in note  # 1 of 10
    assert "lower bound" not in (fa.shift_note(made) or "")


def test_a_previous_chance_is_shown_only_between_two_reads_of_the_forecast() -> None:
    built, _anchor = adjusting_model(NATION)
    days = (date(2026, 1, 14), date(2026, 1, 15))
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    before = world.utc("2026-01-14T02:37:00")  # 8:37 PM CST, before the snapshot
    later = world.utc("2026-01-14T03:07:00")

    def made(at: datetime, found: Forecasts, last: PredictionsFile | None, *, adjust: bool = True,
             read: frozenset[tuple[int, date]] | None = None) -> PredictionsFile:  # fmt: skip
        return forecast_file(
            built, classes, days, at, closed_on=lambda _d: None, last=last, forecasts=found,
            adjust=adjust, read_last=read,
        )  # fmt: skip

    def day_one(file: PredictionsFile) -> Forecast:
        found = file.districts[1].days[0]
        assert isinstance(found, Forecast)
        return found

    heavy = Forecasts({days[0]: {1: forecast(6.0)}})
    heavier = Forecasts({days[0]: {1: forecast(9.0)}})
    level = made(before, heavy, None)
    assert day_one(level).p_no_school == 0.1  # before the snapshot: the class level
    # The snapshot passed: the forecast arriving is not the storm worsening.
    on = made(later, heavy, level)
    assert day_one(on).p_no_school > 0.1
    assert day_one(on).previous is None
    # PHYS-S7: a read that fails the next pass keeps the same snapshot's chance and lines,
    # never a swing to the class level and back.
    failed = made(later + timedelta(minutes=30), NO_FORECASTS, on)
    assert (day_one(failed).p_no_school, day_one(failed).why) == (
        day_one(on).p_no_school,
        day_one(on).why,
    )
    assert day_one(failed).previous is None
    # Two reads: a real change in the forecast, said.
    more = made(later + timedelta(hours=1), heavier, failed)
    assert day_one(more).p_no_school > day_one(failed).p_no_school
    previous = day_one(more).previous
    assert previous is not None
    assert previous.p_no_school == day_one(failed).p_no_school
    # A forecast read that no longer moves it (a point or less) is a real change too.
    usual = float(built.usual_snow[1, SITUATION_POSITION["advisory"]])
    quiet = Forecasts({days[0]: {1: forecast(usual)}})
    calm = made(later + timedelta(hours=2), quiet, more)
    assert day_one(calm).p_no_school == 0.1
    assert day_one(calm).why.reasons == ()
    calmed = day_one(calm).previous
    assert calmed is not None
    assert calmed.p_no_school == day_one(more).p_no_school
    # S8: and from a read that moved it under a point to one that moves it, the change is said,
    # where the pass that made the last file is known to have read it.
    back = made(later + timedelta(hours=3), heavy, calm, read=frozenset({(1, days[0])}))
    assert day_one(back).p_no_school > 0.1
    rose = day_one(back).previous
    assert rose is not None
    assert rose.p_no_school == 0.1
    # S-R2-3: where it is not known (a restart), or that pass's read failed with no lines to
    # keep, the class level was no read's: the forecast read now is no change in the weather.
    assert day_one(made(later + timedelta(hours=3), heavy, calm)).previous is None
    unread = made(later, NO_FORECASTS, None)
    assert (day_one(unread).p_no_school, day_one(unread).why.reasons) == (0.1, ())
    read_now = made(later + timedelta(minutes=30), heavy, unread, read=frozenset())
    assert day_one(read_now).p_no_school > 0.1
    assert day_one(read_now).previous is None


def test_a_failed_read_keeps_the_last_lines_only_at_the_same_class_level_and_snapshot() -> None:
    built, _anchor = adjusting_model(NATION)
    days = (date(2026, 1, 14), date(2026, 1, 15))
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    at = world.utc("2026-01-14T03:07:00")
    heavy = Forecasts({days[0]: {1: forecast(6.0)}})
    on = forecast_file(
        built, classes, days, at, closed_on=lambda _d: None, last=None, forecasts=heavy,
        adjust=True,
    )  # fmt: skip
    kept = serve._kept(on, built)
    assert set(kept) == {(1, days[0])}
    level, moved = kept[(1, days[0])]
    assert level == (10, None, "advisory")
    k = SITUATION_POSITION["advisory"]
    advisory = Situation.of(WeatherClass.ADVISORY, False)
    later = at + timedelta(minutes=30)
    assert serve._adjusted(built, 1, k, days[0], NO_FORECASTS, advisory, later, kept) == (
        moved,
        True,
        fa.snapshot(days[0], "America/Chicago"),
    )
    # The class level moved (a new alert, the live labels): the last lines are not this day's.
    other: serve.Kept = {(1, days[0]): ((12, None, "advisory"), moved)}
    found, read, _snapshot = serve._adjusted(
        built, 1, k, days[0], NO_FORECASTS, advisory, later, other
    )
    assert (found, read) == (None, False)
    # PHYS-R2-S4: nor another situation's at the same level (a lake effect snow warning's
    # lines are never a winter storm warning's).
    snow = SITUATION_POSITION["snow_warning"]
    warning = Situation.of(WeatherClass.SNOW_WARNING, False)
    points = round(float(built.p[1, snow]) * 100)
    lake: serve.Kept = {(1, days[0]): ((points, None, "lake_snow"), moved)}
    found, read, _snapshot = serve._adjusted(
        built, 1, snow, days[0], NO_FORECASTS, warning, later, lake
    )
    assert (found, read) == (None, False)
    same: serve.Kept = {(1, days[0]): ((points, "winter_storm_warning", None), moved)}
    found, read, _snapshot = serve._adjusted(
        built, 1, snow, days[0], NO_FORECASTS, warning, later, same
    )
    assert (found, read) == (moved, True)
    # A file made before the snapshot holds no lines of it.
    early = forecast_file(
        built, classes, days, at - timedelta(minutes=30), closed_on=lambda _d: None, last=None,
        forecasts=heavy, adjust=True,
    )  # fmt: skip
    assert serve._kept(early, built) == {}
    # And a read that fails with the class level moved: the class level, no "Down from".
    lost = forecast_file(
        built, classes, days, later, closed_on=lambda _d: None,
        last=on.model_copy(update={"generated_at": at - timedelta(hours=2)}),
        forecasts=NO_FORECASTS, adjust=True,
    )  # fmt: skip
    first = lost.districts[1].days[0]
    assert isinstance(first, Forecast)
    assert (first.p_no_school, first.previous) == (0.1, None)


def test_a_class_s_situations_are_each_solved_at_their_own_level() -> None:
    # PHYS-S4: the usual snow is solved for each distinct level within a class, never the
    # first situation's carried to the rest.
    built, anchor = adjusting_model(NATION)
    p = built.p.copy()
    lake, snow = SITUATION_POSITION["lake_snow"], SITUATION_POSITION["snow_warning"]
    p[:, lake] = np.clip(p[:, snow] * 1.4, 0.02, 0.95)
    zones = [built.time_zone[i] for i in range(len(world.DISTRICTS))]
    places = [(leaid, "29095", "ohio_valley") for leaid in world.DISTRICTS]
    usual, _alone, _check = serve._usual_snow(anchor, p, places, zones, an.Grid(0.01, 0.99))
    assert np.isfinite(usual[:, lake]).all()
    assert (usual[:, lake] != usual[:, snow]).all()
    counts = NATION.counts("warning", places[0], SETTINGS)
    for k in (lake, snow):
        scale = NATION.scale(zones[0])
        mean = climate_mean(float(p[0, k]), counts, float(usual[0, k]), "warning", scale)
        assert mean == pytest.approx(float(p[0, k]), abs=1e-6)
    ice = SITUATION_POSITION["ice"]
    assert (p[:, ice] == p[:, snow]).all()  # one level: one solve, the same usual snow
    assert usual[:, ice].tolist() == usual[:, snow].tolist()


def test_a_stalled_forecast_host_holds_a_pass_no_longer_than_its_time_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # B1: the adjustment's reader has the outlook's limits: a host that accepts and stalls
    # costs a pass its time limit and one request under way, and the pass serves the class
    # levels with no previous chance.
    built, _anchor = adjusting_model(NATION)
    clock = [0.0]
    monkeypatch.setattr(
        history,
        "clock",
        SimpleNamespace(sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)),
    )
    asked: list[str] = []

    def stall(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        clock[0] += 10.0  # each request runs to its read limit
        raise httpx.ReadTimeout("stalled", request=request)

    budget = outlook_live.Budget(seconds=outlook_live.ADJUST_SECONDS, clock=lambda: clock[0])
    fetcher = history.Fetcher(
        httpx.Client(transport=httpx.MockTransport(stall)),
        attempts=outlook_live.READ_ATTEMPTS,
        before=budget.check,
        left=budget.remaining,
    )
    reader = outlook_live.settled_reader(
        outlook_live.forecast_reader(fetcher, 0.5, outlook_live.prune_days), budget
    )
    days = (date(2026, 1, 14), date(2026, 1, 15))
    at = world.utc("2026-01-14T05:07:00")  # past every zone's snapshot for the 14th
    found = reader(built, days, at)
    assert clock[0] <= outlook_live.ADJUST_SECONDS + 10.0 + 2.0
    assert not any(found.by_day.values())
    assert found.problems
    assert len(asked) <= math.ceil(outlook_live.ADJUST_SECONDS / 10.0) + 1
    # The next pass has its own time.
    clock[0] = 0.0
    asked.clear()
    reader(built, days, at + timedelta(minutes=30))
    assert asked
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    made = forecast_file(
        built, classes, days, at, closed_on=lambda _d: None, last=None, forecasts=found,
        adjust=True,
    )  # fmt: skip
    for entry in made.districts:
        for day in entry.days:
            assert isinstance(day, Forecast)
            assert (day.p_no_school, day.why.reasons, day.previous) == (0.1, (), None)


NIGHT = date(2025, 1, 6)  # a Monday; Chicago's class snapshot is 03:00Z
CHICAGO = "America/Chicago"


class Feed:
    """A synthetic NDFD run (tests/predict/grib.py: made-up constant fields) read range by
    range through a pass's :class:`outlook_live.Budget`, each range read a second on its
    clock, with the live reader (:func:`forecast_live.run_reader` over
    :func:`forecast_history.run_values`, :func:`forecast_live.forecasts` at the class snapshot,
    :func:`outlook_live.settled_reader`)."""

    def __init__(self, built: ServeModel) -> None:
        reference = world.utc("2025-01-06T03:00:00")
        store: dict[str, bytes] = {}
        files = {
            # 3 inches in the period ending 06Z (half still to come at 03Z) and 4 by 12Z.
            ndfd.Element.SNOW: fh_test.amounts(reference, {6: 0.0762, 12: 0.1016}),
            ndfd.Element.ICE: fh_test.amounts(reference, {}, element=ndfd.Element.ICE),
            ndfd.Element.APT: fh_test.apt(reference, 263.0),
        }
        (self.run,) = ndfd.assemble_runs(fh_test.make_run("2025-01-06T02:46", files, store)).runs
        self.store = store
        self.clock = [0.0]
        self.reads = 0
        self.broken: set[ndfd.Element] = set()
        self.budget = outlook_live.Budget(seconds=1e9, clock=lambda: self.clock[0])
        self.cache: dict[tuple[datetime, date], history.RunValues] = {}
        self.schools = history.deciding_schools(built.directory, built.artifact)
        self.index = {leaid: i for i, leaid in enumerate(built.directory.district_ids)}
        self.reader = outlook_live.settled_reader(self._read, self.budget)

    def _open(self, item: ndfd.Listed) -> ndfd.Ranged:
        data = self.store[item.url]

        def read(offset: int, size: int) -> bytes:
            self.budget.check()  # the fetcher's ``before``
            self.clock[0] += 1.0
            self.reads += 1
            if item.element in self.broken:
                raise ndfd.NdfdError(f"HTTP 503 for a range of {item.url}")
            return data[offset : offset + size]

        return read

    def _read(
        self,
        _model: ServeModel,
        days: tuple[date, ...],
        now: datetime,
        moment: object,
        zones: object,
    ) -> Forecasts:
        assert callable(moment)
        assert isinstance(zones, list)
        outlook_live.prune_days(self.cache, now)
        return forecast_live.forecasts(
            self.schools,
            self.index,
            days,
            now,
            lambda _day: [self.run],
            forecast_live.run_reader(self.schools, self._open, self.cache),
            0.5,
            moment=moment,
            zones=zones,
        )

    def read(self, built: ServeModel, now: datetime, seconds: float = 1e9) -> Forecasts:
        """One pass: its own time for reads, from a fresh clock."""
        self.budget.seconds = seconds
        self.clock[0] = 0.0
        self.reads = 0
        return self.reader(built, (NIGHT, NIGHT + timedelta(days=1)), now)


def test_a_run_read_that_fails_part_way_is_a_failed_read_kept_lines_and_no_previous() -> None:
    # T-R3-B1: a pass whose time runs out after the listing, mid run read, is a failed read:
    # the zone is unread with one warning line, nothing is kept for the day, the last file's
    # lines of the same snapshot stand with no previous chance; the next pass, with its own
    # time, reads the run again and serves the adjusted chance.
    built, _anchor = adjusting_model(NATION)
    days = (NIGHT, NIGHT + timedelta(days=1))
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    feed = Feed(built)
    at = world.utc("2025-01-06T03:07:00")
    whole = feed.read(built, at)
    full = feed.reads
    assert whole.problems == ()
    assert whole.unread == {}
    read = whole.get(NIGHT, 1)
    assert read is not None
    assert read.snow == pytest.approx(5.5)
    assert set(feed.cache) == {(feed.run.time, NIGHT)}

    def made(when: datetime, found: Forecasts, last: PredictionsFile | None) -> PredictionsFile:
        return forecast_file(
            built, classes, days, when, closed_on=lambda _d: None, last=last, forecasts=found,
            adjust=True, read_last=None,
        )  # fmt: skip

    def day_one(file: PredictionsFile) -> Forecast:
        item = file.districts[1].days[0]
        assert isinstance(item, Forecast)
        return item

    on = made(at, whole, None)
    assert day_one(on).p_no_school > 0.1
    assert day_one(on).why.reasons
    # A restart (the cache is per process), then a pass whose time runs out mid run read.
    feed.cache.clear()
    later = at + timedelta(minutes=30)
    short = feed.read(built, later, seconds=full // 2)
    assert 0 < feed.reads < full
    assert not any(short.by_day.values())
    assert short.unread == {NIGHT: {CHICAGO: "error"}}
    (line,) = short.problems
    assert CHICAGO in line
    assert "forecast reads are up" in line
    assert "read again next pass" in line
    assert feed.cache == {}
    failed = made(later, short, on)
    assert (day_one(failed).p_no_school, day_one(failed).why) == (
        day_one(on).p_no_school,
        day_one(on).why,
    )
    assert day_one(failed).previous is None
    # The read memory counts only the district-days read without error.
    run = SimpleNamespace(adjust_reads={})
    cli._keep_reads(run, failed, short)  # type: ignore[arg-type]
    assert run.adjust_reads == {failed.generated_at: frozenset()}
    # Where no lines of the same snapshot are kept, the class level with no "Down from".
    lost = made(later, short, on.model_copy(update={"generated_at": at - timedelta(hours=2)}))
    assert (day_one(lost).p_no_school, day_one(lost).previous) == (0.1, None)
    # The next pass has its own time: it reads the run again and serves the adjusted chance.
    again = feed.read(built, later + timedelta(minutes=30))
    assert feed.reads == full
    assert again.problems == ()
    assert again.get(NIGHT, 1) == read
    back = made(later + timedelta(minutes=30), again, failed)
    assert (day_one(back).p_no_school, day_one(back).why) == (
        day_one(on).p_no_school,
        day_one(on).why,
    )
    assert day_one(back).previous is None
    assert set(feed.cache) == {(feed.run.time, NIGHT)}


@pytest.mark.parametrize("element", [ndfd.Element.ICE, ndfd.Element.APT])
def test_a_run_with_one_element_that_did_not_read_is_not_kept_for_the_day(
    element: ndfd.Element,
) -> None:
    # T-R3-B1: an element whose range read fails twice leaves the run unread, never a run
    # read with that element unknown, and never kept: the next pass reads it again.
    built, _anchor = adjusting_model(NATION)
    feed = Feed(built)
    feed.broken = {element}
    at = world.utc("2025-01-06T03:07:00")
    found = feed.read(built, at)
    assert found.get(NIGHT, 1) is None
    assert found.unread == {NIGHT: {CHICAGO: "error"}}
    (line,) = found.problems
    assert f"{element.value}: read: HTTP 503" in line
    assert CHICAGO in line
    assert feed.cache == {}
    # Later the same morning (the day not over), the element reads: the run is read again.
    feed.broken = set()
    morning = world.utc("2025-01-06T11:07:00")
    again = feed.read(built, morning)
    assert feed.reads > 0
    assert again.problems == ()
    assert again.get(NIGHT, 1) is not None
    assert set(feed.cache) == {(feed.run.time, NIGHT)}


def test_the_reader_reads_the_largest_zones_first() -> None:
    # T-R3-S1: a pass whose time runs out part-way leaves the fewest districts unread.
    sizes = {"America/Denver": 1, "America/New_York": 3, "America/Chicago": 2}
    zones = [zone for zone, count in sizes.items() for _ in range(count)]
    schools = history.Schools(
        lat=np.full(len(zones), 40.0),
        lon=np.full(len(zones), -90.0),
        district=np.arange(len(zones), dtype=np.int64),
        districts=tuple(f"{d:07d}" for d in range(len(zones))),
        zone_of_district=tuple(zones),
    )
    asked: list[str] = []

    def moment(day: date, zone: str) -> datetime:
        asked.append(zone)
        return fa.snapshot(day, zone)

    forecast_live.forecasts(
        schools, {}, (DAY,), world.utc("2026-01-14T14:00:00"), lambda _d: [],
        lambda _r, _d: history.RunValues(ndfd.Run(RUN, {}, RUN)), 0.5, moment=moment,
    )  # fmt: skip
    assert asked == ["America/New_York", "America/Chicago", "America/Denver"]


def test_a_host_that_drips_bytes_holds_a_read_no_longer_than_the_time_limit() -> None:
    # S-R2-4: each gap under the read limit, but the answer never ends: the read stops once
    # the pass's time is up, one gap after it at most.
    clock = [0.0]
    budget = outlook_live.Budget(seconds=outlook_live.ADJUST_SECONDS, clock=lambda: clock[0])
    budget.start()

    class Drip(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            for _ in range(10_000):
                clock[0] += 9.0  # under the 10 s read limit each time
                yield b"x"

    def slow(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=Drip())

    fetcher = history.Fetcher(
        httpx.Client(transport=httpx.MockTransport(slow)),
        attempts=outlook_live.READ_ATTEMPTS,
        before=budget.check,
        left=budget.remaining,
    )
    with pytest.raises(ndfd.NdfdError, match="ran out"):
        fetcher.get("https://example.test/slow")
    assert clock[0] <= outlook_live.ADJUST_SECONDS + 9.0
    # A whole answer within the time reads as before.
    whole = history.Fetcher(
        httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=b"ok"))),
        left=budget.remaining,
    )
    clock[0] = 0.0
    budget.start()
    assert whole.get("https://example.test/ok") == b"ok"


def test_a_pass_keeps_the_district_days_it_read_for_the_next_pass_only() -> None:
    # S-R2-3: the loop knows which district-days its last pass read, by that file's time.
    run = SimpleNamespace(adjust_reads={RUN: frozenset({(9, DAY)})})
    made = SimpleNamespace(generated_at=SNAPSHOT)
    found = Forecasts({DAY: {1: forecast(1.0), 3: forecast(0.0)}, DAY + timedelta(days=1): {}})
    cli._keep_reads(run, made, found)  # type: ignore[arg-type]
    assert run.adjust_reads == {SNAPSHOT: frozenset({(1, DAY), (3, DAY)})}
    cli._keep_reads(run, made, NO_FORECASTS)  # type: ignore[arg-type]
    assert run.adjust_reads == {SNAPSHOT: frozenset()}


def test_the_adjustment_keeps_a_day_s_runs_until_the_day_has_passed() -> None:
    # S-R2-2: every pass reads each zone's run at the day's snapshot, so its values are kept
    # until the day is over everywhere, never re-read each morning after 4 hours.
    values = history.RunValues(ndfd.Run(RUN, {}, RUN))
    cache = {
        (RUN, DAY): values,
        (RUN, DAY - timedelta(days=1)): values,
        (RUN - timedelta(days=2), DAY - timedelta(days=2)): values,
    }
    outlook_live.prune_days(cache, world.utc("2026-01-14T17:37:00"))  # noon Eastern on the day
    assert set(cache) == {(RUN, DAY), (RUN, DAY - timedelta(days=1))}
    outlook_live.prune_days(cache, world.utc("2026-01-15T17:37:00"))  # the next day
    assert set(cache) == {(RUN, DAY)}
    kept = dict(cache)
    outlook_live.prune_days(cache, world.utc("2026-01-16T00:07:00"))  # over in Hawaii too
    assert not cache
    outlook_live.prune_runs(kept, world.utc("2026-01-14T17:37:00"))  # the outlook's rule
    assert not kept


def test_the_adjustment_reads_only_days_and_zones_past_their_class_snapshot() -> None:
    # Turn-on items 8 and 10: a Saturday 8 PM Eastern pass reads nothing for Monday (its
    # snapshot is Sunday 9 PM), a weekday evening pass nothing for the day after next, and a
    # pass at 9:30 PM Eastern reads Eastern's and Central's... only those past 9 PM.
    built, _anchor = adjusting_model(NATION)
    calls: list[tuple[tuple[date, ...], datetime, tuple[str, ...]]] = []

    def read(
        _model: ServeModel,
        days: tuple[date, ...],
        now: datetime,
        moment: object,
        zones: object,
    ) -> Forecasts:
        assert callable(moment)
        assert isinstance(zones, list)
        for day in days:
            for zone in zones:
                assert moment(day, zone) == fa.snapshot(day, zone) <= now
        calls.append((days, now, tuple(zones)))
        return NO_FORECASTS

    budget = outlook_live.Budget()
    reader = outlook_live.settled_reader(read, budget)
    monday = date(2026, 1, 19)
    reader(built, (monday,), world.utc("2026-01-18T01:00:00"))  # Saturday 8 PM EST
    assert calls == []
    reader(built, (date(2026, 1, 14), date(2026, 1, 15)), world.utc("2026-01-14T03:30:00"))
    assert calls == [((date(2026, 1, 14),), world.utc("2026-01-14T03:30:00"), ("America/Chicago",))]
    assert forecast_live.readable(monday, world.utc("2026-01-18T01:00:00"))  # the old rule did


def test_each_pass_notes_the_mean_shift_off_the_class_levels() -> None:
    built, _anchor = adjusting_model(NATION)
    days = (date(2026, 1, 14), date(2026, 1, 15))
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    found = Forecasts({days[0]: {1: forecast(6.0)}})
    made = forecast_file(
        built, classes, days, world.utc("2026-01-14T03:07:00"), closed_on=lambda _d: None,
        last=None, forecasts=found, adjust=True,
    )  # fmt: skip
    first = made.districts[1].days[0]
    assert isinstance(first, Forecast)
    note = fa.shift_note(made)
    assert note is not None
    shift = (first.p_no_school - 0.1) / (len(world.DISTRICTS) * 2)
    assert note == f"forecast adjustment: advisory 10 days, 1 moved, mean {shift:+.4f}"


def test_a_day_said_open_keeps_the_floor_whatever_the_forecast() -> None:
    built, _anchor = adjusting_model(NATION)
    days = (date(2026, 1, 14), date(2026, 1, 15))
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    forecasts = Forecasts({days[0]: {1: forecast(9.0)}})
    said = SaidOpen(districts={days[0]: frozenset({1})})
    at = world.utc("2026-01-14T03:00:00")
    made = forecast_file(
        built, classes, days, at, closed_on=lambda _d: None, last=None, forecasts=forecasts,
        adjust=True, said=said,
    )  # fmt: skip
    first = made.districts[1].days[0]
    assert isinstance(first, Forecast)
    assert first.p_no_school == 0.01


def test_with_forecast_adjust_off_or_no_climate_the_anchor_carries_none(tmp_path: Path) -> None:
    off = CONFIG.model_copy(
        update={"serve": CONFIG.serve.model_copy(update={"forecast_adjust": "off"})}
    )
    anchor = serving_anchor(off, world.model(), folder=tmp_path)
    assert anchor is not None
    assert anchor.climate is None
    said: list[str] = []
    missing = serving_anchor(
        CONFIG,
        world.model(),
        folder=tmp_path,
        climate_path=tmp_path / "none.json.gz",
        warn=said.append,
    )
    assert missing is not None
    assert missing.climate is None
    assert said == ["anchor: the forecast climate: FileNotFoundError: the class levels alone"]
    on = serving_anchor(CONFIG, world.model(), folder=tmp_path)
    assert on is not None
    assert on.climate is not None
    assert on.adjust == SETTINGS


def test_the_registered_settings_are_the_module_s_and_refuse_a_bad_block() -> None:
    assert SETTINGS.classes == ("advisory", "warning")
    block = dict(CONFIG.live_score["forecast_adjustment"])
    block["ice_snow"] = -25
    bad = CONFIG.model_copy(
        update={"live_score": {**CONFIG.live_score, "forecast_adjustment": block}}
    )
    with pytest.raises(ValueError, match="only add"):
        fa.AdjustSettings.of(bad)
    assert timedelta(hours=6) == ndfd.PERIOD
