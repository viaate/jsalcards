"""The snow amount term (predict-next SNOW-AMOUNT, registered on by SNOW-AMOUNT-2): with
``snow_amount`` on, each class has its own slope, the day's total is never under the snow
alone's floor and over the class's upper bound it bends toward its asymptote instead of
stopping; it only rises with snow for every usual, ice, timing, cold and class order cap,
serving holds the total exactly as the solve does (also with a cap under 0: SA-R2-S4), keeps
the class order, each district's days still average its class level, no usual is solved at
the range's end, G6 holds and the published chance stays in the floor and ceiling. Off, the
forecast adjustment is L5's exactly."""

import itertools
import math
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from predict import test_forecast_adjust as base
from snowlight.predict import anchor as an
from snowlight.predict import forecast_adjust as fa
from snowlight.predict import serve
from snowlight.predict.artifact import ARTIFACT_PATH, ModelArtifact
from snowlight.predict.exposure import Exposure
from snowlight.predict.forecast_values import DistrictForecast
from snowlight.predict.geography import REGION_OF
from snowlight.predict.serve import SITUATION_POSITION
from snowlight.predict.situations import SITUATIONS

ON = fa.AdjustSettings.of(base.CONFIG)
"""As registered (SNOW-AMOUNT-2: on)."""
OFF = replace(ON, snow_amount=False)
"""L5 as served before SNOW-AMOUNT-2."""
DAY, EAST = base.DAY, base.EAST
AMOUNTS = (0.0, 0.1, 0.3, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 9.0, 12.0, 18.0, 24.0, 30.0)


def raw(  # noqa: PLR0913, PLR0917 - the day and the place
    settings: fa.AdjustSettings,
    found: DistrictForecast,
    usual: float,
    alone: float | None,
    klass: str,
    p0: float,
) -> float:
    """The unrounded chance on ``found`` (:func:`fa.raw_chance`)."""
    return fa.raw_chance(p0, klass, usual, found, DAY, EAST, settings, alone)


def test_registered_on_and_off_is_l5_exactly() -> None:
    block = base.CONFIG.live_score["forecast_adjustment"]
    assert block["snow_amount"] is True
    assert block["snow_amount_high"] == pytest.approx(3.0)
    assert block["snow_amount_floor_ratio"] == pytest.approx(3.0)
    assert block["snow_amount_slope_advisory"] == pytest.approx(1.65)
    assert block["snow_amount_slope_warning"] == pytest.approx(3.0)
    assert block["snow_per_log"] == pytest.approx(1.0)
    assert ON.snow_amount
    assert ON.for_class("advisory").snow_per_log == pytest.approx(1.65)
    assert ON.for_class("warning").snow_per_log == pytest.approx(3.0)
    assert OFF.for_class("warning") is OFF
    assert not OFF.snow_amount
    totals = np.linspace(-3, 6, 91)
    for low, high in OFF.bounds.values():
        assert fa.saturated(totals, low, high, OFF).tolist() == np.clip(totals, low, high).tolist()
        for most in (-2.0, 0.3, 5.0):
            assert fa.saturated(totals, low, high, OFF, most).tolist() == (
                np.clip(totals, low, min(high, max(most, low))).tolist()
            )
    assert not fa.floor_lift(totals, 2.0, 3.0, 0.5, OFF).any()
    # Off, passing the snow alone's usual changes nothing (serving now passes it always).
    for inches, ice in itertools.product(AMOUNTS, (0.0, 0.1)):
        found = base.forecast(inches, ice=ice)
        assert raw(OFF, found, 3.55, 1.5, "warning", 0.45) == raw(
            OFF, found, 3.55, None, "warning", 0.45
        )


def test_a_bad_snow_amount_block_is_refused() -> None:
    for key, value in (
        ("snow_amount", "yes"),
        ("snow_amount_high", 0.0),
        ("snow_amount_high", 1.9),  # under the advisory's upper bound
        ("snow_amount_floor_ratio", 0.5),
        ("snow_amount_slope_warning", "steep"),
        ("snow_amount_slope_advisory", 0.5),  # the timing band would fall with more snow
        ("snow_amount_slope_warning", -1.0),
    ):
        block = dict(base.CONFIG.live_score["forecast_adjustment"])
        block[key] = value
        bad = base.CONFIG.model_copy(
            update={"live_score": {**base.CONFIG.live_score, "forecast_adjustment": block}}
        )
        with pytest.raises(
            ValueError, match=key.removesuffix("_advisory").removesuffix("_warning")
        ):
            fa.AdjustSettings.of(bad)


@pytest.mark.parametrize("klass", ["advisory", "warning"])
def test_on_more_snow_ice_or_cold_never_lowers_the_chance_over_a_grid(klass: str) -> None:
    # Every usual, snow alone's usual (icy places' under it), ice, timing and cold: the total
    # and the chance only rise with the snow, and with the ice and the cold.
    for usual, share, p0 in itertools.product(
        (0.3, 1.0, 1.45, 3.19, 6.0), (1.0, 0.5, 0.1), (0.1, 0.45)
    ):
        alone = usual * share
        for ice, feels, split in itertools.product(
            (0.0, 0.01, 0.05, 0.1, 0.25), (25, 5, -20), (None, (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))
        ):
            chances = [
                raw(
                    ON, base.forecast(s, ice=ice, feels=feels, split=split), usual, alone, klass, p0
                )
                for s in AMOUNTS
            ]
            assert all(b >= a - 1e-12 for a, b in itertools.pairwise(chances)), (usual, ice, split)
        for s in AMOUNTS:
            iced = [
                raw(ON, base.forecast(s, ice=i), usual, alone, klass, p0) for i in (0, 0.05, 0.25)
            ]
            cold = [
                raw(ON, base.forecast(s, feels=f), usual, alone, klass, p0) for f in (25, 5, -20)
            ]
            assert all(b >= a - 1e-12 for a, b in itertools.pairwise(iced))
            assert all(b >= a - 1e-12 for a, b in itertools.pairwise(cold))


def test_on_big_snow_never_reaches_a_flat_cap() -> None:
    # L5 stops at its upper bound (a typical warning district, usual 3.19 in: 20 and 30 inches
    # read the same); over it the total bends toward snow_amount_high, never at it, and up to
    # it the chance is L5's shape at the class's slope exactly (SA-R1-S1: no mid-range loss
    # from the bend).
    for usual, klass, p0 in ((3.19, "warning", 0.45), (1.45, "advisory", 0.12)):
        off = [raw(OFF, base.forecast(s), usual, None, klass, p0) for s in (20.0, 30.0)]
        on = [raw(ON, base.forecast(s), usual, None, klass, p0) for s in (18.0, 24.0, 30.0, 60.0)]
        assert off[0] == off[1]
        assert on == sorted(on)
        assert len(set(on)) == len(on)
        top = 1 / (1 + math.exp(-(math.log(p0 / (1 - p0)) + ON.snow_amount_high)))
        assert on[-1] < top
        high = ON.bounds[klass][1]
        sloped = replace(OFF, snow_per_log=ON.snow_amount_slopes[klass])
        for s in AMOUNTS:
            parts = fa.term_parts(base.forecast(s), usual, klass, DAY, EAST, sloped)
            if parts is not None and sum(parts.raw) <= high:
                assert raw(ON, base.forecast(s), usual, None, klass, p0) == pytest.approx(
                    raw(sloped, base.forecast(s), usual, None, klass, p0), abs=1e-12
                )


@pytest.mark.parametrize("settings", [OFF, ON], ids=["off", "on"])
@pytest.mark.parametrize("klass", ["advisory", "warning"])
def test_serving_holds_each_code_s_total_exactly_as_the_solve_does(
    klass: str, settings: fa.AdjustSettings
) -> None:
    # SA-R1-B1: the usual is solved on climate_terms; serving adds term_parts' bounded terms.
    # For every code, cold morning, usual, snow alone's usual and class order cap the two
    # totals are one, with the term off and on, so the solve's re-centring is what serves.
    # A deployed cap is never under 0 (every deployed warning level at its lower bound is over
    # the advisory level: docs/predict.md, "Class order", the least gap 0.56 log-odds), but
    # SA-R2-S4: under 0, with every term lowering (or none), the two still agree (the guard in
    # :func:`fa.bounded`).
    feels = [25, *(int(f) for f in fa.COLD_FEELS[1:])]
    for usual, share, most in itertools.product(
        (0.3, 1.0, 3.19, 6.0), (1.0, 0.4, 0.05), (None, -0.6, -0.3, 0.0, 0.3, 1.2, 1.8)
    ):
        alone = usual * share
        cap = None if most is None else np.full((1, fa.CODES - 1, len(fa.COLD_FEELS)), most)
        solve = fa.climate_terms(
            np.array([usual]), np.ones(1), klass, settings, alone=np.array([alone]), most=cap
        )[0]
        for code, m in itertools.product(range(fa.CODES - 1), range(len(fa.COLD_FEELS))):
            if code in fa.COLD_CODES and fa.COLD_CODES.index(code) + 1 != m:
                continue
            found = base.forecast(fa.SNOW_CODE[code], ice=fa.ICE_CODE[code], feels=feels[m])
            parts = fa.term_parts(found, usual, klass, DAY, EAST, settings, alone, most)
            assert parts is not None
            assert sum(parts.bounded) == pytest.approx(float(solve[code, m]), abs=1e-9), (
                usual, alone, most, code, m,
            )  # fmt: skip


@pytest.mark.parametrize("settings", [OFF, ON], ids=["off", "on"])
def test_the_bounded_terms_always_add_up_to_the_held_total(settings: fa.AdjustSettings) -> None:
    # SA-R2-S4: a class order cap under 0 with every term lowering (or every term 0) has no
    # raising term to scale; the lowering terms (or the snow's) take it, so serving's sum is
    # the solve's total. Every other case scales as before: a side's terms keep their signs.
    rng = np.random.default_rng(3)
    for _ in range(3000):
        values = list(rng.choice([0.0, 1.0], 4) * rng.normal(0, 1.2, 4))
        values[3] = abs(values[3])  # the cold only adds
        most = None if rng.random() < 0.2 else float(rng.uniform(-1.5, 2.5))
        for low, high in settings.bounds.values():
            found = fa.bounded(values, low, high, settings, most)
            target = float(fa.saturated(sum(values), low, high, settings, most))
            assert float(sum(found)) == pytest.approx(target, abs=1e-12), (values, most)
            for value, term in zip(values[1:], found[1:], strict=True):
                assert value * float(term) >= 0, (values, most)
    # The case the critic found: every term lowering, the cap under their sum.
    found = fa.bounded([-0.1, -0.05, 0.0, 0.0], -0.7, 2.0, settings, -0.4)
    assert float(sum(found)) == pytest.approx(-0.4, abs=1e-12)
    assert all(float(term) <= 0 for term in found)


def test_on_snow_over_the_snow_alone_s_usual_never_lowers_an_icy_place_s_day() -> None:
    # PHYS-R3-S1 (i): an icy place's usual counts its ice days (Memphis-Shelby's warning: 3.55
    # in, 1.50 alone); off, 2 inches with no ice lower its day; on, snow from its snow alone's
    # usual up never does, and with no snow ahead the day is lowered as before.
    usual, alone = 3.55, 1.50
    assert raw(OFF, base.forecast(2.0), usual, alone, "warning", 0.45) < 0.45
    for s in (1.5, 2.0, 3.0, 3.5):
        assert raw(ON, base.forecast(s), usual, alone, "warning", 0.45) >= 0.45 - 1e-12
    assert raw(ON, base.forecast(0.0), usual, alone, "warning", 0.45) < 0.45
    # Late snow still lowers on the timing term, under the floor's even snow (1.4 in: under the
    # snow alone's usual, over the lower bound with the warning's slope).
    late = base.forecast(1.4, split=(0.0, 0.0, 1.0))
    even = base.forecast(1.4)
    assert raw(ON, late, usual, alone, "warning", 0.45) < raw(
        ON, even, usual, alone, "warning", 0.45
    )


def mean_on(p0: float, counts: np.ndarray, usual: float, alone: float, klass: str) -> float:
    """A place's adjusted chance averaged over its climate's days and mornings, with ``ON``."""
    terms = fa.climate_terms(np.array([usual]), np.ones(1), klass, ON, alone=np.array([alone]))[0]
    weight = (counts / counts.sum())[:, None] * fa.cold_mix(counts[None, :])[0]
    z0 = math.log(p0 / (1 - p0))
    return float((weight / (1 + np.exp(-(z0 + terms)))).sum())


@pytest.mark.parametrize("klass", ["advisory", "warning"])
def test_on_each_place_s_days_still_average_its_class_level(klass: str) -> None:
    rng = np.random.default_rng(5)
    count = 200
    counts = rng.poisson(rng.uniform(0, 12, (count, fa.CODES - 1))).astype(np.float64)
    counts[:, 0] += 1
    p0 = rng.uniform(0.02, 0.9, count)
    scale = np.ones(count)
    alone = fa.usual_snow(p0, fa.ice_as_quiet(counts), scale, klass, ON)
    usual = fa.usual_snow(p0, counts, scale, klass, ON, alone=alone)
    inside = np.isfinite(usual) & np.isfinite(alone)
    assert inside.mean() > 0.8
    for i in np.flatnonzero(inside):
        found = mean_on(float(p0[i]), counts[i], float(usual[i]), float(alone[i]), klass)
        assert found == pytest.approx(float(p0[i]), abs=1e-6)


@pytest.fixture(scope="module")
def solved_on() -> SimpleNamespace:
    """Every 15th district of the committed climate solved as serving solves it with ``ON``."""
    artifact = ModelArtifact.from_bytes(ARTIFACT_PATH.read_bytes())
    climate = fa.load()
    leaids = sorted(set(climate.districts) & set(artifact.districts))[::15]
    places = [
        (d, artifact.districts[d].county, REGION_OF.get(artifact.districts[d].state or ""))
        for d in leaids
    ]
    zones = [artifact.districts[d].time_zone or EAST for d in leaids]
    anchor = replace(
        an.fit(
            an.AnchorSettings.of(base.CONFIG), Exposure((), {}, {}, {}, {}, {}), an.NO_LABELS, {}
        ),
        climate=climate,
        adjust=ON,
    )
    p = np.full((len(leaids), len(SITUATIONS)), 0.05)
    for k, situation in enumerate(SITUATIONS):
        klass = anchor.class_of(situation.key)
        for i in range(len(leaids)):
            advisory, warning = base.LEVELS[i % len(base.LEVELS)]
            p[i, k] = {"advisory": advisory, "warning": warning, "cold": 0.1}.get(klass or "", 0.05)
    usual, alone, check = serve._usual_snow(anchor, p, places, zones, an.Grid(0.01, 0.99))
    built, _ = base.adjusting_model(base.NATION)
    model = replace(
        built, p=p, usual_snow=usual, snow_usual=alone, anchor=anchor, time_zone=tuple(zones)
    )
    return SimpleNamespace(leaids=leaids, zones=zones, p=p, usual=usual, alone=alone,
                           check=check, model=model)  # fmt: skip


def test_on_g6_holds_and_every_district_is_solved(solved_on: SimpleNamespace) -> None:
    assert solved_on.check is not None
    assert solved_on.check.failing == ()
    for key in ("advisory", "snow_warning"):
        k = SITUATION_POSITION[key]
        usual = solved_on.usual[:, k]
        assert np.isfinite(usual).mean() > 0.99
        # SA-R1-B2: a usual at the range's end is a plateau, not a solve.
        assert (usual[np.isfinite(usual)] < 0.999 * ON.usual_max).all()


def test_on_each_solved_district_s_chance_rises_with_the_snow(solved_on: SimpleNamespace) -> None:
    # SA-R1-B2: from 1 to 30 inches the chance never falls; it is level only where the snow
    # alone's floor holds the day at its class level (between the floor's anchor and the
    # usual) or at the class's lower bound, and it rises strictly from the usual up, so no
    # district's chance is flat in the snow.
    inches = [float(s) for s in range(1, 31)]
    for key, klass in (("advisory", "advisory"), ("snow_warning", "warning")):
        k = SITUATION_POSITION[key]
        low = ON.bounds[klass][0]
        for i in range(0, len(solved_on.leaids), 2):
            usual, alone = float(solved_on.usual[i, k]), float(solved_on.alone[i, k])
            if not math.isfinite(usual):
                continue
            anchor = min(max(alone, usual / ON.snow_amount_floor_ratio), usual)
            totals = []
            for s in inches:
                parts = fa.term_parts(base.forecast(s), usual, klass, DAY, EAST, ON, alone)
                assert parts is not None
                totals.append(sum(parts.bounded))
            for (s, a), (t, b) in itertools.pairwise(zip(inches, totals, strict=True)):
                assert b >= a - 1e-12, (i, key, s)
                if b <= a + 1e-12:
                    held = anchor - 1e-9 <= s and t <= usual + 1e-9 and abs(b) <= 1e-12
                    assert held or b <= low + 1e-12, (i, key, s, usual, alone)
                    assert t <= usual + 1e-9, (i, key, s, usual)


def test_on_the_served_path_keeps_the_class_order_the_direction_and_the_floor_and_ceiling(
    solved_on: SimpleNamespace,
) -> None:
    model = solved_on.model
    for i in range(0, len(solved_on.leaids), 7):
        zone = solved_on.zones[i]
        for ice, feels in ((0.0, 25), (0.1, 25), (0.0, -20)):
            last: dict[str, float] = {}
            for inches in AMOUNTS:
                found = base.spread(zone, inches, "even", ice=ice, feels=feels)
                chances = {}
                for key in ("advisory", "snow_warning", "lake_snow", "ice"):
                    k = SITUATION_POSITION[key]
                    klass = "advisory" if key == "advisory" else "warning"
                    p0, usual = float(model.p[i, k]), float(model.usual_snow[i, k])
                    cap = serve._order_cap(model, model.anchor, i, klass, DAY, zone, found)
                    moved = fa.adjusted(
                        p0, 0.1, klass, usual, found, DAY, zone, ON, 0.01, 0.99,
                        snow_usual=float(model.snow_usual[i, k]), cap=cap,
                    )  # fmt: skip
                    shown = p0 if moved is None else moved.p_no_school
                    assert 0.01 <= shown <= 0.99
                    chances[key] = shown
                    assert shown >= last.get(key, 0.0)
                assert chances["advisory"] <= min(
                    chances[key] for key in ("snow_warning", "lake_snow", "ice")
                )
                last = chances
