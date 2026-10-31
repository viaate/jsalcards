"""The class anchor (advisory-sane L3): priors, the live update, standing, plausibility, serving.

Every row, market and count here is made up for the tests (synthetic labels in the record's
format); none comes from a real list or a real storm.
"""

import argparse
import gzip
import json
import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from predict import world
from snowlight.predict import anchor as an
from snowlight.predict import anchor_labels, exposure
from snowlight.predict.anchor_labels import read_labels, serving_anchor
from snowlight.predict.config import CONFIG_PATH
from snowlight.predict.exposure import CLASSES, Exposure, Tally
from snowlight.predict.serve import SITUATION_POSITION, ServeModel, build_model, forecast_file
from snowlight.predict.situations import SITUATIONS, Situation, WeatherClass
from snowlight.predict.why import class_base
from snowlight.schemas.predictions import ClassBase, Forecast, PredictionsFile

SETTINGS = an.AnchorSettings.of(world.CONFIG)
DAY = date(2026, 11, 3)
SURE: dict[an.Tier, an.Trials] = {"A": an.Trials(hits=100_000, trials=100_000, dates=50)}
"""Trials that make tier A's sensitivity 1 to four places."""


def rows(
    market_days: int, per_day: int, closed: int = 0, *, tier: an.Tier = "A", start: int = 0
) -> list[an.LiveRow]:
    """``market_days`` market-days of ``per_day`` advisory rows, ``closed`` of each closed."""
    found: list[an.LiveRow] = []
    for j in range(start, start + market_days):
        for i in range(per_day):
            found.append(
                an.LiveRow(
                    day=DAY + timedelta(days=j),
                    district=f"99{j:02d}{i:03d}",
                    market=f"market-{j}",
                    tier=tier,
                    label="no_school" if i < closed else "unnamed",
                    weather="advisory",
                )
            )
    return found


def level(found: list[an.LiveRow], trials: dict[an.Tier, an.Trials] | None = None) -> float:
    fitted = an.fit_class("advisory", found, lambda _d: 0.0, trials or {}, SETTINGS)
    return float(fitted.level(0.0))


EMPTY = Exposure((), {}, {}, {}, {}, {})


# --- the registered priors and the live update ---------------------------------------------------


def test_with_no_label_each_class_serves_its_registered_target() -> None:
    found = an.fit(SETTINGS, EMPTY, an.NO_LABELS, {})
    assert abs(float(found.fits["advisory"].level(0.0)) - 0.100) <= 0.002
    assert abs(float(found.fits["cold"].level(0.0)) - 0.100) <= 0.002
    assert abs(float(found.fits["warning"].level(0.0)) - 0.449) <= 0.003
    low, high = found.fits["advisory"].band
    assert 0.03 < low < 0.06  # the registered 80% band, 4.3% to 20.6%
    assert 0.18 < high < 0.23
    assert found.fits["advisory"].q == pytest.approx(0.11, abs=0.002)  # Beta(1.1, 8.9)


def test_three_hundred_unnamed_rows_bring_the_advisory_level_down() -> None:
    assert level(rows(10, 30), SURE) < 0.03


def test_the_market_day_effect_absorbs_two_all_closed_days() -> None:
    quiet = rows(8, 30)
    storms = [
        *rows(1, 117, 117, start=20),
        *rows(1, 110, 110, start=21),
    ]
    clustered = level([*quiet, *storms], SURE)
    assert clustered < 0.5
    assert clustered > level(quiet, SURE)


def test_a_less_sensitive_list_leaves_the_level_higher() -> None:
    found = rows(10, 30, 1)
    sure = level(found, SURE)
    blunt = level(found, {"A": an.Trials(hits=2, trials=3, dates=3)})  # s_A = 11 / 13
    assert blunt > sure


def test_tier_b_rows_enter_only_with_enough_trials_on_enough_dates() -> None:
    found = rows(10, 30, tier="B")
    few = an.fit_class("advisory", found, lambda _d: 0.0, {}, SETTINGS)
    assert not few.tier_b
    assert few.rows == 0
    one_date: dict[an.Tier, an.Trials] = {"B": an.Trials(hits=40, trials=40, dates=1)}
    assert not an.fit_class("advisory", found, lambda _d: 0.0, one_date, SETTINGS).tier_b
    enough: dict[an.Tier, an.Trials] = {"B": an.Trials(hits=40, trials=40, dates=5)}
    taken = an.fit_class("advisory", found, lambda _d: 0.0, enough, SETTINGS)
    assert taken.tier_b
    assert taken.rows == 300
    assert float(taken.level(0.0)) < float(few.level(0.0))


def test_tau_is_chosen_only_from_thirty_market_days() -> None:
    assert an.fit_class("advisory", rows(29, 3), lambda _d: 0.0, SURE, SETTINGS).tau == 1.5
    many = an.fit_class("advisory", rows(30, 3, 1), lambda _d: 0.0, SURE, SETTINGS)
    assert many.tau in SETTINGS.tau_choices


def test_the_fit_is_deterministic_and_fast() -> None:
    # Season scale (spec test 8): every row its own district with its own exposure offset, so
    # each market-day holds many cells, as live advisory days do.
    rng = np.random.default_rng(11)
    found = [
        *season(rng, "advisory", 150, 60),
        *season(rng, "snow_warning", 60, 60),
        *season(rng, "cold", 30, 40),
    ]
    places = {r.district: (None, None) for r in found}
    known = replace(
        EMPTY,
        districts={
            d: (float(rng.uniform(0, 20)), float(rng.uniform(0, 10)), float(rng.uniform(0, 3)))
            for d in places
        },
        f_ref={"advisory": 4.0, "warning": 1.4, "cold": 0.3},
    )
    labels = an.LiveLabels(rows=tuple(found), trials=SURE, days=150, found=True)
    started = time.perf_counter()
    first = an.fit(SETTINGS, known, labels, places)
    took = time.perf_counter() - started
    second = an.fit(SETTINGS, known, labels, places)
    assert json.dumps(first.summary(), sort_keys=True) == json.dumps(
        second.summary(), sort_keys=True
    )
    assert first.fits["advisory"].market_days == 150
    assert took < 10.0


def test_rows_before_the_registered_first_day_do_not_enter() -> None:
    early = [
        an.LiveRow(date(2026, 10, 20), "9900001", "m", "A", "no_school", "advisory"),
    ]
    found = an.fit(SETTINGS, EMPTY, an.LiveLabels(rows=tuple(early), found=True), {})
    assert found.fits["advisory"].rows == 0


KNOWN_PLAN = (
    (("no_school", 2), ("delayed", 1), ("unnamed", 7)),
    (("unnamed", 12),),
    (("no_school", 5), ("unnamed", 3)),
)
"""Three market-days of mixed labels: the known-answer dataset."""


def known_rows() -> list[an.LiveRow]:
    found: list[an.LiveRow] = []
    for j, labels in enumerate(KNOWN_PLAN):
        i = 0
        for label, count in labels:
            for _ in range(count):
                found.append(
                    an.LiveRow(DAY + timedelta(days=j), f"99{j:02d}{i:03d}", f"m{j}", "A",
                               label, "advisory")  # type: ignore[arg-type]
                )  # fmt: skip
                i += 1
    return found


def quadrature_alpha(
    found: list[an.LiveRow], offset: dict[str, float], s: float, q: float
) -> float:
    """The posterior mean of alpha by scipy's adaptive quadrature over e and alpha."""
    from scipy import integrate, special  # type: ignore[import-untyped]  # noqa: PLC0415

    prior, tau = SETTINGS.priors["advisory"], 1.5
    days = [[r for r in found if r.day == DAY + timedelta(days=j)] for j in range(3)]

    def cluster(alpha: float, members: list[an.LiveRow]) -> float:
        def inner(e: float) -> float:
            value = 1.0
            for r in members:
                p = float(special.expit(alpha + offset[r.district] + e))
                value *= (
                    p if r.label == "no_school"
                    else (1 - p) * q if r.label == "delayed"
                    else 1 - s * (p + (1 - p) * q)
                )  # fmt: skip
            return value * float(np.exp(-(e**2) / (2 * tau**2)) / np.sqrt(2 * np.pi * tau**2))

        return float(integrate.quad(inner, -12, 12, limit=200)[0])

    def posterior(alpha: float) -> float:
        density = np.exp(-0.5 * ((alpha - prior.alpha_mean) / prior.alpha_sd) ** 2)
        return float(density * np.prod([cluster(alpha, members) for members in days]))

    mass = integrate.quad(posterior, -8, 4, limit=200)[0]
    return float(integrate.quad(lambda a: a * posterior(a), -8, 4, limit=200)[0] / mass)


@pytest.mark.parametrize(("low", "tolerance"), [(-0.21, 1e-3), (-0.2, 0.0075)])
def test_the_posterior_matches_an_independent_integration(low: float, tolerance: float) -> None:
    # A known answer: offsets +0.3 and ``low``, tier A's list sensitivity from 18 of 20
    # trials; the grid's posterior mean of alpha and its q against scipy's quadrature. -0.21 is
    # 14 grid steps (0.015) exactly, so the grid must agree to 1e-3; -0.2 is counted at the
    # nearest step (-0.195), which moves alpha by at most half a step.
    from scipy import integrate  # noqa: PLC0415

    found = known_rows()
    offset = {r.district: 0.3 if r.district.endswith("1") else low for r in found}
    trials: dict[an.Tier, an.Trials] = {"A": an.Trials(hits=18, trials=20, dates=6)}
    fitted = an.fit_class("advisory", found, offset.__getitem__, trials, SETTINGS)
    s = (9 + 18) / (10 + 20)  # Beta(9, 1) and 18 of 20
    assert fitted.s_a == pytest.approx(s)
    # q: Beta(1.1, 8.9) on the rows not closed, 1 delayed and 22 unnamed, each unnamed row
    # hiding a closing with its chance p at the posterior mean of alpha (R2-S3), its offset
    # counted on the grid's step as the fit counts it
    hidden = [
        float(fitted.level(round(offset[r.district] / 0.015) * 0.015))
        for r in found
        if r.label == "unnamed"
    ]
    assert len(hidden) == 22

    def q_density(x: float, power: float) -> float:
        return float(
            x**power * (1 - x) ** 7.9 * np.prod([1 - s * p - s * (1 - p) * x for p in hidden])
        )

    q_exact = (
        integrate.quad(q_density, 0, 1, args=(2.1,))[0]
        / integrate.quad(q_density, 0, 1, args=(1.1,))[0]
    )
    assert fitted.q == pytest.approx(q_exact, abs=2e-4)
    assert fitted.alpha == pytest.approx(
        quadrature_alpha(found, offset, s, fitted.q), abs=tolerance
    )


BIG_PLAN: tuple[tuple[str, int, float], ...] = (
    ("no_school", 25, 0.0), ("no_school", 15, 0.3), ("delayed", 6, 0.0),
    ("unnamed", 150, 0.0), ("unnamed", 104, 0.3),
)  # fmt: skip
"""One market-day of 300 rows (as a live advisory market can hold), then two small ones."""


def test_a_market_day_of_three_hundred_rows_is_integrated_exactly() -> None:
    # R2-S1: a market-day's likelihood in e is far narrower than tau when it holds hundreds of
    # rows; a fixed 20-point Gauss-Hermite rule on N(0, tau^2) misses it. The fit must match
    # an independent integration: e on a fine even grid per market-day, alpha on a finer one
    # than the fit's (the fixed rule's band was 0.068-0.256 where this is 0.073-0.233).
    from scipy import special  # noqa: PLC0415

    found: list[an.LiveRow] = []
    offset: dict[str, float] = {}
    plan = (BIG_PLAN, (("no_school", 2, 0.0), ("unnamed", 3, 0.0)), (("unnamed", 4, 0.3),))
    for j, cells in enumerate(plan):
        i = 0
        for label, count, moved in cells:
            for _ in range(count):
                district = f"97{j:02d}{i:03d}"
                offset[district] = moved
                found.append(
                    an.LiveRow(DAY + timedelta(days=j), district, f"m{j}", "A", label,  # type: ignore[arg-type]
                               "advisory")
                )  # fmt: skip
                i += 1
    trials: dict[an.Tier, an.Trials] = {"A": an.Trials(hits=18, trials=20, dates=6)}
    fitted = an.fit_class("advisory", found, offset.__getitem__, trials, SETTINGS)
    s, q, tau = fitted.s_a, fitted.q, 1.5
    prior = SETTINGS.priors["advisory"]
    e = np.linspace(-12, 12, 6_001)
    log_normal = -0.5 * (e / tau) ** 2 - np.log(np.sqrt(2 * np.pi) * tau)

    def log_cluster(alpha: float, cells: tuple[tuple[str, int, float], ...]) -> float:
        log = log_normal.copy()
        for label, count, moved in cells:
            p = special.expit(alpha + moved + e)
            log += count * np.log(
                p if label == "no_school"
                else (1 - p) * q if label == "delayed"
                else 1 - s * (p + (1 - p) * q)
            )  # fmt: skip
        top = float(log.max())
        return top + float(np.log(np.trapezoid(np.exp(log - top), e)))

    alpha = np.linspace(fitted.alpha - 2.5, fitted.alpha + 2.5, 1_001)
    log = np.array(
        [
            -0.5 * ((a - prior.alpha_mean) / prior.alpha_sd) ** 2
            + sum(log_cluster(float(a), cells) for cells in plan)
            for a in alpha
        ]
    )
    weight = np.exp(log - log.max())
    weight /= weight.sum()
    cdf = np.cumsum(weight)
    assert fitted.market_days == 3
    assert fitted.alpha == pytest.approx(float(weight @ alpha), abs=1e-3)
    # the 80% band's ends, to within one step of the fit's grid (0.015)
    assert fitted.alpha_band[0] == pytest.approx(alpha[np.searchsorted(cdf, 0.1)], abs=0.016)
    assert fitted.alpha_band[1] == pytest.approx(alpha[np.searchsorted(cdf, 0.9)], abs=0.016)


def simulate(
    truth: float, market_days: int, rng: np.random.Generator
) -> tuple[list[an.LiveRow], dict[str, float], dict[an.Tier, an.Trials]]:
    """Rows drawn from the model itself: tau 1.5, list sensitivity 0.9, delay share 0.1, each
    row its own offset N(0, 0.4); ``truth`` is the reference district's level."""
    tau, s, q = 1.5, 0.9, 0.1
    low, high = -10.0, 6.0
    z, w = np.polynomial.hermite.hermgauss(40)
    for _ in range(80):
        middle = (low + high) / 2
        at = float((an.sigmoid(middle + np.sqrt(2) * tau * z) @ w) / np.sqrt(np.pi))
        low, high = (middle, high) if at < truth else (low, middle)
    alpha = (low + high) / 2
    found: list[an.LiveRow] = []
    offset: dict[str, float] = {}
    for j in range(market_days):
        e = rng.normal(0, tau)
        for i in range(int(rng.integers(3, 30))):
            district = f"9{j:03d}{i:03d}"
            offset[district] = float(rng.normal(0, 0.4))
            p = float(an.sigmoid(np.array(alpha + offset[district] + e)))
            u = rng.random()
            label = "no_school" if u < p else "delayed" if u < p + (1 - p) * q else "unnamed"
            if label != "unnamed" and rng.random() > s:
                label = "unnamed"  # the list missed it
            found.append(
                an.LiveRow(DAY + timedelta(days=j // 2), district, f"m{j}", "A", label,  # type: ignore[arg-type]
                           "advisory")
            )  # fmt: skip
    trials: dict[an.Tier, an.Trials] = {
        "A": an.Trials(hits=int(rng.binomial(200, s)), trials=200, dates=10)
    }
    return found, offset, trials


@pytest.mark.parametrize(
    ("truth", "market_days"), [(0.05, 60), (0.25, 60), (0.10, 150), (0.45, 60)]
)
def test_the_fit_recovers_a_known_level_from_simulated_rows(truth: float, market_days: int) -> None:
    rng = np.random.default_rng(7)
    estimates: list[float] = []
    delays: list[float] = []
    covered = 0
    replicates = 8
    for _ in range(replicates):
        found, offset, trials = simulate(truth, market_days, rng)
        key = "warning" if truth > 0.4 else "advisory"  # (the prior of a level like it)
        fitted = an.fit_class(key, found, offset.__getitem__, trials, SETTINGS)
        estimates.append(float(fitted.level(0.0)))
        delays.append(fitted.q)
        low, high = fitted.band
        covered += low <= truth <= high
    assert abs(float(np.mean(estimates)) - truth) <= 0.02
    assert covered >= replicates // 2  # the 80% band covers it in most replicates
    # R2-S3: q is fitted with p in its likelihood, so it is not low at a warning-like level
    # (fitted as if no unnamed row could hide a closing, it was 0.092 at 0.45)
    assert abs(float(np.mean(delays)) - 0.1) <= 0.005


def test_no_live_region_or_state_deviation_is_fitted() -> None:
    # Addendum B2: the live update is a pure posterior over per-class label counts. The
    # registered live region and state deviations (live_region_sd, live_state_sd, five dates)
    # and the warning split by alert kind are deferred (docs/predict.md): five dates of one
    # state's all-closed rows move every state's level alike.
    closed = [
        an.LiveRow(DAY + timedelta(days=j), f"29{j:02d}{i:03d}", f"m{j}", "A", "no_school",
                   "advisory")
        for j in range(5)
        for i in range(20)
    ]  # fmt: skip
    quiet = [
        an.LiveRow(DAY + timedelta(days=j), f"49{j:02d}{i:03d}", f"u{j}", "A", "unnamed",
                   "advisory")
        for j in range(5)
        for i in range(20)
    ]  # fmt: skip
    labels = an.LiveLabels(rows=tuple(closed + quiet), trials=SURE, days=5, found=True)
    places = {r.district: (None, "ohio_valley" if r.district[:2] == "29" else "southwest")
              for r in closed + quiet}  # fmt: skip
    anchor = an.fit(SETTINGS, EMPTY, labels, places)
    rates = anchor.rates([an.Unit("2900001", None, "ohio_valley"),
                          an.Unit("4900001", None, "southwest")])  # fmt: skip
    assert rates.p[0].tolist() == rates.p[1].tolist()
    standing = world.CONFIG.live_score["standing"]
    assert {"live_region_sd", "live_state_sd", "live_level_min_dates"} <= set(standing)
    assert "split" in world.CONFIG.live_score  # registered, deferred: one warning level in v1
    source = Path(an.__file__).read_text(encoding="utf-8")
    for deferred in ("live_region_sd", "live_state_sd", "live_level_min_dates", "min_live_dates"):
        assert f'"{deferred}"' not in source  # never read from the registered block


def season(rng: np.random.Generator, key: str, market_days: int, per_day: int) -> list[an.LiveRow]:
    """``market_days`` of ``per_day`` rows of a class, each row its own district."""
    return [
        an.LiveRow(DAY + timedelta(days=j // 3), f"{key[:2]}{j:03d}{i:03d}", f"{key}{j}", "A",
                   "no_school" if rng.random() < 0.1 else "unnamed", key)
        for j in range(market_days)
        for i in range(per_day)
    ]  # fmt: skip


# --- a unit's standing ----------------------------------------------------------------------------


def test_a_region_delta_needs_level_support_and_is_half_strength() -> None:
    nation = Tally(495, 667, 22, 117)
    northeast = Tally(168, 302, 5, 117)
    assert an.region_delta(northeast, nation, SETTINGS) == pytest.approx(-0.415, abs=0.002)
    assert an.region_delta(Tally(77, 82, 2, 46), nation, SETTINGS) == 0.0  # two dates
    assert an.region_delta(Tally(129, 132, 5, 110), nation, SETTINGS) == 0.0  # one date holds 83%
    assert an.region_delta(Tally(29, 29, 5, 6), nation, SETTINGS) == 0.0  # 29 days
    strong = an.region_delta(Tally(300, 300, 10, 30), Tally(300, 600, 10, 60), SETTINGS)
    assert strong == pytest.approx(0.5)  # clipped at 1, halved


def test_more_of_the_class_closes_less_on_each_and_county_days_say_nothing() -> None:
    known = Exposure(
        ("2015-16", "2024-25"),
        districts={"0000001": (9.4, 1.4, 0.3), "0000002": (0.0, 1.4, 0.3)},
        counties={"00001": (9.4, 1.4, 0.3)},
        f_ref={"advisory": 4.0, "warning": 1.4, "cold": 0.3},
        nation={},
        regions={},
    )
    found = an.fit(SETTINGS, known, an.NO_LABELS, {})
    many, _many_standing, _ = found.offsets(an.Unit("0000001", None, None))
    few, few_standing, _ = found.offsets(an.Unit("0000002", None, None))
    borrowed, borrowed_standing, days = found.offsets(an.Unit("0000003", "00001", None))
    unknown, unknown_standing, none = found.offsets(an.Unit("0000004", "99999", None))
    assert many[0] == pytest.approx(0.5 * -np.log(9.9 / 4.5))
    assert few[0] == pytest.approx(0.5 * np.log(4.5 / 0.5))
    assert found.offsets(an.Unit("0000001", None, None))[1] == (1, 0, 0)  # more, usual, usual
    assert few_standing[0] == an.STANDINGS.index("fewer")
    assert borrowed == many
    assert borrowed_standing == (0, 0, 0)
    assert days == (9.4, 1.4, 0.3)
    assert unknown == (0.0, 0.0, 0.0)
    assert unknown_standing == (0, 0, 0)
    assert none is None
    rates = found.rates([an.Unit("0000001", None, None), an.Unit("0000002", None, None)])
    assert rates.p[0, 0] < 0.1 < rates.p[1, 0]


def test_the_class_anchor_reads_no_archive_closure_share() -> None:
    source = Path(an.__file__).read_text(encoding="utf-8")
    assert "model.json" not in source
    assert "artifact" not in source
    assert "ModelArtifact" not in source


# --- plausibility --------------------------------------------------------------------------------


RULES = an.Plausibility(
    advisory_mean=1.0, advisory_p99=3.0, advisory_warning_mean=2.0, district_max=6.0, step=0.05
)


def pull(p: np.ndarray, level: np.ndarray, days: np.ndarray, *, national: bool = True) -> an.Pull:
    every = np.ones(p.shape[0], dtype=np.bool_)
    return an.plausibility_pull(p, level, days, every, every & national, RULES)


def test_a_district_over_six_a_winter_is_pulled_toward_its_class_level() -> None:
    level = np.array([0.10, 0.45, 0.10])
    p = np.array([[0.30, 0.60, 0.10], [0.05, 0.30, 0.05]])
    days = np.array([[10.0, 8.0, 0.0], [10.0, 8.0, 0.0]])
    found = pull(p, level, days, national=False)
    assert (found.pulled, found.capped, found.over, found.failing) == (1, 0, 0, ())
    assert float((p[0] * days[0]).sum()) <= 6.0 + 1e-9
    assert p[0, 0] >= 0.10 - 1e-9  # never below its class level
    assert p[1].tolist() == [0.05, 0.30, 0.05]


def test_a_district_its_class_level_cannot_bring_under_six_is_capped_at_six() -> None:
    # Its exposure already puts it under its class levels: pulling it toward them adds
    # closures, so it keeps its own chances and every class's log-odds falls by one shift.
    level = np.array([0.10, 0.45, 0.10])
    own = np.array([0.05, 0.30, 0.05])
    p = own[None, :].copy()
    days = np.array([[40.0, 20.0, 0.0]])
    found = pull(p, level, days, national=False)
    assert (found.capped, found.over) == (1, 0)
    assert float((p[0] * days[0]).sum()) == pytest.approx(6.0, abs=1e-6)
    assert (p[0] < own).all()
    shift = an.logit(own) - an.logit(p[0])
    assert shift == pytest.approx(np.full(3, shift[0]), abs=1e-6)  # one shift for every class


def test_the_national_clauses_pull_the_districts_with_the_most_closures_first() -> None:
    level = np.array([0.10, 0.45, 0.10])
    p = np.tile([0.40, 0.45, 0.10], (100, 1))
    days = np.tile([3.5, 0.0, 0.0], (100, 1))
    days[0, 0] = 5.0
    found = pull(p, level, days)
    advisory, _, _ = an.implied_closures(p, days)
    assert advisory.mean() <= 1.0
    assert p[0, 0] <= p[1:, 0].min()
    assert found.failing == ()
    assert 0 < found.rounds <= 20


def naive_national(
    p: np.ndarray, level: np.ndarray, days: np.ndarray, rules: an.Plausibility
) -> np.ndarray:
    """The registered national rule one district at a time (the slow reference)."""
    base = an.logit(level)
    own = an.logit(p) - base[None, :]
    scale = np.ones(p.shape[0])
    every = np.ones(p.shape[0], dtype=np.bool_)
    for _ in range(round(1 / rules.step)):
        if not an.failing(p, days, every, rules):
            break
        a, b, t = an.implied_closures(p, days)
        for i in np.argsort(-t, kind="stable").tolist():
            if scale[i] <= 0:
                continue
            lower = max(0.0, round(scale[i] - rules.step, 10))
            moved = an.sigmoid(base + lower * own[i])
            each = moved * days[i]
            if not (
                each.sum() < t[i] - 1e-12
                and each[0] <= a[i] + 1e-12
                and each[0] + each[1] <= b[i] + 1e-12
            ):
                continue
            scale[i] = lower
            p[i] = moved
            if not an.failing(p, days, every, rules):
                return p
    return p


def test_the_national_steps_match_the_one_at_a_time_rule() -> None:
    rng = np.random.default_rng(3)
    level = np.array([0.10, 0.45, 0.10])
    days = rng.uniform(0.0, 1.0, (400, 3)) * np.array([4.0, 1.5, 1.0]) + np.array([1, 0, 0])
    p = an.sigmoid(an.logit(level)[None, :] + rng.normal(1.6, 0.5, (400, 3)))
    assert (p * days).sum(axis=1).max() < 6.0  # only the national clauses act
    assert an.failing(p, days, np.ones(400, dtype=np.bool_), RULES)
    slow = naive_national(p.copy(), level, days, RULES)
    found = pull(p, level, days)
    assert found.failing == ()
    assert found.rounds > 1
    assert p == pytest.approx(slow, abs=1e-12)


def lifted(anchor: an.Anchor, **levels: float) -> an.Anchor:
    """The anchor with classes' levels set (as a live update could), by their ``alpha``."""
    fits = dict(anchor.fits)
    for klass, target in levels.items():
        fitted = fits[klass]
        low, high = -10.0, 6.0
        for _ in range(80):
            middle = (low + high) / 2
            low, high = (
                (middle, high) if float(fitted.level(0.0, middle)) < target else (low, middle)
            )
        fits[klass] = replace(fitted, alpha=(low + high) / 2)
    return replace(anchor, fits=fits)


def committed_units() -> tuple[an.Anchor, list[an.Unit]]:
    """The anchor with the committed exposure file, and every district it knows (the real
    shape of the exposure, the high-exposure districts included)."""
    known = exposure.load()
    anchor = an.fit(SETTINGS, known, an.NO_LABELS, {})
    return anchor, [an.Unit(leaid, None, None) for leaid in sorted(known.districts)]


@pytest.mark.parametrize(
    ("advisory", "warning"),
    [(0.12, 0.50), (0.15, 0.60), (0.21, 0.71), (0.15, 0.85), (0.30, 0.45), (0.6, 0.8)],
)
def test_lifted_class_levels_never_serve_an_implausible_district(
    advisory: float, warning: float
) -> None:
    anchor, units = committed_units()
    started = time.perf_counter()
    rates = lifted(anchor, advisory=advisory, warning=warning).rates(units)
    took = time.perf_counter() - started
    found = rates.plausible
    days = np.array([anchor.exposure.districts[u.leaid or ""] for u in units])
    assert np.round(rates.p * 100) == pytest.approx(rates.p * 100, abs=1e-9)  # as published
    advisory_each, both, total = an.implied_closures(rates.p, days)
    assert total.max() <= 6.0 + 1e-9
    assert advisory_each.mean() <= 1.0 + 1e-9
    assert float(np.quantile(advisory_each, 0.99)) <= 3.0 + 1e-9
    assert both.mean() <= 2.0 + 1e-9
    assert found.passes
    assert found.before["district_max"] > 6.0  # the check had work to do
    assert not found.quiet  # ... and says so
    assert found.after["district_max"] <= 6.0
    assert found.pull.rounds <= 20
    assert took < 10.0


def test_a_class_level_the_national_clauses_refuse_is_shrunk_toward_its_prior() -> None:
    anchor, units = committed_units()
    rates = lifted(anchor, advisory=0.518).rates(units)
    found = rates.plausible
    assert found.passes
    assert 0.0 <= found.shrunk["advisory"] < 1.0
    prior = float(anchor.fits["advisory"].level(0.0))
    assert prior <= found.levels["advisory"] < 0.518
    assert "shrunk toward the prior: advisory" in found.line()
    assert found.summary()["shrunk"] == dict(found.shrunk)


def test_with_no_label_the_committed_exposure_needs_no_more_than_the_registered_pull() -> None:
    anchor, units = committed_units()
    found = anchor.rates(units).plausible
    assert found.quiet
    assert found.pull.capped == 0
    assert found.after["district_max"] <= 6.0
    assert found.after["advisory_day"] < found.levels["advisory"]  # S4: day-weighted


def test_a_standing_is_said_only_on_its_side_of_the_level_by_a_point() -> None:
    more, fewer = an.STANDINGS.index("more"), an.STANDINGS.index("fewer")
    claimed = np.array([[more], [more], [fewer], [fewer], [more]], dtype=np.int8)
    p = np.array([[0.07], [0.104], [0.13], [0.06], [0.12]])
    said = an.said_standing(claimed, p, np.array([0.10]))
    assert said[:, 0].tolist() == [more, 0, fewer, 0, 0]


# --- the adapter: with and without L1's record ---------------------------------------------------


def write_day(
    folder: Path, day: date, found: list[dict[str, object]], trials: list[dict[str, object]]
) -> None:
    (folder / "rows").mkdir(parents=True, exist_ok=True)
    (folder / "trials").mkdir(parents=True, exist_ok=True)
    body = {"schema_version": 1, "day": day.isoformat(), "content": "x", "rows": found}
    (folder / "rows" / f"{day.isoformat()}.json").write_text(json.dumps(body))
    (folder / "trials" / f"{day.isoformat()}.jsonl").write_text(
        "".join(json.dumps(t) + "\n" for t in trials)
    )


def row(
    district: str, label: str, tier: str | None, weather: int = 1, lists: int = 0
) -> dict[str, object]:
    return {
        "district": district,
        "weather": weather,
        "after": False,
        "label": label,
        "why": None,
        "tier": tier,
        "market": "Example",
        "sources": [f"list-{k}" for k in range(lists)],
        "slot": None,
        "health": None,
    }


def test_with_no_record_the_labels_are_empty_and_the_level_is_the_prior(tmp_path: Path) -> None:
    found = read_labels(tmp_path / "reads")
    assert found == an.LiveLabels()
    assert not found.found
    anchor = serving_anchor(world.CONFIG, world.model(), folder=tmp_path / "reads")
    assert anchor is not None
    assert float(anchor.fits["advisory"].level(0.0)) == pytest.approx(0.1, abs=0.002)


def test_the_record_gives_its_labeled_read_rows_and_trials(tmp_path: Path) -> None:
    folder = tmp_path / "reads"
    write_day(
        folder,
        DAY,
        [
            row("2900001", "unnamed", "A", lists=2),
            row("2900002", "no_school", "A", weather=5),
            row("2900003", "delayed", "B", weather=3),
            row("2000004", "unknown", "A"),
            row("4900005", "not_read", None),
        ],
        [{"district": "2900002", "source": "s", "tier": "A", "named": True, "weather": 5}],
    )
    (folder / "rows" / "notes.json").write_text("{}")  # not a day: never read
    found = read_labels(folder)
    assert found.found
    assert found.days == 1
    assert [(r.district, r.label, r.tier, r.weather) for r in found.rows] == [
        ("2900001", "unnamed", "A", "advisory"),
        ("2900002", "no_school", "A", "snow_warning"),
        ("2900003", "delayed", "B", "cold"),
    ]
    assert [r.lists for r in found.rows] == [2, 1, 1]  # (no sources named: one list)
    assert found.trials == {"A": an.Trials(hits=1, trials=1, dates=1)}
    anchor = serving_anchor(world.CONFIG, world.model(), folder=folder)
    assert anchor is not None
    assert anchor.fits["advisory"].rows == 1
    assert anchor.fits["advisory"].multi_list == 1  # R2-S4: counted for the lead, not fitted
    assert anchor.summary()["classes"]["advisory"]["multi_list"] == 1  # type: ignore[index]
    assert anchor.fits["warning"].rows == 1
    assert anchor.fits["warning"].closed == 1
    assert anchor.fits["cold"].rows == 0  # tier B, too few trials
    assert float(anchor.fits["advisory"].level(0.0)) < 0.1


def test_a_day_that_does_not_read_is_left_out_and_said(tmp_path: Path) -> None:
    folder = tmp_path / "reads"
    write_day(folder, DAY, [row("2900001", "unnamed", "A")], [])
    (folder / "rows" / "2026-11-04.json").write_text('{"schema_version": 9}')
    said: list[str] = []
    found = read_labels(folder, warn=said.append)
    assert found.days == 1
    assert len(found.rows) == 1
    assert said == ["anchor: the live labels of 2026-11-04: ValueError: left out"]


def test_a_season_sized_record_reads_and_fits_in_time_and_skips_the_days_before_the_fit(
    tmp_path: Path,
) -> None:
    # R3-S4: the record is kept forever; a process reads only the day files the fit can use,
    # skipped by name (an older file here is not even JSON: reading it would be said).
    folder = tmp_path / "reads"
    rng = np.random.default_rng(5)
    for j in range(100):  # a winter of labeled days: 100 days, 60,000 rows
        found = [
            row(f"{j:03d}{i:04d}", "no_school" if rng.random() < 0.1 else "unnamed", "A",
                weather=int(rng.choice([1, 1, 5, 3])), lists=1)
            for i in range(600)
        ]  # fmt: skip
        trials = [{"tier": "A", "named": bool(rng.random() < 0.9)} for _ in range(40)]
        write_day(folder, SETTINGS.fit_from + timedelta(days=j), found, trials)
    for j in range(1, 61):  # earlier winters' days, before the fit's first day
        day = SETTINGS.fit_from - timedelta(days=j)
        (folder / "rows" / f"{day.isoformat()}.json").write_text("not read")
    said: list[str] = []
    started = time.process_time()
    labels = read_labels(folder, since=SETTINGS.fit_from, warn=said.append)
    places = {r.district: (None, None) for r in labels.rows}
    fitted = an.fit(SETTINGS, EMPTY, labels, places)
    took = time.process_time() - started
    assert said == []
    assert labels.days == 100
    assert len(labels.rows) == 60_000
    assert labels.trials["A"].trials == 4_000
    assert fitted.fits["advisory"].rows > 25_000
    assert took < 10.0  # spec test 8's bar, record read included
    everything = read_labels(folder, warn=said.append)  # with no first day: every file
    assert everything.days == 100
    assert len(said) == 60


def test_the_anchor_is_off_with_serve_anchor_off() -> None:
    config = world.CONFIG.model_copy(
        update={"serve": world.CONFIG.serve.model_copy(update={"anchor": False})}
    )
    assert serving_anchor(config, world.model()) is None
    assert world.CONFIG.serve.anchor  # predict.yaml serves the class levels


def test_an_exposure_file_that_does_not_read_leaves_the_class_levels(tmp_path: Path) -> None:
    said: list[str] = []
    anchor = serving_anchor(
        world.CONFIG,
        world.model(),
        folder=tmp_path,
        exposure_path=tmp_path / "missing.json.gz",
        warn=said.append,
    )
    assert anchor is not None
    assert anchor.deltas == {c: {} for c in CLASSES}
    assert said
    assert "exposure" in said[0]


# --- the exposure file ---------------------------------------------------------------------------


def test_the_exposure_file_counts_each_class_a_winter_and_fills_from_the_county() -> None:
    weather = pl.DataFrame(
        {
            "district": ["0000001"] * 4 + ["0000002"] * 2,
            "day": [
                date(2016, 1, 5),
                date(2017, 1, 5),
                date(2014, 1, 5),  # before the first winter
                date(2020, 2, 1),
                date(2016, 12, 1),
                date(2018, 12, 1),
            ],
            "weather": [1, 1, 1, 5, 3, 1],
        },
        schema={"district": pl.String, "day": pl.Date, "weather": pl.Int8},
    )
    districts = pl.DataFrame(
        {
            "district": ["0000001", "0000002", "0000003", "0000004"],
            "state": ["NY", "NY", "NY", "WA"],
            "county": ["36001", "36001", "36001", "53047"],
            "eligible": [3, 2, 0, 1],
        }
    )
    labels = pl.DataFrame(
        {
            "district": ["0000001", "0000002", "0000004", "0000004"],
            "day": [date(2016, 1, 5)] * 2 + [date(2017, 1, 5), date(2017, 1, 6)],
            "outcome": ["no_school", "open", "unknown", "no_school"],
            "weather": [1, 1, 1, 1],
        },
        schema={"district": pl.String, "day": pl.Date, "outcome": pl.String, "weather": pl.Int8},
    )
    body = exposure.build(weather, districts, labels, ["2015-16", "2024-25"])
    assert body["districts"] == {
        "0000001": [2, 1, 0],
        "0000002": [1, 0, 1],
        "0000004": [0, 0, 0],
    }
    assert body["counties"] == {"36001": [2, 0, 0], "53047": [0, 0, 0]}
    assert body["f_ref"] == {"advisory": 0.15, "warning": 0.1, "cold": 0.1}
    nation, regions = body["nation"], body["regions"]
    assert isinstance(nation, dict)
    assert isinstance(regions, dict)
    assert nation["advisory"] == [2, 3, 2, 2]
    assert regions["advisory"] == {"northeast": [1, 2, 1, 2], "northwest": [1, 1, 1, 1]}


def test_the_committed_exposure_file_reads() -> None:
    found = exposure.load()
    assert found.seasons == ("2015-16", "2024-25")
    assert found.f_ref["advisory"] == pytest.approx(4.0)
    assert found.of("5305020", "53047") == ((9.4, 6.9, 0.1), False)
    assert found.of("0602281", "06043")[1]  # no history of its own: its county's
    assert found.nation["advisory"] == Tally(495, 667, 22, 117)
    raw = json.loads(gzip.decompress(exposure.EXPOSURE_PATH.read_bytes()))
    assert set(raw) == {
        "schema_version", "seasons", "classes", "f_ref", "districts", "counties", "nation",
        "regions", "tropical",
    }  # fmt: skip
    # W3-B1: an inland district has had no tropical warning day; Gulf and Atlantic coast ones have
    assert not found.has_tropical("5305020", "53047")  # Methow Valley SD, inland Washington
    assert found.has_tropical("1200390", "12086")  # Miami-Dade, Atlantic coast
    assert found.has_tropical("4823640", "48201")  # Houston ISD, Gulf coast
    assert len(found.tropical) == 2145
    assert found.tropical <= set(found.districts)


def test_the_exposure_file_names_the_districts_and_counties_with_a_tropical_warning_day() -> None:
    weather = pl.DataFrame(
        {
            "district": ["0000001", "0000001", "0000002", "0000003", "0000005"],
            "day": [
                date(2016, 1, 5),
                date(2018, 2, 1),
                date(2017, 9, 10),
                date(2020, 8, 27),
                date(2013, 9, 1),
            ],
            # inland: winter storm and blizzard; coast: tropical; 0000005's only one is too old
            "weather": [5, 7, 2, 2, 2],
        },
        schema={"district": pl.String, "day": pl.Date, "weather": pl.Int8},
    )
    districts = pl.DataFrame(
        {
            "district": ["0000001", "0000002", "0000003", "0000004", "0000005"],
            "state": ["ND", "FL", "LA", "FL", "SC"],
            "county": ["38017", "12086", "22071", "12086", "45019"],
            "eligible": [2, 3, 1, 0, 1],
        }
    )
    labels = pl.DataFrame(
        schema={"district": pl.String, "day": pl.Date, "outcome": pl.String, "weather": pl.Int8}
    )
    body = exposure.build(weather, districts, labels, ["2015-16", "2024-25"])
    assert body["tropical"] == {"districts": ["0000002", "0000003"], "counties": ["12086", "22071"]}
    found = exposure.parse(json.loads(json.dumps(body)))
    assert not found.has_tropical("0000001", "38017")  # inland: winter warnings only
    assert found.has_tropical("0000002", "12086")  # Atlantic coast
    assert found.has_tropical("0000003", "22071")  # Gulf coast
    assert found.has_tropical("0000004", "12086")  # no history of its own: its county's
    assert found.has_tropical(None, "12086")  # a private school: its county's
    assert not found.has_tropical("0000005", "45019")  # before the registered winters
    assert not found.has_tropical(None, None)


# --- serving -----------------------------------------------------------------------------------


def anchored_model() -> tuple[ServeModel, an.Anchor]:
    anchor = an.fit(SETTINGS, EMPTY, an.NO_LABELS, {})
    return build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    ), anchor


def test_predict_learn_compares_models_built_as_the_passes_serve_them() -> None:
    # R2-LEARN: the no-worse decision scores the storm-class cells on the class level that
    # serves them, the same in the committed and the learned model, never the chain's numbers.
    from snowlight.predict.cli import learn_builder  # noqa: PLC0415

    served, anchor = anchored_model()
    build = learn_builder(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor
    )
    committed = build(None)
    assert committed.anchor is anchor
    assert committed.p.tolist() == served.p.tolist()
    advisory = SITUATION_POSITION["advisory"]
    assert committed.classed[advisory]
    off = learn_builder(world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, None)
    assert off(None).anchor is None


def test_every_storm_class_is_served_from_its_class_level_and_none_from_the_chain() -> None:
    plain = build_model(world.directory(), world.model(), world.CONFIG, lambda _x, _y: None)
    built, anchor = anchored_model()
    for k, situation in enumerate(SITUATIONS):
        klass = anchor.class_of(situation.key)
        if klass is None:
            assert built.p[:, k].tolist() == plain.p[:, k].tolist()
            assert not built.classed[k]
            continue
        assert built.classed[k]
        level = round(float(anchor.fits[klass].level(0.0)), 2)
        assert built.p[:, k].tolist() == [level] * len(world.DISTRICTS)
        assert built.effective[k] == k
        assert not built.own[:, k].any()
    assert built.private is not None
    advisory = SITUATION_POSITION["advisory"]
    assert built.private.p[:, advisory].tolist() == [0.1] * len(built.private)
    assert built.private.classed[advisory]


def test_an_advisory_day_says_its_class_base_and_adds_up() -> None:
    built, _anchor = anchored_model()
    days = (date(2026, 11, 3), date(2026, 11, 4))
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    made = forecast_file(built, classes, days, world.utc("2026-11-03T02:00:00"),
                         closed_on=lambda _d: None, last=None)  # fmt: skip
    for entry in made.districts:
        for found in entry.days:
            assert isinstance(found, Forecast)
            assert found.p_no_school == 0.1
            assert found.p_delay == 0.1  # (1 - 0.1) x 0.11, rounded
            assert isinstance(found.why.base, ClassBase)
            assert found.why.base.weather == "advisory"
            assert found.why.base.alert is None
            assert found.why.total() == 10
            assert found.record is None
    assert PredictionsFile.from_json_bytes(made.to_json_bytes()) == made


def test_the_class_base_names_the_days_alert_and_a_private_school_has_no_standing() -> None:
    blizzard = Situation(WeatherClass.BLIZZARD)
    assert class_base(blizzard, 0.30, "more", usual=0.45).alert == "blizzard_warning"
    cold = class_base(Situation(WeatherClass.COLD), 0.14, "fewer", usual=0.10)
    assert (cold.weather, cold.standing, cold.usual) == ("cold", "fewer", 10)
    assert class_base(blizzard, 0.30, "more", "private_schools", 0.45).standing == "usual"
    with pytest.raises(ValueError, match="storm class"):
        class_base(Situation(WeatherClass.NONE), 0.01, "usual")
    with pytest.raises(ValueError, match="by alert or by weather"):
        ClassBase(kind="class", points=10)


def test_a_warning_day_says_its_warnings_are_tropical_only_where_the_place_has_had_one() -> None:
    # W3-B1: a warning-class base names its warnings from the place's own history: storm
    # warnings where it has had a tropical warning day, else winter storm warnings; never
    # tropical for a place that has had none, and never on another class's day.
    usual = (4.0, 1.4, 0.3)
    known = replace(
        EMPTY,
        districts=dict.fromkeys(world.DISTRICTS, usual),
        counties={"29095": usual, "49035": usual},
        f_ref={"advisory": 4.0, "warning": 1.4, "cold": 0.3},
        tropical=frozenset({"2900001"}),
        tropical_counties=frozenset({"29095"}),
    )
    anchor = an.fit(SETTINGS, known, an.NO_LABELS, {})
    built = build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    )
    assert built.tropical.tolist() == [d == "2900001" for d in built.directory.district_ids]
    days = (date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5))
    kinds = (WeatherClass.TROPICAL, WeatherClass.BLIZZARD, WeatherClass.ADVISORY)
    classes = np.tile(np.array([int(k) for k in kinds], dtype=np.int64), (len(world.DISTRICTS), 1))
    assert built.private is not None
    private = np.tile(np.array([int(k) for k in kinds], dtype=np.int64), (len(built.private), 1))
    made = forecast_file(built, classes, days, world.utc("2026-11-03T02:00:00"),
                         closed_on=lambda _d: None, last=None, private_classes=private)  # fmt: skip
    for leaid, entry in zip(built.directory.district_ids, made.districts, strict=True):
        said = []
        for found in entry.days:
            assert isinstance(found, Forecast)
            assert isinstance(found.why.base, ClassBase)
            said.append(found.why.base.tropical)
        assert said == [leaid == "2900001"] * 2 + [False]
    seen: set[tuple[bool, ...]] = set()
    for school in made.schools:
        said = []
        for index in school.days:
            found = made.outlooks[index]
            assert isinstance(found, Forecast)
            assert isinstance(found.why.base, ClassBase)
            said.append(found.why.base.tropical)
        seen.add(tuple(said))
    # the Missouri county had a tropical day (by the test's own list), Utah's had none
    assert seen == {(True, True, False), (False, False, False)}
    raw = made.to_json_bytes()
    assert raw.count(b'"tropical":true') > 0
    assert b'"tropical":false' not in raw  # absent where false: an old reader parses the file
    assert PredictionsFile.from_json_bytes(raw) == made
    blizzard = Situation(WeatherClass.BLIZZARD)
    assert class_base(blizzard, 0.45, "usual", tropical=True).tropical
    assert not class_base(blizzard, 0.45, "usual").tropical
    assert class_base(Situation(WeatherClass.LAKE_SNOW), 0.45, "usual", tropical=True).tropical
    assert not class_base(Situation(WeatherClass.ADVISORY), 0.10, "usual", tropical=True).tropical
    assert not class_base(Situation(WeatherClass.COLD), 0.10, "usual", tropical=True).tropical
    with pytest.raises(ValueError, match="warning-class day"):
        ClassBase(kind="class", points=10, weather="advisory", tropical=True)
    with pytest.raises(ValueError, match="warning-class day"):
        ClassBase(kind="class", points=10, alert="extreme_cold_warning", tropical=True)
    assert ClassBase(kind="class", points=45, weather="tropical", tropical=True).tropical


def test_a_standing_is_said_only_against_the_usual_level_and_on_its_side() -> None:
    advisory = Situation(WeatherClass.ADVISORY)
    said = class_base(advisory, 0.07, "more", usual=0.10)
    assert (said.standing, said.usual) == ("more", 10)
    for p, standing, usual in ((0.10, "more", 0.10), (0.12, "more", 0.10), (0.08, "fewer", 0.10),
                               (0.07, "more", None)):  # fmt: skip
        quiet = class_base(advisory, p, standing, usual=usual)  # type: ignore[arg-type]
        assert (quiet.standing, quiet.usual) == ("usual", None)
    with pytest.raises(ValueError, match="usual level with a standing"):
        ClassBase(kind="class", points=7, weather="advisory", standing="more")
    with pytest.raises(ValueError, match="usual level with a standing"):
        ClassBase(kind="class", points=7, weather="advisory", usual=10)
    with pytest.raises(ValueError, match="on its side"):
        ClassBase(kind="class", points=12, weather="advisory", standing="more", usual=10)


def test_a_chance_from_before_the_class_level_is_no_previous_chance() -> None:
    # Landing day: the last file served the old chain's 93%; the class level is another
    # method's number, not the storm weakening, so it carries no "down from".
    built, _anchor = anchored_model()
    days = (date(2026, 11, 3), date(2026, 11, 4))
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    plain = build_model(world.directory(), world.model(), world.CONFIG, lambda _x, _y: None)
    old = forecast_file(plain, classes, days, world.utc("2026-11-03T01:00:00"),
                        closed_on=lambda _d: None, last=None)  # fmt: skip
    first = forecast_file(built, classes, days, world.utc("2026-11-03T02:00:00"),
                          closed_on=lambda _d: None, last=old)  # fmt: skip
    assert all(
        isinstance(item, Forecast) and item.previous is None
        for entry in first.districts
        for item in entry.days
    )
    lifted_built = build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None,
        anchor=lifted(an.fit(SETTINGS, EMPTY, an.NO_LABELS, {}), advisory=0.2),
    )  # fmt: skip
    later = forecast_file(lifted_built, classes, days, world.utc("2026-11-03T03:00:00"),
                          closed_on=lambda _d: None, last=first)  # fmt: skip
    moved = [item for entry in later.districts for item in entry.days]
    assert all(isinstance(item, Forecast) and item.previous is not None for item in moved)


def chances(found: PredictionsFile) -> list[tuple[float, float | None]]:
    """Every district-day's chance and its previous chance (``None``: none)."""
    return [
        (item.p_no_school, item.previous.p_no_school if item.previous else None)
        for entry in found.districts
        for item in entry.days
        if isinstance(item, Forecast)
    ]


def test_a_method_change_on_a_storm_day_shows_no_previous_chance_either_way() -> None:
    # R2-FLIPBACK: turning serve.anchor back off after it served is the same method change as
    # landing it, the other way: "Up from 7%" next to the chain's 93% would read as the storm
    # worsening.
    built, _anchor = anchored_model()
    plain = build_model(world.directory(), world.model(), world.CONFIG, lambda _x, _y: None)
    days = (date(2026, 11, 3), date(2026, 11, 4))
    storm = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    on = forecast_file(built, storm, days, world.utc("2026-11-03T01:00:00"),
                       closed_on=lambda _d: None, last=None)  # fmt: skip
    off = forecast_file(plain, storm, days, world.utc("2026-11-03T01:30:00"),
                        closed_on=lambda _d: None, last=on)  # fmt: skip
    assert any(round(a * 100) != round(b * 100) for (a, _), (b, _) in
               zip(chances(on), chances(off), strict=True))  # fmt: skip
    assert all(previous is None for _, previous in chances(off))


def test_a_quiet_evening_that_turns_stormy_keeps_its_previous_chance() -> None:
    # W2-S1: a quiet 5 PM chance is an earlier forecast of the same day, not another
    # method's: "Up from 3% at 5 PM" is true and stays when an advisory comes at 9 PM; so does
    # "Down from" when the storm passes and the day is quiet again.
    built, _anchor = anchored_model()
    days = (date(2026, 11, 3), date(2026, 11, 4))
    quiet = np.full((len(world.DISTRICTS), 2), int(WeatherClass.NONE), dtype=np.int64)
    storm = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    five = forecast_file(built, quiet, days, world.utc("2026-11-02T23:00:00"),
                         closed_on=lambda _d: None, last=None)  # fmt: skip
    nine = forecast_file(built, storm, days, world.utc("2026-11-03T03:00:00"),
                         closed_on=lambda _d: None, last=five)  # fmt: skip
    after = forecast_file(built, quiet, days, world.utc("2026-11-03T04:00:00"),
                          closed_on=lambda _d: None, last=nine)  # fmt: skip
    for last, now in ((five, nine), (nine, after)):
        pairs = list(zip(chances(last), chances(now), strict=True))
        moved = [(was, previous) for (was, _), (shown, previous) in pairs
                 if round(was * 100) != round(shown * 100)]  # fmt: skip
        assert moved
        assert all(previous == was for was, previous in moved)


# --- the edges -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ([], "not a read day"),
        ({"schema_version": 1, "day": "2026-11-04", "rows": []}, "names day"),
        ({"schema_version": 1, "day": "2026-11-03"}, "no rows"),
        ({"schema_version": 1, "day": "2026-11-03", "rows": [1]}, "not an object"),
        (
            {"schema_version": 1, "day": "2026-11-03", "rows": [{"label": "unnamed", "tier": "A"}]},
            "no district",
        ),
    ],
)
def test_a_read_day_that_is_not_one_is_refused(body: object, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        anchor_labels._rows(DAY, body)


def test_a_trial_line_that_does_not_read_leaves_its_day_out(tmp_path: Path) -> None:
    folder = tmp_path / "reads"
    write_day(folder, DAY, [row("2900001", "unnamed", "A")], [{"tier": "C", "named": True}])
    (folder / "trials" / f"{DAY.isoformat()}.jsonl").write_text('\n{"tier": "C"}\n')
    said: list[str] = []
    assert read_labels(folder, warn=said.append).rows == ()
    assert said == [f"anchor: the live labels of {DAY}: ValueError: left out"]


def test_the_log_line_and_the_private_report(tmp_path: Path) -> None:
    found = an.fit(SETTINGS, EMPTY, an.NO_LABELS, {})
    line = anchor_labels.anchor_line(found)
    assert line.startswith("anchor: advisory 0.100 (0.043-0.206) q 0.110 rows 0 on 0 dates;")
    assert line.endswith("; no read record")
    path = tmp_path / "anchor.json"
    anchor_labels.write_report(found, path)
    report = json.loads(path.read_text())
    assert report["classes"]["advisory"]["level"] == 0.1
    assert report["labels"] == {"found": False, "days": 0, "rows": 0, "through": None}
    assert report["classes"]["advisory"]["predictive"] == pytest.approx(0.1146, abs=0.0005)
    assert "plausibility" not in report
    built, anchor = anchored_model()
    assert built.plausible is not None
    anchor_labels.write_report(anchor, path, plausible=built.plausible)
    assert json.loads(path.read_text())["plausibility"]["passes"] is True


def test_the_settings_refuse_what_is_not_registered() -> None:
    score = world.CONFIG.live_score

    def config_with(block: str, key: str, value: object):  # type: ignore[no-untyped-def]
        changed = {**score, block: {**score[block], key: value}}
        return world.CONFIG.model_copy(update={"live_score": changed})

    with pytest.raises(ValueError, match="not a number"):
        an.AnchorSettings.of(config_with("prior", "tau", True))
    with pytest.raises(ValueError, match="not a pair"):
        an.AnchorSettings.of(config_with("prior", "delay_beta", [1.1]))
    with pytest.raises(ValueError, match="not a mapping"):
        an.AnchorSettings.of(config_with("prior", "advisory", 0.1))
    with pytest.raises(ValueError, match="are lists"):
        an.AnchorSettings.of(config_with("prior", "tau_choices", 1.5))
    with pytest.raises(ValueError, match="prior_weight"):
        an.AnchorSettings.of(config_with("live_update", "prior_weight", "capture_k"))


def test_an_exposure_file_of_another_kind_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "exposure.json.gz"
    path.write_bytes(gzip.compress(b'{"schema_version": 2}'))
    with pytest.raises(ValueError, match="schema 1"):
        exposure.load(path)
    body = json.loads(gzip.decompress(exposure.EXPOSURE_PATH.read_bytes()))
    for change, why in (
        ({"classes": ["advisory"]}, "classes"),
        ({"districts": {"0000001": [1, 2]}}, "numbers"),
        ({"nation": {"advisory": [1, 2]}}, "tally"),
        ({"tropical": {"districts": []}}, "tropical"),
    ):
        exposure.write({**body, **change}, path)
        with pytest.raises(ValueError, match=why):
            exposure.load(path)
    exposure.write({k: v for k, v in body.items() if k != "tropical"}, path)
    with pytest.raises(KeyError, match="tropical"):
        exposure.load(path)  # a file with no list of them would name no coast's storms
    with pytest.raises(ValueError, match="first and a last"):
        exposure.season_years(["2015-16"])
    with pytest.raises(ValueError, match="before the first"):
        exposure.season_years(["2020-21", "2015-16"])
    assert exposure.season_of(date(2025, 8, 20)) == 2025
    assert exposure.season_of(date(2026, 2, 1)) == 2025


def test_the_exposure_command_writes_the_same_bytes_twice(tmp_path: Path) -> None:
    from snowlight.predict import anchor_cli  # noqa: PLC0415

    work = tmp_path / "work"
    work.mkdir()
    pl.DataFrame(
        {"district": ["0000001"], "day": [date(2016, 1, 5)], "weather": [1]},
        schema={"district": pl.String, "day": pl.Date, "weather": pl.Int8},
    ).write_parquet(work / "weather.parquet")
    pl.DataFrame(
        {"district": ["0000001"], "state": ["NY"], "county": ["36001"], "eligible": [1]}
    ).write_parquet(work / "districts.parquet")
    pl.DataFrame(
        {"district": ["0000001"], "day": [date(2016, 1, 5)], "outcome": ["open"], "weather": [1]},
        schema={"district": pl.String, "day": pl.Date, "outcome": pl.String, "weather": pl.Int8},
    ).write_parquet(work / "labels.parquet")
    out = tmp_path / "exposure.json.gz"
    args = argparse.Namespace(config=CONFIG_PATH, work=work, out=out)
    assert anchor_cli.run_exposure(args) == 0
    first = out.read_bytes()
    assert anchor_cli.run_exposure(args) == 0
    assert out.read_bytes() == first
    assert exposure.load(out).districts == {"0000001": (0.1, 0.0, 0.0)}
    assert (
        anchor_cli.run_exposure(argparse.Namespace(config=CONFIG_PATH, work=tmp_path, out=out)) == 1
    )


def test_the_exposure_command_refuses_a_file_whose_priors_fail_the_plausibility_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # R3-S3: thirty advisory days every winter in every district puts the priors' advisory mean
    # at three closures a winter, over the national clause, and nothing can pull a district
    # whose own level is its class level: the file is never written, so no pass can serve it.
    from snowlight.predict import anchor_cli  # noqa: PLC0415

    work = tmp_path / "work"
    work.mkdir()
    days = [date(2015 + y, 12, 1) + timedelta(days=i) for y in range(10) for i in range(30)]
    pl.DataFrame(
        {"district": ["0000001"] * len(days), "day": days, "weather": [1] * len(days)},
        schema={"district": pl.String, "day": pl.Date, "weather": pl.Int8},
    ).write_parquet(work / "weather.parquet")
    pl.DataFrame(
        {"district": ["0000001"], "state": ["NY"], "county": ["36001"], "eligible": [1]}
    ).write_parquet(work / "districts.parquet")
    pl.DataFrame(
        {"district": ["0000001"], "day": [date(2016, 1, 5)], "outcome": ["open"], "weather": [1]},
        schema={"district": pl.String, "day": pl.Date, "outcome": pl.String, "weather": pl.Int8},
    ).write_parquet(work / "labels.parquet")
    out = tmp_path / "exposure.json.gz"
    assert anchor_cli.run_exposure(argparse.Namespace(config=CONFIG_PATH, work=work, out=out)) == 1
    assert not out.exists()
    assert "the priors fail the plausibility check" in capsys.readouterr().err


def test_the_committed_exposure_file_passes_the_plausibility_check_at_the_priors() -> None:
    from snowlight.predict.anchor_cli import prior_plausible  # noqa: PLC0415

    known = exposure.load()
    districts = pl.DataFrame(
        {"district": sorted(known.districts), "county": None, "state": None},
        schema={"district": pl.String, "county": pl.String, "state": pl.String},
    )
    found = prior_plausible(SETTINGS, known, districts)
    assert found.passes
    assert found.quiet  # nothing beyond the registered pull


def test_the_exposure_command_is_registered_and_reads_the_registered_winters(
    tmp_path: Path,
) -> None:
    from snowlight.predict import anchor_cli, cli  # noqa: PLC0415

    parser = argparse.ArgumentParser()
    cli.register(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["predict", "exposure", "--work", str(tmp_path)])
    assert args.handler is anchor_cli.run_exposure
    assert args.out == exposure.EXPOSURE_PATH
    score = world.CONFIG.live_score
    changed = {**score, "standing": {**score["standing"], "seasons": "2015-16"}}
    config = world.CONFIG.model_copy(update={"live_score": changed})
    path = tmp_path / "predict.yaml"
    path.write_text(json.dumps(config.model_dump(mode="json")))
    bad = argparse.Namespace(config=path, work=tmp_path, out=tmp_path / "x.json.gz")
    assert anchor_cli.run_exposure(bad) == 1


def lifted_world(heavy: int) -> tuple[ServeModel, tuple[float, float, float]]:
    """The test world's model with ``heavy`` districts shaped as the committed file's most
    exposed ones (the rest light), served with a live record that lifts the warning level."""
    known = exposure.load()
    shape = (12.0, 17.3, 0.0)
    shaped = replace(
        known,
        districts={
            **known.districts,
            **{d: shape if i < heavy else (0.5, 0.5, 0.0) for i, d in enumerate(world.DISTRICTS)},
        },
    )
    closed = [
        an.LiveRow(DAY + timedelta(days=j), f"98{j:02d}{i:03d}", f"m{j}", "A",
                   "no_school" if i < 15 else "unnamed", "snow_warning")
        for j in range(20)
        for i in range(20)
    ]  # fmt: skip
    labels = an.LiveLabels(rows=tuple(closed), trials=SURE, days=20, found=True)
    anchor = an.fit(SETTINGS, shaped, labels, {})
    assert float(anchor.fits["warning"].level(0.0)) > 0.6  # the live record lifts warning
    built = build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    )
    return built, shape


def test_a_lifted_level_on_the_serve_path_serves_no_implausible_district_and_says_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from snowlight.predict.cli import said_plausible  # noqa: PLC0415

    built, shape = lifted_world(1)
    found = built.plausible
    assert found is not None
    assert found.passes
    assert found.pull.capped == 1
    served = np.stack(
        [built.p[:, SITUATION_POSITION[k]] for k in ("advisory", "snow_warning", "cold")],
        axis=1,
    )
    # the capped district is held to six as published, within a hundredth of its days
    assert 6.0 - 0.01 * sum(shape) <= float((served[0] * np.array(shape)).sum()) <= 6.0 + 1e-9
    assert found.after["district_max"] <= 6.0
    warning = SITUATION_POSITION["snow_warning"]
    assert built.usual[warning] == pytest.approx(found.levels["warning"])
    assert built.p_rate[0, warning] < built.usual[warning]
    said_plausible(built, report=None)
    out, err = capsys.readouterr()
    assert out.startswith("predict: anchor plausibility: ")
    assert "pulled 0, capped 1, shrunk 0" in out
    assert "anchor plausibility" in err  # a warning, never silent


def most_exposed(count: int) -> list[tuple[float, float, float]]:
    """The committed exposure file's ``count`` units with the most storm-class days."""
    known = exposure.load()
    return sorted(known.districts.values(), key=lambda f: -(f[0] + f[1] + f[2]))[:count]


@pytest.mark.parametrize(("advisory", "warning"), [(0.21, 0.71), (0.15, 0.85), (0.25, 0.75)])
def test_raised_levels_publish_no_district_over_six_on_the_serve_path(
    advisory: float, warning: float
) -> None:
    # R2-B1: G6 holds on the chances as published (rounded to the hundredth, floored), not
    # only on the raw ones: rounding a capped district's chances up would serve it above six.
    known = exposure.load()
    light = (0.5, 0.5, 0.0)
    shapes = {d: most_exposed(1)[0] if i == 0 else light for i, d in enumerate(world.DISTRICTS)}
    shaped = replace(known, districts={**known.districts, **shapes})
    anchor = lifted(an.fit(SETTINGS, shaped, an.NO_LABELS, {}), advisory=advisory,
                    warning=warning)  # fmt: skip
    built = build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    )
    found = built.plausible
    assert found is not None
    assert found.passes
    assert not found.shrunk
    assert found.before["district_max"] > 6.0  # the check had work to do
    days = np.array([shapes[d] for d in built.directory.district_ids])
    for advisory_key, warning_key in (("advisory", "snow_warning"), ("advisory_after", "ice")):
        served = np.stack(
            [built.p[:, SITUATION_POSITION[k]] for k in (advisory_key, warning_key, "cold")],
            axis=1,
        )
        assert np.round(served * 100) == pytest.approx(served * 100, abs=1e-9)  # as published
        total = (served * days).sum(axis=1)
        assert total.max() <= 6.0 + 1e-9
        assert found.after["district_max"] == pytest.approx(total.max(), abs=1e-4)
    assert built.p_rate[:, SITUATION_POSITION["advisory"]] == pytest.approx(
        built.p[:, SITUATION_POSITION["advisory"]], abs=1e-12
    )  # publishing keeps what the check held


def test_a_district_rounding_would_put_over_six_takes_the_hundredth_under_instead() -> None:
    raw = np.array([[0.0752, 0.4451, 0.0], [0.0751, 0.20, 0.0]])
    days = np.array([[20.0, 9.9, 0.0], [20.0, 10.0, 0.0]])
    assert (raw[0] * days[0]).sum() <= 6.0  # raw: 5.91; rounded: 1.6 + 4.455 = 6.055
    every = np.ones(2, dtype=np.bool_)
    found = an.settle(raw, days, every, 6.0, an.PUBLISHED)
    # warning's rounding raised it most (cold's floor is no shift of its days): it goes down
    assert found[0].tolist() == [0.08, 0.44, 0.01]
    assert (found[0] * days[0]).sum() <= 6.0
    assert found[1].tolist() == [0.08, 0.20, 0.01]  # under six as rounded: kept
    assert an.settle(raw, days, every, 6.0, None).tolist() == raw.tolist()


def test_a_national_clause_even_the_priors_fail_is_said_as_a_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from snowlight.predict.cli import said_plausible  # noqa: PLC0415

    built, _shape = lifted_world(len(world.DISTRICTS))
    found = built.plausible
    assert found is not None
    assert not found.passes
    assert found.pull.over == 0  # every district still held to six
    assert found.shrunk == {"advisory": 0.0, "warning": 0.0}
    said_plausible(built, report=None)
    _out, err = capsys.readouterr()
    assert "FAILS advisory_warning_mean" in err
    assert ", shrunk 2; shrunk toward the prior: advisory to 0.00" in err


def test_only_the_advisory_class_takes_an_archive_region_delta() -> None:
    known = exposure.load()
    anchor = an.fit(SETTINGS, known, an.NO_LABELS, {})
    assert anchor.deltas["advisory"] == {"northeast": pytest.approx(-0.415, abs=0.01)}
    assert anchor.deltas["warning"] == {}
    assert anchor.deltas["cold"] == {}
    ohio = known.regions["warning"]["ohio_valley"]
    assert an.region_delta(ohio, known.nation["warning"], SETTINGS) > 0  # supported, not used
