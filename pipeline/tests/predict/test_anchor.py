"""The class anchor (advisory-sane L3): priors, the live update, standing, plausibility, serving.

Every row, market and count here is made up for the tests (synthetic labels in the record's
format); none comes from a real list or a real storm.
"""

import argparse
import gzip
import hashlib
import itertools
import json
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

# threadpoolctl comes with scikit-learn, which the pipeline depends on.
from threadpoolctl import (  # type: ignore[import-untyped, unused-ignore]
    threadpool_info,
    threadpool_limits,
)

from predict import world
from snowlight.predict import anchor as an
from snowlight.predict import anchor_labels, exposure, live_read
from snowlight.predict.anchor_labels import read_labels, serving_anchor
from snowlight.predict.config import CONFIG_PATH, LearnSettings, PredictConfig
from snowlight.predict.exposure import CLASSES, Exposure, Tally
from snowlight.predict.serve import SITUATION_POSITION, ServeModel, build_model, forecast_file
from snowlight.predict.situations import SITUATIONS, Situation, WeatherClass
from snowlight.predict.why import class_base
from snowlight.schemas.predictions import ClassBase, Forecast, PredictionsFile, PreviousChance
from snowlight.schemas.stats import ReadAuditDay

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


def test_the_adapter_reads_the_record_l1_writes_with_its_own_models(tmp_path: Path) -> None:
    # SYNTHETIC: a day written by L1's own write_day, ReadDay, ReadRow and Trial (the landed
    # record format), read through the one adapter in L1's own folder.
    assert anchor_labels.READS_DIR == live_read.READS_DIR
    folder = tmp_path / "reads"

    def read(
        district: str,
        label: str,
        tier: live_read.Tier | None,
        weather: int = 1,
        sources: tuple[str, ...] = ("s",),
    ) -> live_read.ReadRow:
        return live_read.ReadRow(
            district=district, weather=weather, after=False, label=live_read.Label(label),
            why=None, tier=tier, market=None, sources=sources, slot="11:00", health=None,
        )  # fmt: skip

    live_read.write_day(
        folder,
        live_read.ReadDay(
            schema_version=1,
            day=DAY,
            content="synthetic",
            rows=(
                read("2900001", "unnamed", live_read.Tier.A, sources=("s", "t")),
                read("2900002", "no_school", live_read.Tier.A, weather=5),
                read("2900003", "delayed", live_read.Tier.B, weather=3),
                read("2000004", "unknown", live_read.Tier.A),
                read("4900005", "not_read", None, sources=()),
            ),
            no_school=("2900002",),
            audit=ReadAuditDay(day=DAY, held=False, classes=()),
        ),
        [
            live_read.Trial(
                district="2900002", source="s", tier=live_read.Tier.A, named=True, weather=5
            ),
            live_read.Trial(
                district="2900002", source="t", tier=live_read.Tier.A, named=False, weather=5
            ),
        ],
    )
    said: list[str] = []
    found = read_labels(folder, warn=said.append)
    assert said == []
    assert found.found
    assert found.days == 1
    assert [(r.district, r.label, r.tier, r.weather, r.lists) for r in found.rows] == [
        ("2900001", "unnamed", "A", "advisory", 2),
        ("2900002", "no_school", "A", "snow_warning", 1),
        ("2900003", "delayed", "B", "cold", 1),
    ]
    assert found.trials == {"A": an.Trials(hits=1, trials=2, dates=1)}
    anchor = serving_anchor(world.CONFIG, world.model(), folder=folder)
    assert anchor is not None
    assert anchor.fits["advisory"].rows == 1
    assert anchor.fits["warning"].closed == 1


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
    # predict-next ONE-STORM (decision 7): the level itself moved (a refit), with no change in
    # the weather: no previous chance on the first file after the level moved.
    moved = [item for entry in later.districts for item in entry.days]
    assert all(isinstance(item, Forecast) and item.previous is None for item in moved)
    assert chances(later) != chances(first)
    # A third file at the same level with the class changed shows one: the weather changed.
    warned = np.full((len(world.DISTRICTS), 2), int(WeatherClass.SNOW_WARNING), dtype=np.int64)
    third = forecast_file(lifted_built, warned, days, world.utc("2026-11-03T04:00:00"),
                          closed_on=lambda _d: None, last=later)  # fmt: skip
    pairs = list(zip(chances(later), chances(third), strict=True))
    assert all(previous == was for (was, _), (_shown, previous) in pairs)


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


# --- the morning a level moves (predict-next ONE-STORM, decision 7) -----------------------------

TWO_DAYS = (date(2026, 11, 3), date(2026, 11, 4))


def model_at(**levels: float) -> ServeModel:
    """The test world's serving model with classes' levels set, as a refit could set them."""
    anchor = lifted(an.fit(SETTINGS, EMPTY, an.NO_LABELS, {}), **levels)
    return build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    )


def file_at(
    model: ServeModel,
    weather: WeatherClass | np.ndarray,
    at: str,
    last: PredictionsFile | None,
    *,
    schools: bool = False,
) -> PredictionsFile:
    """One pass's file: every district (and, with ``schools``, every private school) in
    ``weather`` on both days."""
    classes = (
        weather
        if isinstance(weather, np.ndarray)
        else np.full((len(world.DISTRICTS), 2), int(weather), dtype=np.int64)
    )
    private = None
    if schools:
        assert model.private is not None
        private = np.full((len(model.private), 2), int(classes[0, 0]), dtype=np.int64)
    return forecast_file(
        model, classes, TWO_DAYS, world.utc(at), closed_on=lambda _d: None, last=last,
        private_classes=private,
    )  # fmt: skip


def carrying(found: PredictionsFile, p: float, at: str) -> PredictionsFile:
    """``found`` with every district-day carrying a previous chance of ``p`` made at ``at``."""
    previous = PreviousChance(p_no_school=p, at=world.utc(at))
    return found.model_copy(
        update={
            "districts": tuple(
                entry.model_copy(
                    update={
                        "days": tuple(
                            item.model_copy(update={"previous": previous})
                            if isinstance(item, Forecast)
                            else item
                            for item in entry.days
                        )
                    }
                )
                for entry in found.districts
            )
        }
    )


def test_a_refit_that_moves_no_level_keeps_the_previous_chance() -> None:
    # (guard) A process start that refits to the same levels changes nothing: "Up from 3% at
    # 5 PM" is carried, and a change of the class is still said.
    five = file_at(model_at(), WeatherClass.NONE, "2026-11-02T23:00:00", None)
    nine = file_at(model_at(), WeatherClass.ADVISORY, "2026-11-03T03:00:00", five)
    up = [previous for _, previous in chances(nine)]
    assert any(previous is not None for previous in up)
    ten = file_at(model_at(), WeatherClass.ADVISORY, "2026-11-03T04:00:00", nine)
    assert chances(ten) == chances(nine)
    warned = file_at(model_at(), WeatherClass.SNOW_WARNING, "2026-11-03T05:00:00", ten)
    pairs = list(zip(chances(ten), chances(warned), strict=True))
    assert all(previous == was for (was, _), (_shown, previous) in pairs)


def test_a_take_back_shows_no_down_from() -> None:
    # A level that fell (a take-back, a refit) shows no "Down from": the weather did not ease.
    high = file_at(model_at(advisory=0.2), WeatherClass.ADVISORY, "2026-11-03T01:00:00", None)
    low = file_at(model_at(), WeatherClass.ADVISORY, "2026-11-03T02:00:00", high)
    assert {p for p, _ in chances(high)} == {0.2}
    assert {p for p, _ in chances(low)} == {0.1}
    assert all(previous is None for _, previous in chances(low))
    # A warning day at 45% that carried "Up from 44% at 3 AM": kept while the chance stays
    # above it, dropped where the level took the chance to it or across it ("Down from 44%"
    # would read as the storm easing).
    at45 = file_at(model_at(), WeatherClass.SNOW_WARNING, "2026-11-03T08:00:00", None)
    assert {p for p, _ in chances(at45)} == {0.45}
    carried = carrying(at45, 0.44, "2026-11-03T07:00:00")
    for level, kept in ((0.47, 0.44), (0.38, None), (0.44, None), (0.45, 0.44)):
        now = file_at(
            model_at(warning=level), WeatherClass.SNOW_WARNING, "2026-11-03T09:00:00", carried
        )
        assert set(chances(now)) == {(level, kept)}, level
    # ... and one carried from above ("Down from 52%") the other way round.
    carried = carrying(at45, 0.52, "2026-11-03T07:00:00")
    for level, kept in ((0.47, 0.52), (0.52, None), (0.60, None)):
        now = file_at(
            model_at(warning=level), WeatherClass.SNOW_WARNING, "2026-11-03T09:00:00", carried
        )
        assert set(chances(now)) == {(level, kept)}, level
    # The next file compares as before: a change in the weather after the refit is said.
    moved = file_at(model_at(warning=0.38), WeatherClass.SNOW_WARNING, "2026-11-03T09:00:00",
                    carried)  # fmt: skip
    eased = file_at(model_at(warning=0.38), WeatherClass.ADVISORY, "2026-11-03T10:00:00", moved)
    assert set(chances(eased)) == {(0.1, 0.38)}


def test_a_day_with_forecast_lines_makes_no_new_previous_chance_when_its_level_moved() -> None:
    from predict.test_forecast_adjust import NATION, adjusting_model, forecast  # noqa: PLC0415
    from snowlight.predict.forecast_values import Forecasts  # noqa: PLC0415

    built, anchor = adjusting_model(NATION)
    refit = build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None,
        anchor=lifted(anchor, advisory=0.2),
    )  # fmt: skip
    days = (date(2026, 1, 14), date(2026, 1, 15))
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    later = world.utc("2026-01-14T03:07:00")  # after the day's class snapshot
    read = frozenset({(1, days[0])})

    def made(
        model: ServeModel, at: datetime, inches: float, last: PredictionsFile | None
    ) -> Forecast:
        file = forecast_file(
            model, classes, days, at, closed_on=lambda _d: None, last=last,
            forecasts=Forecasts({days[0]: {1: forecast(inches)}}), adjust=True, read_last=read,
        )  # fmt: skip
        made_files.append(file)
        found = file.districts[1].days[0]
        assert isinstance(found, Forecast)
        return found

    made_files: list[PredictionsFile] = []
    on = made(built, later, 6.0, None)
    assert on.why.reasons  # the forecast's lines, on a class base
    first = made_files[-1]
    # (guard) Two reads at the same level: a real change in the forecast, said.
    more = made(built, later + timedelta(hours=1), 9.0, first)
    assert more.previous is not None
    assert more.previous.p_no_school == on.p_no_school
    # The same two reads with the level moved between them: no new previous chance.
    moved = made(refit, later + timedelta(hours=1), 9.0, first)
    assert moved.why.reasons
    assert isinstance(moved.why.base, ClassBase)
    assert (moved.why.base.points, moved.p_no_school > on.p_no_school) == (20, True)
    assert moved.previous is None
    # From the next file on previous chances are back.
    after = made(refit, later + timedelta(hours=2), 6.0, made_files[-1])
    assert after.previous is not None
    assert after.previous.p_no_school == moved.p_no_school


def test_an_earlier_line_is_carried_across_the_morning_a_level_moves() -> None:
    # "Up from 3% at 5 PM", made when the alert came, is true of the weather: it is on the
    # first file after a refit and on the next.
    five = file_at(model_at(), WeatherClass.NONE, "2026-11-02T23:00:00", None)
    nine = file_at(model_at(), WeatherClass.ADVISORY, "2026-11-03T03:00:00", five)
    came = [previous for _, previous in chances(nine)]
    assert any(previous is not None and previous < 0.1 for previous in came)
    refit = file_at(model_at(advisory=0.2), WeatherClass.ADVISORY, "2026-11-03T09:00:00", nine)
    assert [shown for shown, _ in chances(refit)] == [0.2] * len(came)
    assert [previous for _, previous in chances(refit)] == came
    again = file_at(model_at(advisory=0.2), WeatherClass.ADVISORY, "2026-11-03T10:00:00", refit)
    assert chances(again) == chances(refit)
    # It is dropped where the chance now shown equals it or has crossed it.
    ten = file_at(model_at(), WeatherClass.ADVISORY, "2026-11-03T04:00:00", None)
    carried = carrying(ten, 0.03, "2026-11-02T23:00:00")
    for level, kept in ((0.2, 0.03), (0.04, 0.03), (0.03, None), (0.02, None)):
        now = file_at(model_at(advisory=level), WeatherClass.ADVISORY, "2026-11-03T09:00:00",
                      carried)  # fmt: skip
        assert set(chances(now)) == {(level, kept)}, level


def test_a_district_whose_class_changed_keeps_its_previous_chance_though_a_level_moved() -> None:
    # (guard) The advisory level moved, and one district's alert became a warning: its change
    # is a change in the weather, said as before.
    first = file_at(model_at(), WeatherClass.ADVISORY, "2026-11-03T01:00:00", None)
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    classes[0, :] = int(WeatherClass.SNOW_WARNING)
    later = file_at(model_at(advisory=0.2), classes, "2026-11-03T02:00:00", first)
    for entry in later.districts:
        for item in entry.days:
            assert isinstance(item, Forecast)
            if entry.district == 0:
                assert (item.p_no_school, item.previous is not None) == (0.45, True)
                assert item.previous is not None
                assert item.previous.p_no_school == 0.1
            else:
                assert (item.p_no_school, item.previous) == (0.2, None)


def test_private_schools_use_the_districts_moved_classes() -> None:
    def schools(found: PredictionsFile) -> list[tuple[float, float | None]]:
        return [
            (item.p_no_school, item.previous.p_no_school if item.previous else None)
            for entry in found.schools
            for item in found.outlook_of(entry)
            if isinstance(item, Forecast)
        ]

    first = file_at(model_at(), WeatherClass.ADVISORY, "2026-11-03T01:00:00", None, schools=True)
    assert schools(first)
    moved = file_at(model_at(advisory=0.2), WeatherClass.ADVISORY, "2026-11-03T02:00:00", first,
                    schools=True)  # fmt: skip
    assert [shown for shown, _ in schools(moved)] != [shown for shown, _ in schools(first)]
    assert all(previous is None for _, previous in schools(moved))
    # (guard) at the same level a change of the class is said for a school too
    warned = file_at(model_at(), WeatherClass.SNOW_WARNING, "2026-11-03T02:00:00", first,
                     schools=True)  # fmt: skip
    pairs = list(zip(schools(first), schools(warned), strict=True))
    assert all(previous == was for (was, _), (_shown, previous) in pairs)


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
        an.LiveRow(DAY + timedelta(days=7 * j), f"98{j:02d}{i:03d}", f"m{j}", "A",
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


# --- the ramp, the storm and the cap (predict-next ONE-STORM) ------------------------------------
#
# Every storm below is made up. These tests carry their own rule (RAMPED or AS_BUILT), so none
# reads the committed ``live_update.ramp``: one assert in test_retention.py pins that value.

RAMPED = replace(SETTINGS, ramp="capped_storms")
AS_BUILT = replace(SETTINGS, ramp="off")
MONDAY = date(2026, 11, 30)
WEATHER_OF = {"advisory": "advisory", "warning": "snow_warning", "cold": "cold"}
WEATHER_CODE = {"advisory": 1, "warning": 5, "cold": 3}
NO_TRIALS: dict[an.Tier, an.Trials] = {}
LEVEL_BOUND = {"advisory": 6.0, "warning": 9.0, "cold": 6.0}
"""The most a first storm may move a class's reference level, in points."""
DELAY_BOUND = 5.0
"""The most it may move the chance of a delay at the reference district, in points."""
SERVED = (
    "alpha", "alpha_band", "q", "tau", "s_a", "s_b", "tier_b", "rows", "closed", "delayed",
    "unnamed", "market_days", "dates", "k_eff", "predictive", "multi_list",
)  # fmt: skip


def market_day(  # noqa: PLR0913, PLR0917 - one made-up market-day's class, day and labels
    key: str,
    day: date,
    market: str,
    count: int,
    closed: int = 0,
    delayed: int = 0,
    *,
    offset: float = 0.0,
    tier: an.Tier = "A",
) -> list[an.LiveRow]:
    """``count`` made-up rows of one market on one day, ``closed`` of them closed and
    ``delayed`` delayed, each at ``offset`` (the district id carries it: :func:`offset_in`)."""
    labels: tuple[an.LabelKind, ...] = ("no_school", "delayed", "unnamed")
    return [
        an.LiveRow(
            day,
            f"{offset}|{day.toordinal()}|{market}|{i}",
            market,
            tier,
            labels[0 if i < closed else 1 if i < closed + delayed else 2],
            WEATHER_OF[key],
        )
        for i in range(count)
    ]


def offset_in(district: str) -> float:
    return float(district.split("|", 1)[0])


def storm(  # noqa: PLR0913, PLR0917 - one made-up storm's class, mornings and labels
    key: str,
    start: int,
    markets: int,
    count: int,
    closed: int = 0,
    delayed: int = 0,
    *,
    mornings: int = 1,
    offset: float = 0.0,
    tier: an.Tier = "A",
) -> list[an.LiveRow]:
    """``mornings`` mornings in a row from ``start`` days after a Monday, each of ``markets``
    markets of ``count`` rows (``closed`` closed and ``delayed`` delayed in each)."""
    return [
        made
        for d in range(mornings)
        for m in range(markets)
        for made in market_day(
            key, MONDAY + timedelta(days=start + d), f"M{m:03d}", count, closed, delayed,
            offset=offset, tier=tier,
        )
    ]  # fmt: skip


def ramp_fit(
    key: str,
    found: list[an.LiveRow],
    trials: dict[an.Tier, an.Trials] = SURE,
    settings: an.AnchorSettings = RAMPED,
) -> an.ClassFit:
    return an.ramped(key, found, offset_in, trials, settings)


def built_fit(
    key: str, found: list[an.LiveRow], trials: dict[an.Tier, an.Trials] = SURE
) -> an.ClassFit:
    return an.fit_class(key, found, offset_in, trials, SETTINGS)


def points(fitted: an.ClassFit) -> float:
    """The reference district's level, in points."""
    return 100 * float(fitted.level(0.0))


def delay_points(fitted: an.ClassFit) -> float:
    """The chance of a delay at the reference district, in points."""
    return 100 * (1 - float(fitted.level(0.0))) * fitted.q


def served(fitted: an.ClassFit) -> tuple[object, ...]:
    return tuple(getattr(fitted, name) for name in SERVED)


def ramp_of(fitted: an.ClassFit) -> an.Ramp:
    assert fitted.ramp is not None
    return fitted.ramp


def weekdays_on(day: date, count: int) -> date:
    """The weekday ``count`` weekdays after ``day``."""
    while count:
        day += timedelta(days=1)
        count -= day.weekday() < 5
    return day


@contextmanager
def quiet() -> Iterator[None]:
    """Run the work inside with no trace function and on one BLAS thread; restore both after.

    Under the coverage tracer the fit's own Python loops run several times slower (the storms
    of a record some 30 times), and BLAS's worker threads spin through process time while
    they wait. So a timing read under either is not the fit's cost, and a sweep of hundreds
    of fits costs every CI worker several times its own work. The timed blocks and the
    sweeps below run in here; the lines they run are covered by the single fits around them.
    """
    tracer = sys.gettrace()
    sys.settrace(None)
    try:
        with threadpool_limits(limits=1):
            yield
    finally:
        sys.settrace(tracer)


@pytest.fixture
def sweep() -> Iterator[None]:
    """A sweep of hundreds of made-up fits, run :func:`quiet`."""
    with quiet():
        yield


def blas_threads() -> list[int]:
    return [pool["num_threads"] for pool in threadpool_info() if pool["user_api"] == "blas"]


def test_quiet_work_runs_untraced_on_one_blas_thread_and_restores_both() -> None:
    def tracer(*_args: object) -> None:
        return None

    np.ones((2, 2)) @ np.ones((2, 2))  # BLAS is loaded
    threads = blas_threads()
    assert threads
    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        with quiet():
            assert sys.gettrace() is None
            assert set(blas_threads()) == {1}
        assert sys.gettrace() is tracer
        assert blas_threads() == threads
        with pytest.raises(ZeroDivisionError), quiet():
            1 / 0  # noqa: B018 - the error is the test
        assert sys.gettrace() is tracer
        assert blas_threads() == threads
    finally:
        sys.settrace(previous)


def test_with_no_class_row_the_ramped_fit_is_the_fit_as_built_bit_for_bit(tmp_path: Path) -> None:
    # (guard) Landing day: with no used row every served number is the same float as before.
    early = SETTINGS.fit_from - timedelta(days=3)
    chain = [
        an.LiveRow(DAY, f"29{i:05d}", "m", "A", "no_school" if i < 9 else "unnamed", "none")
        for i in range(40)
    ]
    before = [replace(made, day=early) for made in storm("warning", 0, 3, 40, 40)]
    unused = storm("cold", 0, 2, 30, 30, tier="B")  # tier B with too few trials: not used
    for labels in (
        an.NO_LABELS,
        an.LiveLabels(rows=(*chain, *before, *unused), trials={}, days=3, found=True),
    ):
        ramped = an.fit(RAMPED, EMPTY, labels, {})
        off = an.fit(AS_BUILT, EMPTY, labels, {})
        for key in CLASSES:
            start = an.fit_class(key, [], lambda _d: 0.0, labels.trials, SETTINGS)
            assert served(ramped.fits[key]) == served(start) == served(off.fits[key])
            ramp = ramp_of(ramped.fits[key])
            assert (ramp.w, ramp.bound, ramp.rows) == (0.0, "none", 0)
            assert off.fits[key].ramp is None
    path = tmp_path / "a.json"
    anchor_labels.write_report(an.fit(RAMPED, EMPTY, an.NO_LABELS, {}), path)
    assert json.loads(path.read_text())["classes"]["warning"]["level"] == 0.4498


def test_one_lone_closed_row_barely_moves_a_level() -> None:
    for key, most, as_built in (("advisory", 0.1, 4.0), ("warning", 0.2, 8.6), ("cold", 0.1, 5.7)):
        found = storm(key, 0, 1, 1, 1)
        base = points(ramp_fit(key, []))
        assert 0 < points(ramp_fit(key, found)) - base < most
        assert points(built_fit(key, found)) - base == pytest.approx(as_built, abs=0.1)


GRID_SIZES = ((1, 1), (100, 1), (100, 4), (1000, 4), (30, 100))
"""Rows a market and markets a morning."""
GRID_PINS = {
    "advisory": (2.58, -1.13, 2.66),
    "warning": (6.62, -6.59, 3.47),
    "cold": (4.46, -1.82, 4.29),
}
"""The design's largest rise and fall of the level and rise of the delay chance over the grid."""


def grid_storm(  # noqa: PLR0913, PLR0917 - one made-up first storm of the grid
    key: str,
    count: int,
    markets: int,
    mornings: int,
    closed: float,
    delayed: float,
    offsets: tuple[float, ...],
) -> list[an.LiveRow]:
    """A first storm: each market's rows split evenly over ``offsets``, the share ``closed``
    of each part closed and the share ``delayed`` of its open rows delayed."""
    found: list[an.LiveRow] = []
    for d in range(mornings):
        for m in range(markets):
            for i, offset in enumerate(offsets):
                part = count // len(offsets) + (1 if i < count % len(offsets) else 0)
                shut = round(part * closed)
                found += market_day(
                    key, MONDAY + timedelta(days=d), f"M{m:03d}", part, shut,
                    round((part - shut) * delayed), offset=offset,
                )  # fmt: skip
    return found


@pytest.mark.usefixtures("sweep")
@pytest.mark.parametrize("key", CLASSES)
def test_the_first_storm_whatever_it_holds_stays_inside_the_bound(key: str) -> None:
    start = ramp_fit(key, [])
    base, base_delay = points(start), delay_points(start)
    up = down = late = 0.0
    every = ((0.0,), (-1.5,), (1.5,), (-1.5, 1.5))
    for trials, offsets in ((SURE, every), (NO_TRIALS, every[:1])):
        for (count, markets), mornings, closed, delayed, offset in itertools.product(
            GRID_SIZES, (1, 3), (1.0, 0.0, 0.5), (0.0, 1.0), offsets
        ):
            found = grid_storm(key, count, markets, mornings, closed, delayed, offset)
            fitted = ramp_fit(key, found, trials)
            moved = points(fitted) - base
            delay = delay_points(fitted) - base_delay
            assert abs(moved) <= LEVEL_BOUND[key], (count, markets, mornings, closed, delayed)
            assert abs(delay) <= DELAY_BOUND, (count, markets, mornings, closed, delayed)
            assert ramp_of(fitted).storm_count == 1
            up, down, late = max(up, moved), min(down, moved), max(late, delay)
    # so that a change which doubled a move cannot pass: the grid's largest moves are the
    # design's
    assert (up, down, late) == pytest.approx(GRID_PINS[key], abs=0.3)


def test_the_worst_first_storms_of_the_wide_grid_move_a_level_as_designed() -> None:
    def moved(key: str, found: list[an.LiveRow], trials: dict[an.Tier, an.Trials]) -> float:
        return points(ramp_fit(key, found, trials)) - points(ramp_fit(key, [], trials))

    lone = {key: storm(key, 0, 100, 1, 1, offset=-3.0) for key in ("advisory", "cold")}
    assert moved("advisory", lone["advisory"], SURE) == pytest.approx(3.79, abs=0.1)
    assert moved("cold", lone["cold"], SURE) == pytest.approx(5.62, abs=0.1)
    closed = storm("warning", 0, 2, 1000, 1000, offset=-3.0)
    assert moved("warning", closed, NO_TRIALS) == pytest.approx(7.30, abs=0.1)
    late = storm("warning", 0, 4, 1000, 0, 1000, mornings=5, offset=2.0)
    assert moved("warning", late, SURE) == pytest.approx(-6.95, abs=0.1)


def test_mornings_of_one_storm_are_one_storm() -> None:
    def count(*days: date, gap: int = 1) -> int:
        return len(set(an.storms_of(days, gap).values()))

    monday, friday, thursday = MONDAY, MONDAY + timedelta(days=4), MONDAY + timedelta(days=3)
    assert count(monday, monday + timedelta(days=1), monday + timedelta(days=2)) == 1
    assert count(monday, monday + timedelta(days=2)) == 1  # a morning lost between
    assert count(friday, friday + timedelta(days=3)) == 1  # Friday and Monday
    assert count(friday, friday + timedelta(days=4)) == 1  # Friday and Tuesday
    assert count(thursday, thursday + timedelta(days=4)) == 1  # Thursday and the next Monday
    assert count(monday, thursday) == 2
    assert count(thursday, thursday + timedelta(days=5)) == 2
    # Thanksgiving Thursday and Friday between: two storms
    assert count(date(2026, 11, 25), date(2026, 11, 30)) == 2
    assert count(monday, monday + timedelta(days=2), gap=0) == 2
    assert an.storms_of([thursday, monday, thursday], 1) == {monday: monday, thursday: thursday}
    # However many mornings it lasts, one storm serves the same level.
    for closed, level in ((100, 0.493), (0, 0.410)):
        levels = [
            float(ramp_fit("warning", storm("warning", 0, 3, 100, closed, mornings=n)).level(0.0))
            for n in (1, 2, 3, 5)
        ]
        assert levels[0] == pytest.approx(level, abs=5e-4)
        assert levels[1:] == pytest.approx(levels[:1] * 3, abs=1e-9)
    # A first morning with none closed and a second with all closed is still one storm.
    for key in CLASSES:
        mixed = [*storm(key, 0, 3, 100, 0), *storm(key, 1, 3, 100, 100)]
        fitted = ramp_fit(key, mixed)
        assert ramp_of(fitted).storm_count == 1
        assert abs(points(fitted) - points(ramp_fit(key, []))) <= LEVEL_BOUND[key]


@pytest.mark.usefixtures("sweep")
@pytest.mark.parametrize("key", CLASSES)
def test_seeded_first_storms_of_one_to_five_mornings_stay_inside_the_bound(key: str) -> None:
    rng = np.random.default_rng(20261110 + CLASSES.index(key))
    start = ramp_fit(key, [], NO_TRIALS)
    for trial in range(200):
        found: list[an.LiveRow] = []
        markets = int(rng.integers(1, 5))
        for d in range(int(rng.integers(1, 6))):
            for m in range(markets):
                count = int(rng.choice([1, 5, 30, 100, 300]))
                shut = int(rng.binomial(count, float(rng.choice([0.0, 0.1, 0.5, 0.9, 1.0]))))
                late = int(rng.binomial(count - shut, float(rng.choice([0.0, 0.5, 1.0]))))
                found += market_day(
                    key, MONDAY + timedelta(days=d), f"M{m}", count, shut, late,
                    offset=float(rng.choice([-1.5, 0.0, 1.5])),
                )  # fmt: skip
        fitted = ramp_fit(key, found, SURE if trial % 2 else NO_TRIALS)
        assert ramp_of(fitted).storm_count == 1
        assert abs(points(fitted) - points(start)) <= LEVEL_BOUND[key]
        assert abs(delay_points(fitted) - delay_points(start)) <= DELAY_BOUND


def drawn_date(
    rng: np.random.Generator, key: str, day: date, sizes: Sequence[int]
) -> list[an.LiveRow]:
    """One made-up date: 1 to 4 markets, each of a size drawn from ``sizes``, labels mixed."""
    found: list[an.LiveRow] = []
    for m in range(int(rng.integers(1, 5))):
        count = int(rng.choice(sizes))
        shut = int(rng.binomial(count, float(rng.choice([0.0, 0.1, 0.5, 1.0]))))
        late = int(rng.binomial(count - shut, float(rng.choice([0.0, 0.3, 1.0]))))
        found += market_day(key, day, f"M{m}", count, shut, late)
    return found


@pytest.mark.usefixtures("sweep")
@pytest.mark.parametrize("key", CLASSES)
def test_the_newest_date_never_lowers_the_ramp_weight(key: str) -> None:
    # Every row tier A: tier B is held fixed here (what it does is pinned in
    # test_what_can_lower_the_ramp_weight).
    rng = np.random.default_rng(20261111 + CLASSES.index(key))
    a0 = ramp_fit(key, []).alpha
    cap, full = RAMPED.date_cap[key], RAMPED.ramps[key]
    for _ in range(500):
        day = MONDAY
        found: list[an.LiveRow] = []
        before: an.Storms | None = None
        weight = 0.0
        for _ in range(int(rng.integers(1, 13))):
            day = weekdays_on(day, int(rng.choice([1, 1, 2, 3, 5, 9])))  # in a row, or apart
            found += drawn_date(rng, key, day, (1, 2, 5, 30, 100, 300))
            table = an.storm_table(key, found, RAMPED, a0)
            now, _bound = an.ramp_weight(len(found), table, full)
            assert now >= weight
            joined = table.of[day]
            for name, was in (before.information if before is not None else {}).items():
                assert before is not None
                # no storm's information after the cap fell...
                assert table.weight[name] * table.information[name] >= (
                    before.weight[name] * was - 1e-12
                )
                if name != joined:  # ...and no storm the date did not join lost weight
                    assert table.weight[name] >= before.weight[name] - 1e-12
                    assert table.delay_weight[name] >= before.delay_weight[name] - 1e-12
            for sizes, weights, start in (
                (table.information, table.weight, table.start),
                (table.open_rows, table.delay_weight, table.delay_start),
            ):  # no storm is over the cap after tempering, in either cap
                whole = start + sum(weights[name] * size for name, size in sizes.items())
                assert all(
                    weights[name] * size <= cap * whole + 1e-9 for name, size in sizes.items()
                )
                assert all(0 < value <= 1 for value in weights.values())
            before, weight = table, now


@pytest.mark.parametrize("key", CLASSES)
def test_tau_once_free_stays_free_while_dates_are_added(key: str) -> None:
    rng = np.random.default_rng(20261112 + CLASSES.index(key))
    a0 = ramp_fit(key, []).alpha
    found = [made for j in range(10) for made in storm(key, 7 * j, 3, 100, 20, 10)]
    table = an.storm_table(key, found, RAMPED, a0)
    assert len({made.market_day for made in found}) == 30
    assert an.ramp_weight(len(found), table, RAMPED.ramps[key]) == (1.0, "full")
    day = MONDAY + timedelta(days=70)
    for _ in range(20):
        day = weekdays_on(day, int(rng.choice([1, 2, 4, 8])))
        found += drawn_date(rng, key, day, (1, 5, 100, 1000))
        table = an.storm_table(key, found, RAMPED, a0)
        assert an.ramp_weight(len(found), table, RAMPED.ramps[key]) == (1.0, "full")
    fitted = ramp_fit(key, found)
    assert ramp_of(fitted).bound == "full"
    assert fitted.tau in SETTINGS.tau_choices


def test_what_can_lower_the_ramp_weight() -> None:
    def weight(found: list[an.LiveRow], settings: an.AnchorSettings = RAMPED) -> float:
        return ramp_of(ramp_fit("warning", found, settings=settings)).w

    first, second = storm("warning", 0, 3, 100, 100), storm("warning", 7, 3, 100, 100)
    assert weight([*first, *second]) == pytest.approx(0.250)
    assert weight(first) == pytest.approx(0.125)  # a take-back of a whole storm
    # A morning added between two storms joins them: Monday and Thursday, then Tuesday.
    thursday = storm("warning", 3, 3, 100, 100)
    assert weight([*first, *thursday]) == pytest.approx(0.250)
    assert weight([*first, *storm("warning", 1, 3, 100, 100), *thursday]) == pytest.approx(0.125)
    # One middle morning of three taken back leaves one storm (two with no gap allowed).
    ends = [*first, *storm("warning", 2, 3, 100, 100)]
    assert weight(ends) == pytest.approx(0.125)
    assert weight(ends, replace(RAMPED, storm_gap=0)) == pytest.approx(0.250)


def test_tier_b_leaving_on_the_newest_date_lowers_the_ramp_weight() -> None:
    # Three warning storms a week apart, the first tier A and two tier B, with tier B in.
    found = [
        *storm("warning", 0, 3, 100, 50),
        *storm("warning", 7, 3, 100, 50, tier="B"),
        *storm("warning", 14, 3, 100, 50, tier="B"),
    ]
    held: dict[an.Tier, an.Trials] = {"B": an.Trials(hits=15, trials=20, dates=5)}
    fitted = ramp_fit("warning", found, held)
    ramp = ramp_of(fitted)
    assert (fitted.tier_b, fitted.rows, ramp.bound) == (True, 900, "storms")
    assert ramp.w == pytest.approx(0.375, abs=1e-3)
    assert ramp.storms == pytest.approx(3.0)
    # A fourth date whose tier B trials are misses takes tier B out: every tier B row leaves.
    found += storm("warning", 21, 1, 100, 50)
    gone: dict[an.Tier, an.Trials] = {"B": an.Trials(hits=15, trials=23, dates=6)}
    fitted = ramp_fit("warning", found, gone)
    ramp = ramp_of(fitted)
    assert (fitted.tier_b, fitted.rows, ramp.bound) == (False, 400, "storms")
    assert ramp.w == pytest.approx(0.247, abs=1e-3)
    assert ramp.storms == pytest.approx(1.97, abs=5e-3)
    assert "w 0.247 by storms 1.97 of 8" in anchor_labels._ramp_said("warning", ramp)


def test_two_days_taken_back_from_the_middle_split_a_storm() -> None:
    for closed, whole, split in ((100, 0.493, 0.619), (0, 0.410, 0.271)):
        found = storm("warning", 0, 3, 100, closed, mornings=4)  # Monday to Thursday
        fitted = ramp_fit("warning", found)
        assert ramp_of(fitted).w == pytest.approx(0.125)
        assert float(fitted.level(0.0)) == pytest.approx(whole, abs=1e-3)
        kept = [made for made in found if made.day in {MONDAY, MONDAY + timedelta(days=3)}]
        fitted = ramp_fit("warning", kept)
        assert ramp_of(fitted).storm_count == 2
        assert ramp_of(fitted).w == pytest.approx(0.250)
        assert float(fitted.level(0.0)) == pytest.approx(split, abs=1e-3)


def test_the_ramp_weight_is_the_smallest_of_rows_storms_and_market_days() -> None:
    for mornings in (1, 3):
        ramp = ramp_of(ramp_fit("advisory", storm("advisory", 0, 3, 100, 10, mornings=mornings)))
        assert (ramp.w, ramp.bound, ramp.storms) == (0.125, "storms", 1.0)
    ramp = ramp_of(ramp_fit("advisory", storm("advisory", 0, 1, 100, 10)))
    assert ramp.bound == "market_days"
    assert ramp.w == pytest.approx(0.0626, abs=1e-4)
    assert ramp.market_days == pytest.approx(0.939, abs=1e-3)
    ramp = ramp_of(ramp_fit("warning", storm("warning", 0, 1, 1, 1)))
    assert (ramp.w, ramp.bound) == (0.01, "rows")
    # A full ramp serves the fit as built itself: no arithmetic, no weight under 1.
    eight = [made for j in range(8) for made in storm("advisory", 7 * j, 3, 100, 12, 10)]
    fitted = ramp_fit("advisory", eight)
    ramp = ramp_of(fitted)
    assert (ramp.w, ramp.bound, ramp.tempered) == (1.0, "full", ())
    assert served(fitted) == served(built_fit("advisory", eight))
    assert ramp.built == ramp.raw
    # Part of the way: the three formulas, from the no-row fit toward the tempered posterior.
    found = storm("advisory", 0, 3, 100, 60, 20)
    fitted, start = ramp_fit("advisory", found), ramp_fit("advisory", [])
    ramp = ramp_of(fitted)
    table = an.storm_table("advisory", found, RAMPED, start.alpha)
    raw = an.fit_class(
        "advisory", found, offset_in, SURE, SETTINGS, weights=table.by_day(table.weight),
        delay_weights=table.by_day(table.delay_weight), tau_free=False,
    )  # fmt: skip
    assert ramp.w == 0.125
    assert fitted.alpha == pytest.approx(start.alpha + 0.125 * (raw.alpha - start.alpha), abs=1e-12)
    assert fitted.q == pytest.approx(start.q + 0.125 * (raw.q - start.q), abs=1e-12)
    for end in (0, 1):
        assert fitted.alpha_band[end] == pytest.approx(
            start.alpha_band[end] + 0.125 * (raw.alpha_band[end] - start.alpha_band[end]),
            abs=1e-12,
        )
    assert (fitted.tau, fitted.rows, fitted.closed, fitted.delayed) == (1.5, 300, 180, 60)
    assert (ramp.raw.alpha, ramp.raw.q, fitted.predictive) == (raw.alpha, raw.q, raw.predictive)


def test_a_storm_over_its_share_is_tempered_to_the_cap_and_no_other() -> None:
    a0 = ramp_fit("advisory", []).alpha

    def shares(found: list[an.LiveRow]) -> tuple[an.Storms, list[float], list[float]]:
        table = an.storm_table("advisory", found, RAMPED, a0)
        names = sorted(table.information)
        after = [table.weight[name] * table.information[name] for name in names]
        whole = table.start + sum(after)
        return table, [table.weight[name] for name in names], [part / whole for part in after]

    small = [*storm("advisory", 7, 1, 100), *storm("advisory", 14, 1, 100)]
    _table, weights, after = shares([*storm("advisory", 0, 3, 100), *small])
    assert weights == pytest.approx([0.5907, 1.0, 1.0], abs=1e-4)
    assert after == pytest.approx([0.2500, 0.1411, 0.1411], abs=1e-4)
    _table, weights, after = shares(storm("advisory", 0, 3, 100))
    assert weights == pytest.approx([0.3685], abs=1e-4)
    assert after == pytest.approx([0.25])
    table, weights, after = shares([*storm("advisory", 0, 3, 100, mornings=2), *small])
    assert table.information[MONDAY] == pytest.approx(5.6338, abs=1e-4)
    known = table.start + sum(table.information.values())
    assert table.information[MONDAY] / known == pytest.approx(0.5302, abs=1e-4)
    assert weights == pytest.approx([0.2954, 1.0, 1.0], abs=1e-4)
    assert after == pytest.approx([0.2500, 0.1411, 0.1411], abs=1e-4)
    # the weights are found from the row counts alone: no label moves them
    assert an.storm_weights({MONDAY: 0.0}, 3.0, 0.25) == {MONDAY: 1.0}
    assert an.storm_weights({}, 3.0, 0.25) == {}


def test_lone_row_storms_do_not_buy_a_full_ramp_for_one_big_storm() -> None:
    for key, most, step in (("warning", 0.5, 10.0), ("cold", 0.35, 7.0)):
        lone = [made for j in range(7) for made in storm(key, 7 * j, 1, 1)]
        before = ramp_fit(key, lone)
        after = ramp_fit(key, [*lone, *storm(key, 49, 3, 100, 100)])
        assert ramp_of(before).w < ramp_of(after).w < most
        assert 0 < points(after) - points(before) < step
        assert ramp_of(after).w == pytest.approx({"warning": 0.369, "cold": 0.242}[key], abs=2e-3)


def test_the_delay_share_is_held_to_its_own_cap() -> None:
    for key, open_rows, was, now in (
        ("advisory", 3.3333, 9.9, 12.5),
        ("cold", 6.6667, 9.9, 14.0),
        ("warning", 6.6667, 6.0, 9.1),
    ):
        found = storm(key, 0, 3, 100, 0, 100)
        start, fitted = ramp_fit(key, []), ramp_fit(key, found)
        table = an.storm_table(key, found, RAMPED, start.alpha)
        assert table.delay_weight[MONDAY] * table.open_rows[MONDAY] == pytest.approx(
            open_rows, abs=1e-4
        )
        assert delay_points(start) == pytest.approx(was, abs=0.1)
        assert delay_points(fitted) == pytest.approx(now, abs=0.1)
        quiet = ramp_fit(key, storm(key, 0, 3, 100, 0, 0))
        assert abs(delay_points(quiet) - delay_points(start)) < 0.5
        eight = [made for j in range(8) for made in storm(key, 7 * j, 3, 100, 20, 10)]
        assert ramp_fit(key, eight).q == built_fit(key, eight).q


def test_tau_stays_registered_until_the_ramp_is_full() -> None:
    # 40 market-days on one date would free tau as built; one storm does not.
    found = storm("advisory", 0, 40, 30, 3)
    fitted = ramp_fit("advisory", found)
    assert built_fit("advisory", found).tau != SETTINGS.tau
    assert (fitted.tau, ramp_of(fitted).w) == (SETTINGS.tau, 0.125)
    assert abs(points(fitted) - points(ramp_fit("advisory", []))) <= LEVEL_BOUND["advisory"]
    # At a full ramp it is chosen as built.
    ten = [made for j in range(10) for made in storm("advisory", 7 * j, 3, 30, 3)]
    fitted, built = ramp_fit("advisory", ten), built_fit("advisory", ten)
    assert (ramp_of(fitted).w, fitted.market_days) == (1.0, 30)
    assert built.tau != SETTINGS.tau
    assert served(fitted) == served(built)


def test_the_ramp_off_serves_the_fit_as_built() -> None:
    found = [*storm("warning", 0, 3, 100, 100), *storm("advisory", 0, 2, 50, 5, 5)]
    labels = an.LiveLabels(rows=tuple(found), trials=SURE, days=1, found=True)
    off = an.fit(AS_BUILT, EMPTY, labels, {})
    on = an.fit(RAMPED, EMPTY, labels, {})
    for key in CLASSES:
        mine = [made for made in found if made.weather == WEATHER_OF[key]]
        built = an.fit_class(key, mine, lambda _d: 0.0, SURE, SETTINGS)
        assert off.fits[key].ramp is None
        assert served(off.fits[key]) == served(built)
    assert float(off.fits["warning"].level(0.0)) == pytest.approx(0.906, abs=1e-3)
    assert float(on.fits["warning"].level(0.0)) == pytest.approx(0.493, abs=1e-3)
    assert off.summary()["ramp"] == "off"
    assert off.summary()["classes"]["warning"]["ramp"] is None  # type: ignore[index]


def ramp_config(**changed: object) -> PredictConfig:
    """The test world's config with ``live_score.live_update`` keys set (``None``: removed)."""
    score = world.CONFIG.live_score
    update = {**score["live_update"], **changed}
    update = {key: value for key, value in update.items() if value is not None}
    return world.CONFIG.model_copy(update={"live_score": {**score, "live_update": update}})


def test_the_settings_refuse_a_ramp_that_is_not_registered() -> None:
    def refused(why: str, **changed: object) -> None:
        with pytest.raises(ValueError, match=why):
            an.AnchorSettings.of(ramp_config(**changed))

    assert an.AnchorSettings.of(ramp_config(ramp="off")).ramp == "off"
    assert an.AnchorSettings.of(ramp_config(ramp="capped_storms")).ramp == "capped_storms"
    refused("live_score live_update ramp is missing", ramp=None)
    refused(r"ramp is a bare YAML word \(read as False\): write the value in quotes", ramp=False)
    refused(r"ramp is a bare YAML word \(read as True\): write the value in quotes", ramp=True)
    refused('ramp is not "capped_storms" or "off": \'capped\'', ramp="capped")
    refused('ramp is not "capped_storms" or "off": 1', ramp=1)
    refused("live_score live_update ramp_warning is missing", ramp_warning=None)
    refused("live_score live_update ramp_cold is missing", ramp_cold=8)
    refused(
        "ramp_advisory has a key that is not rows, storms or market_days: dates",
        ramp_advisory={"rows": 300, "storms": 8, "dates": 8},
    )
    refused("ramp_cold has no rows or no storms", ramp_cold={"rows": 100})
    refused("ramp_cold has no rows or no storms", ramp_cold={"storms": 8})
    refused("ramp_warning storms is under 1: 0", ramp_warning={"rows": 100, "storms": 0})
    refused("ramp_warning rows is under 1: 0.5", ramp_warning={"rows": 0.5, "storms": 8})
    for gap in (6, -1, 1.5, True, None):
        refused("ramp_storm_gap is not a whole number from 0 to 5", ramp_storm_gap=gap)
    score = world.CONFIG.live_score
    for share in (0, 1, 1.5):
        supply = {**score["supply"], "cold": {"rows": 100, "max_date_share": share}}
        config = world.CONFIG.model_copy(update={"live_score": {**score, "supply": supply}})
        with pytest.raises(ValueError, match="supply cold max_date_share is not between 0 and 1"):
            an.AnchorSettings.of(config)
    settings = an.AnchorSettings.of(ramp_config(ramp_storm_gap=0))
    assert (settings.storm_gap, settings.date_cap) == (
        0,
        {"advisory": 0.25, "warning": 0.40, "cold": 0.40},
    )
    assert settings.ramps == {
        "advisory": an.RampFull(300.0, 8.0, 15.0),
        "warning": an.RampFull(100.0, 8.0),
        "cold": an.RampFull(100.0, 8.0),
    }


def test_a_bare_off_is_refused_with_the_way_to_write_it() -> None:
    # Through the YAML text: the committed file with the value of its ramp line replaced by
    # the bare word, whatever it was. YAML reads a bare off as false, and the config loads.
    text = CONFIG_PATH.read_text(encoding="utf-8")
    line = next(found for found in text.splitlines() if found.startswith("    ramp: "))

    def with_value(value: str) -> PredictConfig:
        body = yaml.safe_load(text.replace(line, f"    ramp: {value}"))
        return PredictConfig.model_validate(body)

    for word in ("off", "no", "on"):
        config = with_value(word)
        assert isinstance(config.live_score["live_update"]["ramp"], bool)
        with pytest.raises(ValueError, match="in quotes"):
            an.AnchorSettings.of(config)
    assert an.AnchorSettings.of(with_value('"off"')).ramp == "off"
    assert an.AnchorSettings.of(with_value('"capped_storms"')).ramp == "capped_storms"


def test_the_fit_as_built_is_reported_beside_the_served_one() -> None:
    found = storm("warning", 0, 3, 100, 100)
    fitted = ramp_fit("warning", found)
    ramp = ramp_of(fitted)
    built = built_fit("warning", found)
    assert ramp.built is not None
    assert ramp.built.level == float(built.level(0.0)) == pytest.approx(0.906, abs=1e-3)
    assert (ramp.built.q, ramp.built.tau, ramp.built_error) == (built.q, built.tau, None)
    assert ramp.raw.level == pytest.approx(0.772, abs=1e-3)  # the tempered posterior: not that
    assert float(fitted.level(0.0)) == pytest.approx(0.493, abs=1e-3)
    empty = ramp_of(ramp_fit("warning", []))
    assert empty.built == empty.raw == empty.start
    assert empty.start.level == pytest.approx(0.4498, abs=1e-4)


def record_row(
    district: str, label: str, key: str, market: str, tier: str = "A"
) -> dict[str, object]:
    """One made-up row of the record, as L1 writes it."""
    return {**row(district, label, tier, weather=WEATHER_CODE[key], lists=1), "market": market}


def record_storm(  # noqa: PLR0913, PLR0917 - one made-up day of the record
    folder: Path,
    day: date,
    key: str,
    markets: int,
    count: int,
    closed: int,
    trials: list[dict[str, object]] | None = None,
) -> None:
    """A made-up day of the record: ``markets`` markets of ``count`` rows of the class,
    ``closed`` of each closed, with its trial lines."""
    found = [
        record_row(f"{m:02d}{i:05d}", "no_school" if i < closed else "unnamed", key, f"M{m}")
        for m in range(markets)
        for i in range(count)
    ]
    write_day(folder, day, found, trials or [])


def test_a_fit_as_built_that_raises_leaves_the_served_fit_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "reads"
    record_storm(folder, MONDAY, "warning", 3, 100, 100)
    config = ramp_config(ramp="capped_storms")
    whole = serving_anchor(config, world.model(), folder=folder)
    real = an.fit_class

    def as_built_raises(*args: Any, **keywords: Any) -> an.ClassFit:
        if args[1] and not keywords:  # rows and no weights: the fit as built
            raise ArithmeticError("made up")
        return real(*args, **keywords)

    monkeypatch.setattr(an, "fit_class", as_built_raises)
    said: list[str] = []
    found = serving_anchor(config, world.model(), folder=folder, warn=said.append)
    assert whole is not None
    assert found is not None
    for key in CLASSES:
        assert served(found.fits[key]) == served(whole.fits[key])
    ramp = ramp_of(found.fits["warning"])
    assert (ramp.built, ramp.built_error) == (None, "ArithmeticError")
    assert ramp_of(whole.fits["warning"]).built is not None
    assert said == ["anchor: the fit as built of warning: ArithmeticError: not in the line"]
    line = anchor_labels.anchor_line(found)
    assert "warning w 0.125 by storms 1.00 of 8 raw 0.771 q 0.110 built unavailable, cold" in line
    report = found.summary()["classes"]["warning"]["ramp"]  # type: ignore[index]
    assert (report["built"], report["built_error"]) == (None, "ArithmeticError")


def test_the_plausibility_check_judges_the_ramped_level() -> None:
    # (guard) the plausibility backstop reads the ramped alpha, with its code unchanged
    found = storm("warning", 0, 3, 100, 100)
    labels = an.LiveLabels(rows=tuple(found), trials=SURE, days=1, found=True)
    anchor = an.fit(RAMPED, EMPTY, labels, {})
    rates = anchor.rates([an.Unit(None, None, None)], grid=None)
    for j, key in enumerate(CLASSES):
        level = float(anchor.fits[key].level(0.0))
        assert rates.plausible.levels[key] == pytest.approx(level, abs=1e-12)
        assert rates.p[0, j] == pytest.approx(level, abs=1e-12)
        assert rates.q[j] == anchor.fits[key].q
    assert rates.plausible.levels["warning"] == pytest.approx(0.493, abs=1e-3)


# --- the take-back ---------------------------------------------------------------------------


def sums(folder: Path) -> dict[str, str]:
    """Every record file's sha256."""
    return {
        str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def learn_with(
    days: tuple[date, ...] = (), pairs: tuple[tuple[date, str], ...] = ()
) -> LearnSettings:
    return world.CONFIG.learn.model_copy(update={"excluded_days": days, "excluded_rows": pairs})


def same_fit(one: an.LiveLabels, other: an.LiveLabels) -> None:
    """Both labels, the take-back's own counts apart, are equal and fit the same."""
    assert replace(one, left_out=an.LeftOut()) == replace(other, left_out=an.LeftOut())
    first, second = (an.fit(RAMPED, EMPTY, labels, {}).summary() for labels in (one, other))
    first.pop("left_out")
    second.pop("left_out")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["classes"]["warning"]["rows"] > 0  # type: ignore[index]


def test_an_excluded_day_reads_as_if_it_was_never_labeled(tmp_path: Path) -> None:
    one, two, three = MONDAY, MONDAY + timedelta(days=1), MONDAY + timedelta(days=8)
    lost = MONDAY + timedelta(days=9)
    trial = {"district": "0000001", "source": "s", "tier": "A", "named": True, "weather": 5}
    held, never = tmp_path / "held", tmp_path / "never"
    for folder in (held, never):
        record_storm(folder, one, "warning", 2, 40, 10, [trial, {**trial, "named": False}])
        record_storm(folder, three, "warning", 3, 40, 30, [trial])
    record_storm(held, two, "warning", 3, 100, 100, [trial] * 4)
    (held / "rows" / f"{lost.isoformat()}.json").write_text("not JSON")  # never opened
    before = sums(held)
    said: list[str] = []
    excluded = learn_with(days=(two, lost, MONDAY - timedelta(days=300)))
    taken = read_labels(held, since=SETTINGS.fit_from, warn=said.append, excluded=excluded)
    plain = read_labels(never, since=SETTINGS.fit_from, warn=said.append)
    assert said == []
    assert sums(held) == before
    same_fit(taken, plain)
    assert (taken.days, len(taken.rows), taken.trials["A"].trials) == (2, 200, 3)
    assert taken.left_out == an.LeftOut(days_listed=3, days=2, rows_listed=0, rows=0, trials=0)
    assert plain.left_out == an.LeftOut()
    # without the take-back the day is in the fit (and the file that is not JSON is said)
    every = read_labels(held, since=SETTINGS.fit_from, warn=said.append, excluded=learn_with())
    assert (every.days, len(every.rows), len(said)) == (3, 500, 1)
    # with no record at all the listed counts are still there
    none = read_labels(tmp_path / "none", excluded=excluded)
    assert (none.found, none.left_out) == (False, an.LeftOut(days_listed=3))


def test_an_excluded_row_reads_as_if_its_district_was_never_labeled_that_day(
    tmp_path: Path,
) -> None:
    one, two, three = MONDAY, MONDAY + timedelta(days=1), MONDAY + timedelta(days=8)
    taken_back = "0000003"  # a closed row of the first market
    trials = [
        {"district": taken_back, "source": "s", "tier": "A", "named": True, "weather": 5},
        {"district": taken_back, "source": "t", "tier": "A", "named": False, "weather": 5},
        {"district": "0000004", "source": "s", "tier": "A", "named": True, "weather": 5},
        {"tier": "A", "named": False},  # no district (a test fixture's line): kept
    ]
    held, never = tmp_path / "held", tmp_path / "never"
    record_storm(held, one, "warning", 2, 40, 10, trials)
    record_storm(held, two, "warning", 3, 100, 100, trials)
    record_storm(held, three, "warning", 3, 40, 30, trials)  # the same district, another day
    for folder in (held, never):
        (folder / "rows").mkdir(parents=True, exist_ok=True)
    body = json.loads((held / "rows" / f"{one.isoformat()}.json").read_text())
    body["rows"] = [made for made in body["rows"] if made["district"] != taken_back]
    write_day(never, one, body["rows"], trials[2:])
    record_storm(never, three, "warning", 3, 40, 30, trials)
    before = sums(held)
    excluded = learn_with(
        days=(two,),
        pairs=(
            (one, taken_back),
            (two, "0000001"),  # a day in both lists: the day wins, the pair is not held
            (one, "9999999"),  # no labeled row that day
            (MONDAY + timedelta(days=30), taken_back),  # listed before its day is labeled
        ),
    )
    said: list[str] = []
    taken = read_labels(held, since=SETTINGS.fit_from, warn=said.append, excluded=excluded)
    plain = read_labels(never, since=SETTINGS.fit_from)
    assert said == []
    assert sums(held) == before
    same_fit(taken, plain)
    assert (taken.days, len(taken.rows)) == (2, 199)
    assert taken.trials["A"] == an.Trials(hits=3, trials=6, dates=2)
    assert sum(made.district == taken_back for made in taken.rows) == 1  # the other day's stays
    assert taken.left_out == an.LeftOut(days_listed=1, days=1, rows_listed=4, rows=1, trials=2)
    # through the serving path: the lists come from the config, and the line says them
    config = ramp_config(ramp="capped_storms").model_copy(update={"learn": excluded})
    anchor = serving_anchor(config, world.model(), folder=held)
    assert anchor is not None
    assert anchor.fits["warning"].rows == 199
    assert "; take-back 1 day listed (1 in the record), 4 rows listed (1 in the record); 2 la" in (
        anchor_labels.anchor_line(anchor)
    )
    assert anchor.summary()["left_out"] == {
        "days_listed": 1, "days": 1, "rows_listed": 4, "rows": 1, "trials": 2,
    }  # fmt: skip


# --- the lines -------------------------------------------------------------------------------


def test_the_log_line_says_the_ramp_the_tempered_storms_and_the_take_back() -> None:
    # The only storm is advisory: Wednesday and Thursday, Dec 2 and 3, of 3 markets of 100
    # rows, 10 closed and 15 delayed in each.
    found = storm("advisory", 2, 3, 100, 10, 15, mornings=2)
    left_out = an.LeftOut(days_listed=1, days=1, rows_listed=3, rows=2, trials=0)
    labels = an.LiveLabels(rows=tuple(found), trials=SURE, days=11, found=True, left_out=left_out)
    anchor = an.fit(RAMPED, EMPTY, labels, {})
    assert anchor_labels.anchor_line(anchor) == (
        "anchor: advisory 0.102 (0.044-0.207) q 0.112 rows 600 on 2 dates; "
        "warning 0.450 (0.212-0.710) q 0.110 rows 0 on 0 dates; "
        "cold 0.100 (0.036-0.231) q 0.110 rows 0 on 0 dates; "
        "ramp advisory w 0.125 by storms 1.00 of 8 raw 0.114 q 0.124 built 0.138 q 0.166, "
        "warning w 0.000 no rows, cold w 0.000 no rows; "
        "tempered advisory 2026-12-02 x2 level 0.644 to 0.250 delays 0.982 to 0.250; "
        "take-back 1 day listed (1 in the record), 3 rows listed (2 in the record); "
        "11 labeled days"
    )
    quiet = an.LiveLabels(rows=(), trials={}, days=9, found=True)
    assert anchor_labels.anchor_line(an.fit(RAMPED, EMPTY, quiet, {})) == (
        "anchor: advisory 0.100 (0.043-0.206) q 0.110 rows 0 on 0 dates; "
        "warning 0.450 (0.212-0.710) q 0.110 rows 0 on 0 dates; "
        "cold 0.100 (0.036-0.231) q 0.110 rows 0 on 0 dates; "
        "ramp advisory w 0.000 no rows, warning w 0.000 no rows, cold w 0.000 no rows; "
        "tempered none; take-back none listed; 9 labeled days"
    )
    off = anchor_labels.anchor_line(an.fit(AS_BUILT, EMPTY, labels, {}))
    assert off.startswith("anchor: advisory 0.138 (")
    assert off.endswith(
        "rows 0 on 0 dates; ramp off; take-back 1 day listed (1 in the record), 3 rows listed "
        "(2 in the record); 11 labeled days"
    )
    listed = replace(quiet, left_out=an.LeftOut(days_listed=2, days=0, rows_listed=1, rows=0))
    assert "; take-back 2 days listed (0 in the record), 1 row listed (0 in the record); " in (
        anchor_labels.anchor_line(an.fit(RAMPED, EMPTY, listed, {}))
    )
    only_days = replace(quiet, left_out=an.LeftOut(days_listed=1, days=1))
    assert "; take-back 1 day listed (1 in the record), 0 rows listed (0 in the record); " in (
        anchor_labels.anchor_line(an.fit(RAMPED, EMPTY, only_days, {}))
    )
    # Seven tempered storms: six are named, by class then first date, and the rest counted.
    many = [
        *(made for j in range(3) for made in storm("advisory", 14 * j, 50, 1, 1)),
        *(made for j in range(3) for made in storm("advisory", 14 * j + 7, 1, 100)),
        *storm("warning", 0, 3, 100, 100),
    ]
    busy = an.fit(RAMPED, EMPTY, replace(labels, rows=tuple(many)), {})
    line = anchor_labels.anchor_line(busy)
    tempered = line.split("; ")[4]
    assert tempered.startswith("tempered advisory 2026-11-30 x1 level 0.")
    assert tempered.count("advisory 202") == 6
    assert ", advisory 2026-12-07 x1 delays 0.323 to 0.250, advisory 2026-12-14 x1 level 0." in (
        tempered
    )
    assert tempered.endswith(", advisory 2027-01-04 x1 delays 0.323 to 0.250 and 1 more")
    assert "warning" not in tempered
    report = busy.summary()
    assert (report["ramp"], report["left_out"]) == ("capped_storms", left_out.summary())
    assert set(report["labels"]) == {"found", "days", "rows", "through"}  # type: ignore[call-overload]
    ramp = report["classes"]["advisory"]["ramp"]  # type: ignore[index]
    assert set(ramp) == {
        "w", "bound", "rows", "rows_full", "storms", "storms_full", "market_days",
        "market_days_full", "gap", "cap", "storm_count", "start", "raw", "built", "built_error",
        "tempered",
    }  # fmt: skip
    assert set(ramp["start"]) == {"level", "band", "alpha", "q"}
    assert set(ramp["raw"]) == {"level", "band", "alpha", "q", "tau", "predictive"}
    assert set(ramp["built"]) == {"level", "band", "q", "tau"}
    assert len(ramp["tempered"]) == 6
    assert set(ramp["tempered"][0]) == {
        "storm", "dates", "share", "weight", "delay_share", "delay_weight",
    }  # fmt: skip
    assert (ramp["gap"], ramp["cap"], ramp["storm_count"]) == (1, 0.25, 6)
    assert (ramp["rows_full"], ramp["storms_full"], ramp["market_days_full"]) == (300, 8, 15)
    warning = report["classes"]["warning"]["ramp"]  # type: ignore[index]
    assert (warning["market_days_full"], len(warning["tempered"])) == (None, 1)
    assert warning["tempered"][0]["dates"] == ["2026-11-30"]


def test_the_ramped_fit_and_the_storm_weights_speed() -> None:
    # (guard) On the season record of test_the_fit_is_deterministic_and_fast, in process time:
    # each class's ramped fit (the served fit and the fit as built) and its storms with both
    # sets of weights. Named _speed so CI times it alone in its serial step, which runs under
    # coverage: each timed block is quiet(), so it reads the fit's cost and not the tracer's
    # or BLAS's waiting threads'.
    rng = np.random.default_rng(11)
    found = [
        *season(rng, "advisory", 150, 60),
        *season(rng, "snow_warning", 60, 60),
        *season(rng, "cold", 30, 40),
    ]
    known = replace(
        EMPTY,
        districts={
            made.district: (
                float(rng.uniform(0, 20)), float(rng.uniform(0, 10)), float(rng.uniform(0, 3))
            )
            for made in found
        },
        f_ref={"advisory": 4.0, "warning": 1.4, "cold": 0.3},
    )  # fmt: skip
    stub = an.Anchor(RAMPED, known, {}, {}, an.NO_LABELS)
    for j, key in enumerate(CLASSES):
        mine = [made for made in found if RAMPED.class_of[made.weather] == key]

        def offset_of(leaid: str, j: int = j) -> float:
            return stub.offsets(an.Unit(leaid, None, None))[0][j]

        fits = []
        fitted = an.ramped(key, [], offset_of, SURE, RAMPED)
        for _ in range(3):
            with quiet():
                started = time.process_time()
                fitted = an.ramped(key, mine, offset_of, SURE, RAMPED)
                fits.append(time.process_time() - started)
        assert ramp_of(fitted).built is not None
        assert fitted.rows == len(mine)
        assert min(fits) < 1.0, (key, fits)
        tables = []
        for _ in range(5):
            with quiet():
                started = time.process_time()
                an.storm_table(key, mine, RAMPED, fitted.alpha)
                tables.append(time.process_time() - started)
        assert min(tables) < 0.010, (key, tables)
