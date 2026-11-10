"""The class anchor (advisory-sane L3, Addendum A items 1, 2, 4 and 5): the chance served on a
storm-class day, from capture-corrected priors updated by the live, outcome-blind labels, never
from an archive closure share.

The classes (``live_score.classes``): ``advisory`` (advisory, advisory_after), ``cold``, and
``warning`` (snow_warning, lake_snow, ice, blizzard, tropical). ``none`` and ``none_after`` stay
on the served chain (:mod:`snowlight.predict.pool`).

For a read district-day ``i`` of class ``c`` on market-day ``j``::

    p_ij         = sigmoid(alpha_c + o_i + e_j),  e_j ~ N(0, tau^2)
    o_i          = delta_region(i) + beta * x_i,  x_i = -ln((f_i + 0.5) / (f_ref + 0.5))
    P(no school) = p_ij
    P(delayed)   = (1 - p_ij) * q_c
    P(unnamed)   = 1 - s_t * (p_ij + (1 - p_ij) * q_c)     (t the row's tier; lit rows drop s)

Every number here is registered in ``config/predict.yaml`` ``live_score`` (L0, sha256 pinned):
the priors on ``alpha_c`` (normal, mean solved so the level at the prior mean is the target at
``tau``), the delay prior Beta(1.1, 8.9), the grids, ``tau``, the exposure term (``beta`` 0.5,
:mod:`snowlight.predict.exposure`), the half-strength region deltas where the archive's region
record of the class has level support, the list sensitivities and the plausibility pull.

* ``alpha_c`` has a posterior on an 801-point grid; ``e_j`` is integrated out per
  market-day on that grid's own points (each market-day's likelihood is a function of
  ``alpha + e`` alone, tabled once on the grid, then summed against the ``N(0, tau^2)``
  density: exact for a market-day of hundreds of rows, where the registered 20-point
  Gauss-Hermite rule on ``N(0, tau^2)`` is not, R2-S1; accepted by the lead's ruling of Oct
  31); the registered 20-point rule still gives the served level's mean over ``e`` (a smooth
  integrand, where it is exact to 1e-6).
  ``q_c`` has a 401-point grid posterior on the rows not closed, plugged in. For speed a row's
  offset is counted in whole grid steps (0.015, at most half a step off), each label's log
  chance is tabled once on the grid, and the grid is computed in full only where a coarse
  pass finds the posterior within e^-40 of its top: a season of advisory rows fits in well
  under a second.
* The **level** of a unit with offset ``o`` is ``E_e[sigmoid(alpha_bar + o + e)]``, the marginal
  mean over the market-day effect at the posterior mean ``alpha_bar``: with no live label it is
  exactly the registered target (10% advisory and cold, 45% warning at the reference district).
* The **live update** (Addendum B2) is this posterior over the per-class label counts of the
  outcome-blind record (:mod:`snowlight.predict.anchor_labels`), refreshed each day; with no
  record the level is the prior's. The registered live region and state deviations
  (``standing.live_region_sd``, ``live_state_sd``) and the warning split by alert kind
  (``split``) are deferred: Addendum B2 makes the live update a pure posterior over per-class
  label counts (docs/predict.md, "The storm-class levels").
* The **ramp** (predict-next ONE-STORM, ``live_update.ramp`` ``"capped_storms"``; ``"off"``
  serves the posterior as built): one storm cannot move a level far. A class's mornings with
  at most ``ramp_storm_gap`` weekdays between them are one storm. Each market-day counts its
  information about ``alpha`` (``n / (n + c)`` whole market-days for ``n`` rows, from the row
  counts alone), and no storm may hold more than the class's registered share
  (``supply.<class>.max_date_share``) of the information, the start's counted in: a storm over
  it is tempered to it (:func:`storm_weights`), and so are a storm's open rows in the delay
  share, against that prior's own weight. The level, its band and the delay share then go from
  the no-row fit toward that tempered posterior by ``w``, the least of the class's rows,
  storms and market-days over their registered full counts (``ramp_<class>``), and ``tau``
  stays registered until ``w`` is 1 (:func:`ramped`). With no used row the fit is the no-row
  fit itself; at ``w`` 1 it is the tempered posterior itself. The fit as built is made beside
  it for the log line only.
* The **plausibility pull** (G6, item 5): a district whose implied closures a winter (its days
  of each class times its chance) are over ``district_max`` is pulled toward its class level on
  the log-odds scale until they are not; then while the national clauses fail, the districts with
  the most implied closures take one more step each.

Nothing here reads a closure share of the archive: the region deltas take only the region and
nation tallies the exposure file holds (:func:`region_delta`).
"""

import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Final, Literal

import numpy as np
import numpy.typing as npt

from snowlight.predict.config import PredictConfig
from snowlight.predict.exposure import CLASSES, Exposure, Tally
from snowlight.predict.forecast_adjust import AdjustSettings, Climate
from snowlight.predict.pool import level_supported

type Floats = npt.NDArray[np.float64]
type Tier = Literal["A", "B"]
type Standing = Literal["usual", "more", "fewer"]
type LabelKind = Literal["no_school", "delayed", "unnamed"]
type RampRule = Literal["capped_storms", "off"]

CHAIN: Final = "chain"
"""A situation ``live_score.classes`` leaves on the served chain."""
STANDINGS: Final[tuple[Standing, ...]] = ("usual", "more", "fewer")
STANDING_ODDS: Final = 0.1
"""A unit's exposure moves its odds by more than this (on the log scale) for its sentence to
say it gets more or fewer of the class's alerts than most districts."""
_TINY: Final = 1e-300


def sigmoid(value: Floats) -> Floats:
    """The logistic function."""
    return np.asarray(1.0 / (1.0 + np.exp(-value)), dtype=np.float64)


def logit(p: Floats) -> Floats:
    """The log-odds of ``p`` (clipped away from 0 and 1)."""
    clipped = np.clip(p, 1e-9, 1 - 1e-9)
    return np.asarray(np.log(clipped / (1 - clipped)), dtype=np.float64)


# --- settings -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Prior:
    """A class's prior on ``alpha`` (normal)."""

    target: float
    alpha_mean: float
    alpha_sd: float


@dataclass(frozen=True, slots=True)
class Plausibility:
    """The implied-closures clauses (G6) and the pull's step."""

    advisory_mean: float
    advisory_p99: float
    advisory_warning_mean: float
    district_max: float
    step: float


@dataclass(frozen=True, slots=True)
class Grid:
    """The grid a chance is published on (:func:`snowlight.predict.pool.publish_rates`):
    hundredths, within ``[floor, ceiling]``. The plausibility check (G6) holds the chances as
    published, never only the raw ones (rounding adds up to half a hundredth of a class's days,
    and the floor more)."""

    floor: float
    ceiling: float

    def round(self, p: Floats) -> Floats:
        """``p`` as published: to the nearest hundredth, within the floor and ceiling."""
        return np.asarray(np.clip(np.round(p, 2), self.floor, self.ceiling), dtype=np.float64)

    def down(self, p: Floats) -> Floats:
        """``p`` to the hundredth at or under it, within the floor and ceiling (a grid point
        :meth:`round` keeps)."""
        return np.asarray(
            np.clip(np.floor(np.asarray(p) * 100 + 1e-9) / 100, self.floor, self.ceiling),
            dtype=np.float64,
        )


PUBLISHED: Final = Grid(0.01, 0.99)
"""The served grid (``config/predict.yaml`` ``floor`` and ``ceiling``); serving passes its own."""


@dataclass(frozen=True, slots=True)
class RampFull:
    """The counts a class's ramp is full at (``live_update.ramp_<class>``): its used rows, its
    storms and (where registered) its market-days, the last two counted by information."""

    rows: float
    storms: float
    market_days: float | None = None


RAMP_RULES: Final[tuple[RampRule, ...]] = ("capped_storms", "off")
RAMP_KEYS: Final = ("rows", "storms", "market_days")
STORM_GAP_MOST: Final = 5


@dataclass(frozen=True, slots=True)
class AnchorSettings:
    """``live_score`` as the anchor reads it."""

    class_of: Mapping[str, str]
    """Situation key to its class, or :data:`CHAIN`."""
    priors: Mapping[str, Prior]
    delay_prior: tuple[float, float]
    grid: tuple[float, float, int]
    delay_grid: int
    tau: float
    tau_choices: tuple[float, ...]
    tau_free_market_days: int
    nodes: int
    beta: float
    offset: float
    delta_strength: float
    delta_clip: float
    tier_a_prior: tuple[float, float]
    tier_b_prior: tuple[float, float]
    tier_b_min: float
    tier_b_min_trials: int
    tier_b_min_dates: int
    plausibility: Plausibility
    fit_from: date
    ramp: RampRule
    """``live_update.ramp``: ``capped_storms`` (:func:`ramped`), or ``off`` (the fit as
    built, :func:`fit_class`)."""
    ramps: Mapping[str, RampFull]
    """Each class's full counts (``live_update.ramp_<class>``)."""
    storm_gap: int
    """``live_update.ramp_storm_gap``: mornings of a class with at most this many weekdays
    between them are one storm."""
    date_cap: Mapping[str, float]
    """Each class's ``supply.<class>.max_date_share``, read as the most one storm may hold."""

    @classmethod
    def of(cls, config: PredictConfig) -> "AnchorSettings":
        """Read from the registered block.

        Raises:
            ValueError: a setting is missing or not the registered kind.
        """
        score = config.live_score
        prior = score["prior"]
        standing = score["standing"]
        sens = score["sensitivity"]
        plaus = score["plausibility"]
        update = score["live_update"]

        def number(block: Mapping[str, object], key: str) -> float:
            found = block[key]
            if isinstance(found, bool) or not isinstance(found, int | float):
                raise ValueError(f"live_score {key} is not a number: {found!r}")
            return float(found)

        def pair(block: Mapping[str, object], key: str) -> tuple[float, float]:
            found = block[key]
            if not isinstance(found, list) or len(found) != 2:  # noqa: PLR2004 - a pair
                raise ValueError(f"live_score {key} is not a pair: {found!r}")
            return float(found[0]), float(found[1])

        priors: dict[str, Prior] = {}
        for klass in CLASSES:
            entry = prior[klass]
            if not isinstance(entry, dict):
                raise ValueError(f"live_score prior {klass} is not a mapping")
            priors[klass] = Prior(
                float(entry["target"]), float(entry["alpha_mean"]), float(entry["alpha_sd"])
            )
        grid = prior["alpha_grid"]
        choices = prior["tau_choices"]
        if not isinstance(grid, list) or not isinstance(choices, list):
            raise ValueError("live_score prior alpha_grid and tau_choices are lists")
        if update["prior_weight"] != "alpha_sd":
            raise ValueError("live_score live_update prior_weight is not alpha_sd")
        ramp, ramps, storm_gap, date_cap = _ramp_settings(update, score["supply"])
        return cls(
            class_of={str(k): str(v) for k, v in score["classes"].items()},
            priors=priors,
            delay_prior=pair(prior, "delay_beta"),
            grid=(float(grid[0]), float(grid[1]), int(grid[2])),
            delay_grid=int(number(prior, "delay_grid")),
            tau=number(prior, "tau"),
            tau_choices=tuple(float(item) for item in choices),
            tau_free_market_days=int(number(prior, "tau_free_market_days")),
            nodes=int(number(prior, "quadrature_points")),
            beta=number(standing, "exposure_beta"),
            offset=number(standing, "exposure_offset"),
            delta_strength=number(standing, "region_delta_strength"),
            delta_clip=number(standing, "region_delta_clip"),
            tier_a_prior=pair(sens, "tier_a_prior"),
            tier_b_prior=pair(sens, "tier_b_prior"),
            tier_b_min=number(sens, "tier_b_min"),
            tier_b_min_trials=int(number(sens, "tier_b_min_trials")),
            tier_b_min_dates=TIER_B_MIN_DATES,
            plausibility=Plausibility(
                advisory_mean=number(plaus, "advisory_mean"),
                advisory_p99=number(plaus, "advisory_p99"),
                advisory_warning_mean=number(plaus, "advisory_warning_mean"),
                district_max=number(plaus, "district_max"),
                step=number(plaus, "pull_step"),
            ),
            fit_from=date.fromisoformat(str(update["fit_from"])),
            ramp=ramp,
            ramps=ramps,
            storm_gap=storm_gap,
            date_cap=date_cap,
        )


def _ramp_settings(
    update: Mapping[str, object], supply: Mapping[str, object]
) -> tuple[RampRule, dict[str, RampFull], int, dict[str, float]]:
    """The ramp's registered values (``live_update.ramp``, ``ramp_<class>``,
    ``ramp_storm_gap``) and each class's ``supply.<class>.max_date_share``.

    Raises:
        ValueError: one is missing or not the registered kind.
    """
    if "ramp" not in update:
        raise ValueError("live_score live_update ramp is missing")
    ramp = update["ramp"]
    if isinstance(ramp, bool):
        raise ValueError(
            f"live_score live_update ramp is a bare YAML word (read as {ramp!r}): write the "
            'value in quotes, "capped_storms" or "off"'
        )
    if ramp not in RAMP_RULES:
        raise ValueError(f'live_score live_update ramp is not "capped_storms" or "off": {ramp!r}')
    ramps: dict[str, RampFull] = {}
    for klass in CLASSES:
        name = f"ramp_{klass}"
        entry = update.get(name)
        if not isinstance(entry, dict):
            raise ValueError(f"live_score live_update {name} is missing")
        for key, value in entry.items():
            if key not in RAMP_KEYS:
                raise ValueError(
                    f"live_score live_update {name} has a key that is not rows, storms or "
                    f"market_days: {key}"
                )
            if isinstance(value, bool) or not isinstance(value, int | float) or value < 1:
                raise ValueError(f"live_score live_update {name} {key} is under 1: {value!r}")
        if "rows" not in entry or "storms" not in entry:
            raise ValueError(f"live_score live_update {name} has no rows or no storms")
        ramps[klass] = RampFull(
            rows=float(entry["rows"]),
            storms=float(entry["storms"]),
            market_days=float(entry["market_days"]) if "market_days" in entry else None,
        )
    gap = update.get("ramp_storm_gap")
    if isinstance(gap, bool) or not isinstance(gap, int) or not 0 <= gap <= STORM_GAP_MOST:
        raise ValueError(
            f"live_score live_update ramp_storm_gap is not a whole number from 0 to 5: {gap!r}"
        )
    date_cap: dict[str, float] = {}
    for klass in CLASSES:
        entry = supply.get(klass)
        share = entry.get("max_date_share") if isinstance(entry, dict) else None
        if isinstance(share, bool) or not isinstance(share, int | float) or not 0 < share < 1:
            raise ValueError(
                f"live_score supply {klass} max_date_share is not between 0 and 1: {share!r}"
            )
        date_cap[klass] = float(share)
    return ramp, ramps, gap, date_cap


TIER_B_MIN_DATES: Final = 5
"""Addendum B1.5: tier B rows enter only with closed co-listing trials on this many dates."""


# --- the live labels ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveRow:
    """One labeled, read district-day of the outcome-blind record."""

    day: date
    district: str
    market: str | None
    tier: Tier
    label: LabelKind
    weather: str
    """The situation key of the day (``advisory_after``)."""
    lists: int = 1
    """The lists that read it whole that day (the record's ``sources``). The likelihood
    takes one list's sensitivity per row as registered (R2-S4: an unnamed row read by two
    lists hides fewer closings than one list's sensitivity says, if their misses are
    independent; the trials cannot tell, since they condition on a list having named the
    district). Counted for the private report (:attr:`ClassFit.multi_list`)."""

    @property
    def market_day(self) -> tuple[date, str]:
        """The cluster of its random effect: its market that day, or the district alone."""
        return self.day, self.market if self.market is not None else f"~{self.district}"


@dataclass(frozen=True, slots=True)
class Trials:
    """Closed co-listing trials of one tier: hits of trials, on dates."""

    hits: int = 0
    trials: int = 0
    dates: int = 0


@dataclass(frozen=True, slots=True)
class LeftOut:
    """What the take-back lists (``learn.excluded_days``, ``learn.excluded_rows``) name and
    what of it the record held when it was read (counts only)."""

    days_listed: int = 0
    """Distinct days of ``learn.excluded_days``."""
    days: int = 0
    """Those whose rows file the record holds from the fit's first day on: skipped unread."""
    rows_listed: int = 0
    """Distinct pairs of ``learn.excluded_rows``."""
    rows: int = 0
    """Labeled rows a pair dropped from a day that was read."""
    trials: int = 0
    """Trial lines dropped with them."""

    def summary(self) -> dict[str, int]:
        """The private report's counts (``anchor.json``)."""
        return {
            "days_listed": self.days_listed,
            "days": self.days,
            "rows_listed": self.rows_listed,
            "rows": self.rows,
            "trials": self.trials,
        }


@dataclass(frozen=True, slots=True)
class LiveLabels:
    """What the outcome-blind record holds (empty: no record on this head)."""

    rows: tuple[LiveRow, ...] = ()
    trials: Mapping[Tier, Trials] = field(default_factory=dict)
    days: int = 0
    """Labeled days read."""
    found: bool = False
    """Whether a record was found at all."""
    left_out: LeftOut = LeftOut()
    """What the take-back lists name and what of it the record held (a row or a day left out
    is in none of the counts above: the labels are those of a record that never held it)."""


NO_LABELS: Final = LiveLabels()


# --- the fit -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Told:
    """A fit of the class as the ramp reports it: the reference district's level and 80% band,
    and the ``alpha``, delay share and ``tau`` they are made from."""

    level: float
    band: tuple[float, float]
    alpha: float
    q: float
    tau: float
    predictive: float

    def summary(self, *keys: str) -> dict[str, object]:
        """The private report's numbers, the named keys only."""
        found: dict[str, object] = {
            "level": round(self.level, 4),
            "band": [round(self.band[0], 4), round(self.band[1], 4)],
            "alpha": round(self.alpha, 4),
            "q": round(self.q, 4),
            "tau": self.tau,
            "predictive": round(self.predictive, 4),
        }
        return {key: found[key] for key in keys}


@dataclass(frozen=True, slots=True)
class Tempered:
    """A storm held to the class's registered share: in the level, in the delay share, or in
    both (a weight of 1: not in that one)."""

    storm: date
    """Its first date."""
    dates: tuple[date, ...]
    share: float
    """Its share of the information about the level before the cap, the start counted in."""
    weight: float
    """What its market-days count for in the level's likelihood (after: the cap exactly)."""
    delay_share: float
    """Its open rows' share of the delay share's rows before the cap, the start counted in."""
    delay_weight: float

    def summary(self) -> dict[str, object]:
        """The private report's numbers."""
        return {
            "storm": self.storm.isoformat(),
            "dates": [day.isoformat() for day in self.dates],
            "share": round(self.share, 4),
            "weight": round(self.weight, 5),
            "delay_share": round(self.delay_share, 4),
            "delay_weight": round(self.delay_weight, 5),
        }


type Bound = Literal["none", "rows", "storms", "market_days", "full"]


@dataclass(frozen=True, slots=True)
class Ramp:
    """How a class's served fit was ramped from its start (:func:`ramped`)."""

    w: float
    """The ramp weight: 0 with no used row, 1 at full."""
    bound: Bound
    """The count that holds ``w`` under 1 (``full`` at 1, ``none`` with no row)."""
    rows: int
    storms: float
    """Its storms, each counted as ``min(1, its information after the cap)``."""
    market_days: float
    """Its market-days' information, summed."""
    full: RampFull
    gap: int
    cap: float
    storm_count: int
    start: Told
    """The no-row fit."""
    raw: Told
    """The tempered posterior at the ``tau`` the ramp allows: what ``w`` 1 serves."""
    built: Told | None
    """The fit as built (what ``ramp: "off"`` would serve); ``None`` where it raised."""
    built_error: str | None = None
    """The type of the error that fit raised."""
    tempered: tuple[Tempered, ...] = ()
    """The storms with a weight under 1, by first date."""

    def summary(self) -> dict[str, object]:
        """The private report's numbers (``anchor.json``)."""
        return {
            "w": round(self.w, 5),
            "bound": self.bound,
            "rows": self.rows,
            "rows_full": self.full.rows,
            "storms": round(self.storms, 4),
            "storms_full": self.full.storms,
            "market_days": round(self.market_days, 4),
            "market_days_full": self.full.market_days,
            "gap": self.gap,
            "cap": self.cap,
            "storm_count": self.storm_count,
            "start": self.start.summary("level", "band", "alpha", "q"),
            "raw": self.raw.summary("level", "band", "alpha", "q", "tau", "predictive"),
            "built": None
            if self.built is None
            else self.built.summary("level", "band", "q", "tau"),
            "built_error": self.built_error,
            "tempered": [storm.summary() for storm in self.tempered],
        }


@dataclass(frozen=True, slots=True)
class ClassFit:
    """One class's posterior."""

    key: str
    prior: Prior
    alpha: float
    """The posterior mean of ``alpha``."""
    alpha_band: tuple[float, float]
    """Its 10% and 90% posterior quantiles."""
    q: float
    tau: float
    s_a: float
    s_b: float
    tier_b: bool
    """Whether tier B rows entered (Addendum B1.5)."""
    rows: int
    closed: int
    delayed: int
    unnamed: int
    market_days: int
    dates: int
    k_eff: float
    """Rows weighted by their market-days' design effect: (sum n_j)^2 / sum n_j^2."""
    nodes: tuple[Floats, Floats]
    predictive: float = 0.0
    """The posterior mean of the reference district's marginal level (the Bayes predictive
    chance), reported beside the served level (the level at the posterior mean of ``alpha``)
    (the lead's ruling of Oct 31: the plug-in level serves, the predictive is reported and
    L4's frozen scorer judges calibration); not served."""
    multi_list: int = 0
    """Unnamed rows read by two lists or more (R2-S4, :attr:`LiveRow.lists`): the rows whose
    hidden closings the one-list sensitivity may overstate (the lead's ruling of Oct 31 keeps
    the registered one-list form and revisits once L1's real record shows this share)."""
    ramp: Ramp | None = None
    """How the fit was ramped from its start (:func:`ramped`); ``None`` from :func:`fit_class`
    (the posterior of the rows it is given, as with ``live_update.ramp`` ``"off"``)."""

    def level(self, offset: Floats | float, alpha: float | None = None) -> Floats:
        """``E_e[sigmoid(alpha + offset + e)]`` at the posterior mean (or ``alpha``)."""
        z, w = self.nodes
        a = self.alpha if alpha is None else alpha
        o = np.asarray(offset, dtype=np.float64)
        return np.asarray(
            sigmoid(a + o[..., None] + np.sqrt(2.0) * self.tau * z) @ w, dtype=np.float64
        )

    @property
    def band(self) -> tuple[float, float]:
        """The reference district's level at the 10% and 90% posterior ``alpha``."""
        return (
            float(self.level(0.0, self.alpha_band[0])),
            float(self.level(0.0, self.alpha_band[1])),
        )

    def summary(self) -> dict[str, object]:
        """The private report's numbers of the class (``anchor.json``)."""
        low, high = self.band
        return {
            "level": round(float(self.level(0.0)), 4),
            "band": [round(low, 4), round(high, 4)],
            "prior_level": round(float(self.level(0.0, self.prior.alpha_mean)), 4),
            "predictive": round(self.predictive, 4),
            "alpha": round(self.alpha, 4),
            "q": round(self.q, 4),
            "tau": self.tau,
            "s_a": round(self.s_a, 4),
            "s_b": round(self.s_b, 4),
            "tier_b": self.tier_b,
            "rows": self.rows,
            "closed": self.closed,
            "delayed": self.delayed,
            "unnamed": self.unnamed,
            "market_days": self.market_days,
            "dates": self.dates,
            "k_eff": round(self.k_eff, 2),
            "multi_list": self.multi_list,
            "ramp": None if self.ramp is None else self.ramp.summary(),
        }


def sensitivity(found: Trials, prior: tuple[float, float]) -> float:
    """The posterior mean of a tier's list sensitivity, Beta(a + hits, b + misses)."""
    return (prior[0] + found.hits) / (prior[0] + prior[1] + found.trials)


def _nodes(count: int) -> tuple[Floats, Floats]:
    z, w = np.polynomial.hermite.hermgauss(count)
    return np.asarray(z, dtype=np.float64), np.asarray(w / np.sqrt(np.pi), dtype=np.float64)


def _delay(
    q_prior: tuple[float, float], points: int, delayed: float, unnamed: Sequence[Floats]
) -> float:
    """The posterior mean of ``q`` from the rows not closed: ``delayed`` rows, and the unnamed
    rows as (count, list sensitivity, chance of no school) per cell, each with
    ``P(unnamed) = 1 - s p - s (1 - p) q``: an unnamed row may hide a closing as well as a
    delay, so ``q`` is fitted with ``p`` in its likelihood (R2-S3), not as if ``p`` were 0."""
    q = (np.arange(points, dtype=np.float64) + 0.5) / points
    log = (q_prior[0] - 1 + delayed) * np.log(q) + (q_prior[1] - 1) * np.log1p(-q)
    counts, s, p = unnamed
    if counts.size:
        log += counts @ np.log(
            np.maximum(1 - (s * p)[:, None] - (s * (1 - p))[:, None] * q[None, :], _TINY)
        )
    weight = np.exp(log - log.max())
    return float((weight * q).sum() / weight.sum())


DELAY_ROUNDS: Final = 4
"""``q`` and ``alpha`` are found in turn (``q`` at the posterior mean of ``alpha``, then
``alpha`` at that ``q``) at most this many times, until ``q`` moves under :data:`DELAY_TOL`."""
DELAY_TOL: Final = 1e-4


COARSE: Final = 10
"""The posterior is found first on every tenth point of the ``alpha`` grid..."""
WINDOW_LOG: Final = 40.0
"""...and the full grid is computed only where that is within this of its top (one coarse step
wider each side); beyond it a point's weight is under e^-40 of the top's, counted as 0."""


@dataclass(frozen=True, slots=True)
class _Cells:
    """One label's cells of a market-day: each cell's offset in ``alpha`` grid steps (a row's
    offset is counted on the grid's own step, at most half of it off: under 0.1% of a 10%
    chance), its rows, and (unnamed rows) its list sensitivity."""

    steps: npt.NDArray[np.intp]
    counts: Floats
    s: Floats


@dataclass(frozen=True, slots=True)
class _Cluster:
    """One market-day's cells, each label's apart (cells of no row of it are left out)."""

    closed: _Cells
    delayed: _Cells
    unnamed: _Cells
    day: date | None = None
    """Its school day (its storm's weight is looked up by it; ``None``: it weighs 1)."""

    @property
    def size(self) -> float:
        """Its rows."""
        return float(
            self.closed.counts.sum() + self.delayed.counts.sum() + self.unnamed.counts.sum()
        )


def _clusters(
    used: Sequence[LiveRow],
    offset_of: Callable[[str], float],
    s_of: Mapping[str, float],
    step: float,
) -> list[_Cluster]:
    """The rows' market-days, each row in the cell of its offset (in grid steps), its list
    sensitivity and its label."""
    grouped: dict[tuple[date, str], dict[tuple[int, float], list[int]]] = {}
    for row in used:
        cell = grouped.setdefault(row.market_day, {}).setdefault(
            (round(offset_of(row.district) / step), s_of[row.tier]), [0, 0, 0]
        )
        cell[("no_school", "delayed", "unnamed").index(row.label)] += 1

    def part(cells: Mapping[tuple[int, float], list[int]], label: int) -> _Cells:
        keys = [k for k, v in cells.items() if v[label]]
        return _Cells(
            np.array([k[0] for k in keys], dtype=np.intp),
            np.array([cells[k][label] for k in keys], dtype=np.float64),
            np.array([k[1] for k in keys], dtype=np.float64),
        )

    return [
        _Cluster(part(cells, 0), part(cells, 1), part(cells, 2), day)
        for (day, _), cells in sorted(grouped.items())
    ]


KERNEL_SD: Final = 8.0
"""Each market-day's effect is integrated over this many of its sds either side (the normal
density beyond is under e^-32 of its top)."""


@dataclass(frozen=True, slots=True)
class _Profiles:
    """Each market-day's log-likelihood as a function of ``u = alpha + e`` alone, on the
    ``alpha`` grid's own points extended either side: ``values[j, m]`` at ``u = alpha[0] +
    step * (first + m)``, with each row's ``top``."""

    first: int
    values: Floats
    top: Floats

    @property
    def scaled(self) -> Floats:
        """``exp(values - top)``, each market-day's likelihood over its own top."""
        return np.asarray(np.exp(self.values - self.top[:, None]), dtype=np.float64)


def _profiles(alpha: Floats, clusters: Sequence[_Cluster], q: float, reach: int) -> _Profiles:
    """``l_j(u) = sum_i log P(row_i | u + offset_i)`` per market-day ``j`` with ``P(closed) =
    p``, ``P(delayed) = (1 - p) q`` and ``P(unnamed) = 1 - s (p + (1 - p) q)``, ``p =
    sigmoid(u + offset)``, on the grid extended by ``reach`` points each side.

    A row's offset is a whole number of grid steps, so ``u + offset`` is a grid point too:
    each label's log chance is tabled once on the grid and every cell looks its values up."""
    step = float(alpha[1] - alpha[0])
    first, last = -reach, alpha.size - 1 + reach
    shifts = np.concatenate(
        [
            c.steps
            for cluster in clusters
            for c in (cluster.closed, cluster.delayed, cluster.unnamed)
        ]
    )
    low = first + int(shifts.min())
    t = alpha[0] + step * np.arange(low, last + int(shifts.max()) + 1)
    closed = -np.logaddexp(0.0, -t)
    delayed = -np.logaddexp(0.0, t) + float(np.log(max(q, _TINY)))
    p = sigmoid(t)
    unnamed = {
        s: np.log(np.maximum(1 - s * q - s * (1 - q) * p, _TINY))
        for s in sorted({float(s) for cluster in clusters for s in cluster.unnamed.s})
    }
    points = np.arange(first, last + 1) - low
    values = np.zeros((len(clusters), points.size))
    for j, cluster in enumerate(clusters):
        found = values[j]
        for cells, table in ((cluster.closed, closed), (cluster.delayed, delayed)):
            if cells.counts.size:
                found += cells.counts @ table[cells.steps[:, None] + points[None, :]]
        cells = cluster.unnamed
        for s, table in unnamed.items():
            mine = cells.s == s
            if mine.any():
                found += cells.counts[mine] @ table[cells.steps[mine][:, None] + points[None, :]]
    return _Profiles(first, values, values.max(axis=1) if len(clusters) else np.zeros(0))


def _log_likelihood(  # noqa: PLR0913 - the grid, the rows' profiles and the ramp's weights
    index: npt.NDArray[np.intp],
    alpha: Floats,
    profiles: _Profiles,
    tau: float,
    scaled: Floats | None = None,
    *,
    weights: Floats | None = None,
) -> Floats:
    """``sum_j log int exp(l_j(alpha + e)) dN(e; 0, tau^2)`` at the grid points ``index`` of
    ``alpha``: each market-day's effect is integrated on the grid's own points (the
    trapezoid rule on an even grid, exact to well under 1e-6 for any market-day whose
    likelihood is wider than one grid step: under about 4,000 closings' worth of rows), so
    a market-day of hundreds of rows, whose likelihood is far narrower than ``tau``, is
    integrated as exactly as one of a few (a fixed Gauss-Hermite rule on ``N(0, tau^2)`` is
    not). ``scaled``: :attr:`_Profiles.scaled`, when already found. ``weights``: each
    market-day's log marginal likelihood is multiplied by its own (its storm's weight under
    the cap, :func:`ramped`); ``None``: each counts whole."""
    step = float(alpha[1] - alpha[0])
    reach = int(np.ceil(KERNEL_SD * tau / step))
    lo = max(int(index.min()) - reach, profiles.first)
    hi = min(int(index.max()) + reach, profiles.first + profiles.values.shape[1] - 1)
    span = hi - lo
    # the kernel depends on the grid distance alone: tabled once, looked up (Toeplitz)
    gaps = np.arange(-span, span + 1)
    density = np.exp(-0.5 * (gaps * step / tau) ** 2) * (step / (np.sqrt(2 * np.pi) * tau))
    kernel = density[(np.arange(lo, hi + 1)[:, None] - index[None, :]) + span]
    shown = (profiles.scaled if scaled is None else scaled)[
        :, lo - profiles.first : hi - profiles.first + 1
    ]
    mass = shown @ kernel
    each = np.log(np.maximum(mass, _TINY)) + profiles.top[:, None]
    if weights is not None:
        each = weights[:, None] * each
    return np.asarray(each.sum(axis=0), dtype=np.float64)


def _log_posterior(
    alpha: Floats,
    log_prior: Floats,
    profiles: _Profiles | None,
    tau: float,
    weights: Floats | None = None,
) -> Floats:
    """The unnormalized log posterior on the ``alpha`` grid: found on every :data:`COARSE`
    th point, then in full only where that is within :data:`WINDOW_LOG` of its top (one coarse
    step wider each side), ``-inf`` elsewhere (``profiles`` ``None``: no rows, the prior)."""
    if profiles is None:
        return log_prior.copy()
    scaled = profiles.scaled
    coarse = np.arange(0, alpha.size, COARSE)
    if coarse[-1] != alpha.size - 1:
        coarse = np.append(coarse, alpha.size - 1)
    rough = log_prior[coarse] + _log_likelihood(
        coarse, alpha, profiles, tau, scaled, weights=weights
    )
    kept = coarse[rough >= rough.max() - WINDOW_LOG]
    window = np.arange(
        max(0, int(kept.min()) - COARSE), min(alpha.size, int(kept.max()) + COARSE + 1)
    )
    found = np.full(alpha.size, -np.inf)
    found[window] = log_prior[window] + _log_likelihood(
        window, alpha, profiles, tau, scaled, weights=weights
    )
    return found


def _unnamed_cells(
    clusters: Sequence[_Cluster], weights: Sequence[float] | None = None
) -> tuple[npt.NDArray[np.intp], Floats, Floats]:
    """Every unnamed row of the class, as (offset in grid steps, count, list sensitivity) per
    distinct cell; ``weights``: each market-day's rows count its own (``None``: whole)."""
    found: dict[tuple[int, float], float] = {}
    for j, cluster in enumerate(clusters):
        cells = cluster.unnamed
        for k, n, s in zip(cells.steps.tolist(), cells.counts.tolist(), cells.s.tolist(),
                           strict=True):  # fmt: skip
            found[(k, s)] = found.get((k, s), 0.0) + (n if weights is None else weights[j] * n)
    keys = sorted(found)
    return (
        np.array([k for k, _ in keys], dtype=np.intp),
        np.array([found[k] for k in keys], dtype=np.float64),
        np.array([s for _, s in keys], dtype=np.float64),
    )


def _posterior(  # noqa: PLR0913 - the grid, the prior, the rows and the ramp's keywords
    alpha: Floats,
    log_prior: Floats,
    profiles: _Profiles,
    settings: AnchorSettings,
    market_days: int,
    *,
    weights: Floats | None = None,
    tau_free: bool = True,
) -> tuple[float, Floats]:
    """``tau`` and the log posterior of ``alpha`` at it: the registered ``tau``, or, once the
    class has ``tau_free_market_days`` market-days (and ``tau_free``: the ramp holds it
    registered until it is full), the choice with the most marginal likelihood."""
    log = _log_posterior(alpha, log_prior, profiles, settings.tau, weights)
    if not tau_free or market_days < settings.tau_free_market_days:
        return settings.tau, log
    best = (settings.tau, -np.inf, log)
    for choice in settings.tau_choices:
        found = (
            log
            if choice == settings.tau
            else _log_posterior(alpha, log_prior, profiles, choice, weights)
        )
        top = float(found.max())
        evidence = top + float(np.log(np.exp(found - top).sum()))
        if evidence > best[1] + 1e-12:
            best = (choice, evidence, found)
    return best[0], best[2]


def _used(
    rows: Sequence[LiveRow], trials: Mapping[Tier, Trials], settings: AnchorSettings
) -> tuple[list[LiveRow], float, float, bool]:
    """The rows the fit takes (tier A, and tier B only under the tier B rule, Addendum B1.5),
    each tier's list sensitivity, and whether tier B entered."""
    s_a = sensitivity(trials.get("A", Trials()), settings.tier_a_prior)
    found_b = trials.get("B", Trials())
    s_b = sensitivity(found_b, settings.tier_b_prior)
    tier_b = (
        s_b >= settings.tier_b_min
        and found_b.trials >= settings.tier_b_min_trials
        and found_b.dates >= settings.tier_b_min_dates
    )
    return [row for row in rows if row.tier == "A" or tier_b], s_a, s_b, tier_b


def fit_class(  # noqa: PLR0913 - the class, its rows, their lookups and the ramp's keywords
    key: str,
    rows: Sequence[LiveRow],
    offset_of: Callable[[str], float],
    trials: Mapping[Tier, Trials],
    settings: AnchorSettings,
    *,
    weights: Mapping[date, float] | None = None,
    delay_weights: Mapping[date, float] | None = None,
    tau_free: bool = True,
) -> ClassFit:
    """The class's posterior from its live rows (none: the prior alone).

    The ramp's keywords (:func:`ramped`); with the two maps ``None`` and ``tau_free`` true
    this is the fit as built, bit for bit. ``weights``: a school day to its storm's weight;
    each market-day's log marginal likelihood is multiplied by its day's (a day not in the
    map weighs 1). ``delay_weights``: the same for the delay share's likelihood: each
    market-day's delayed rows and unnamed cells count their day's weight there (the rows'
    part in ``alpha``'s likelihood is under ``weights``, like every row). ``tau_free`` false:
    ``tau`` is the registered one and no choice is tried."""
    prior = settings.priors[key]
    used, s_a, s_b, tier_b = _used(rows, trials, settings)
    s_of = {"A": s_a, "B": s_b}
    closed = sum(1 for row in used if row.label == "no_school")
    delayed = sum(1 for row in used if row.label == "delayed")
    unnamed = len(used) - closed - delayed
    nodes = _nodes(settings.nodes)
    lo, hi, count = settings.grid
    alpha = np.linspace(lo, hi, count)
    step = float(alpha[1] - alpha[0])
    clusters = _clusters(used, offset_of, s_of, step)
    reach = int(np.ceil(KERNEL_SD * max(settings.tau, *settings.tau_choices) / step))
    log_prior = -0.5 * ((alpha - prior.alpha_mean) / prior.alpha_sd) ** 2

    def of_days(weight: Mapping[date, float] | None) -> list[float] | None:
        if weight is None:
            return None
        return [1.0 if c.day is None else weight.get(c.day, 1.0) for c in clusters]

    lam = of_days(weights)
    mu = of_days(delay_weights)
    weighted = None if lam is None else np.array(lam, dtype=np.float64)
    hidden = _unnamed_cells(clusters, mu)
    late: float = (
        delayed
        if mu is None
        else float(
            sum(m * float(c.delayed.counts.sum()) for m, c in zip(mu, clusters, strict=True))
        )
    )

    def delay_at(at: float, tau: float) -> float:
        steps, counts, s = hidden
        p = sigmoid(at + step * steps[:, None] + np.sqrt(2.0) * tau * nodes[0][None, :]) @ nodes[1]
        return _delay(settings.delay_prior, settings.delay_grid, late, (counts, s, p))

    q = delay_at(prior.alpha_mean, settings.tau)
    tau, log = settings.tau, log_prior.copy()
    for _ in range(DELAY_ROUNDS if clusters else 0):
        tau, log = _posterior(alpha, log_prior, _profiles(alpha, clusters, q, reach), settings,
                              len(clusters), weights=weighted, tau_free=tau_free)  # fmt: skip
        weight = np.exp(log - log.max())
        moved = delay_at(float(weight @ alpha) / float(weight.sum()), tau)
        if abs(moved - q) < DELAY_TOL:
            break
        q = moved
    weight = np.exp(log - log.max())
    weight /= weight.sum()
    cdf = np.cumsum(weight)
    band = (
        float(alpha[min(int(np.searchsorted(cdf, 0.1)), count - 1)]),
        float(alpha[min(int(np.searchsorted(cdf, 0.9)), count - 1)]),
    )
    sizes = np.array([c.size for c in clusters])
    return ClassFit(
        key=key,
        prior=prior,
        alpha=float((weight * alpha).sum()),
        alpha_band=band,
        q=q,
        tau=tau,
        s_a=s_a,
        s_b=s_b,
        tier_b=tier_b,
        rows=len(used),
        closed=closed,
        delayed=delayed,
        unnamed=unnamed,
        market_days=len(clusters),
        dates=len({row.day for row in used}),
        k_eff=float(sizes.sum() ** 2 / (sizes**2).sum()) if sizes.size else 0.0,
        nodes=nodes,
        multi_list=sum(1 for row in used if row.label == "unnamed" and row.lists > 1),
        predictive=float(
            weight @ (sigmoid(alpha[:, None] + np.sqrt(2.0) * tau * nodes[0][None, :]) @ nodes[1])
        ),
    )


# --- the ramp: storms, the cap and the weight ----------------------------------------------------


def weekday_index(day: date) -> int:
    """The weekdays counted up to ``day``: a Friday and the next Monday differ by 1 (a
    Saturday or Sunday counts as its Friday; ordinal 1 is a Monday)."""
    ordinal = day.toordinal() - 1
    return 5 * (ordinal // 7) + min(ordinal % 7, 4)


def storms_of(days: Iterable[date], gap: int) -> dict[date, date]:
    """Each day's storm, named by its first day: a run of the days with at most ``gap``
    weekdays between two of them. With the registered gap of 1, Monday and Wednesday are one
    storm (a morning the record lost, or one taken back, does not split it) and so are Friday
    and Tuesday; Monday and Thursday are two. A weekday with no school counts as a day
    between, so no storm runs across a break."""
    found: dict[date, date] = {}
    first: date | None = None
    last: date | None = None
    for day in sorted(set(days)):
        if first is None or last is None or weekday_index(day) - weekday_index(last) > 1 + gap:
            first = day
        found[day] = first
        last = day
    return found


def storm_weights(sizes: Mapping[date, float], start: float, cap: float) -> dict[date, float]:
    """Each storm's weight in (0, 1], the largest for which no storm holds more than ``cap``
    of the whole, the start counted in: ``weight_s x_s <= cap (start + sum_e weight_e x_e)``.

    The storms over their share end level with each other (the ``m`` largest, at ``T_m = cap
    U_m / (1 - m cap)``, ``U_m`` the start and every other storm); every other storm keeps 1,
    and so does a storm of size 0. Because the start is counted, the cap is met from the first
    storm on, and it never lowers an earlier storm's size when a storm is added."""
    order = sorted(sizes, key=lambda storm: (-sizes[storm], storm))
    values = [sizes[storm] for storm in order]
    found = dict.fromkeys(order, 1.0)
    most = min(math.ceil(1 / cap) - 1, len(order))
    for m in range(most + 1):
        left = 1 - m * cap
        level = cap * (start + sum(values[m:])) / left if left > 0 else math.inf
        if m == most or values[m] <= level:
            for storm, value in zip(order[:m], values[:m], strict=True):
                found[storm] = min(1.0, level / value) if value > 0 else 1.0
            break
    return found


@dataclass(frozen=True, slots=True)
class Storms:
    """A class's storms and what each may count for (:func:`storm_table`): from the used
    rows' days, markets and counts alone (the delay share's from the rows not labeled closed);
    no chance is read."""

    of: Mapping[date, date]
    """Each of the class's dates to its storm (its first date)."""
    information: Mapping[date, float]
    """Each storm's information about ``alpha``, in whole market-days (``I_s``)."""
    open_rows: Mapping[date, float]
    """Each storm's rows not labeled closed (``O_s``)."""
    weight: Mapping[date, float]
    """Each storm's weight in the level's likelihood (``lambda``)."""
    delay_weight: Mapping[date, float]
    """Each storm's weight in the delay share's likelihood (``mu``)."""
    start: float
    """What the start counts for in the level (``I_0 = (tau / alpha_sd)^2``)."""
    delay_start: float
    """What the start counts for in the delay share, in rows (the sum of ``delay_beta``)."""
    market_days: float
    """Every used market-day's information, summed (not weighted)."""

    @property
    def counted(self) -> float:
        """The storms, each counted as ``min(1, its information after the cap)``."""
        return float(
            sum(min(1.0, self.weight[storm] * info) for storm, info in self.information.items())
        )

    def by_day(self, weight: Mapping[date, float]) -> dict[date, float] | None:
        """A storm weight per school day, or ``None`` where every storm weighs 1."""
        if all(value >= 1 for value in weight.values()):
            return None
        return {day: weight[storm] for day, storm in self.of.items()}


def row_information(alpha: float, settings: AnchorSettings) -> float:
    """``c``: a market-day of ``n`` rows counts ``n / (n + c)`` whole market-days of
    information about ``alpha``. A lone row counts exactly its Fisher information at the
    level of ``alpha`` (``I_1 = tau^2 L'(alpha)^2 / (L (1 - L))``, ``L`` the marginal level
    over the market-day effect), and a market-day of endless rows fixes ``alpha`` only to the
    day's own spread: one whole market-day."""
    z, w = _nodes(settings.nodes)
    s = sigmoid(alpha + np.sqrt(2.0) * settings.tau * z)
    level = float(s @ w)
    slope = float((s * (1 - s)) @ w)
    one = settings.tau**2 * slope**2 / (level * (1 - level))
    return 1.0 / one - 1.0


def storm_table(
    key: str, used: Sequence[LiveRow], settings: AnchorSettings, start_alpha: float
) -> Storms:
    """The class's storms from its used rows, with both sets of weights under the class's
    registered share (``start_alpha``: the no-row fit's ``alpha``)."""
    c = row_information(start_alpha, settings)
    sizes = Counter(row.market_day for row in used)
    closed = Counter(row.market_day for row in used if row.label == "no_school")
    of = storms_of({day for day, _ in sizes}, settings.storm_gap)
    information = dict.fromkeys(dict.fromkeys(of.values()), 0.0)
    open_rows = dict.fromkeys(information, 0.0)
    total = 0.0
    for market_day, n in sorted(sizes.items()):
        storm = of[market_day[0]]
        each = n / (n + c)
        information[storm] += each
        open_rows[storm] += n - closed.get(market_day, 0)
        total += each
    cap = settings.date_cap[key]
    start = (settings.tau / settings.priors[key].alpha_sd) ** 2
    delay_start = float(sum(settings.delay_prior))
    return Storms(
        of=of,
        information=information,
        open_rows=open_rows,
        weight=storm_weights(information, start, cap),
        delay_weight=storm_weights(open_rows, delay_start, cap),
        start=start,
        delay_start=delay_start,
        market_days=total,
    )


def _told(found: ClassFit) -> Told:
    return Told(
        level=float(found.level(0.0)),
        band=found.band,
        alpha=found.alpha,
        q=found.q,
        tau=found.tau,
        predictive=found.predictive,
    )


def ramp_weight(rows: int, table: Storms, full: RampFull) -> tuple[float, Bound]:
    """``w = min(1, rows / R, storms / D, market_days / K)`` (the last only where the class
    registers ``market_days``) and the count that binds it (ties: rows, then storms, then
    market-days; ``full`` at 1). While the newest date's rows are the only change to the used
    rows none of the three counts can fall, so neither does ``w``."""
    parts: dict[Bound, float] = {"rows": rows / full.rows, "storms": table.counted / full.storms}
    if full.market_days is not None:
        parts["market_days"] = table.market_days / full.market_days
    bound = min(parts, key=lambda name: parts[name])
    if parts[bound] >= 1:
        return 1.0, "full"
    return parts[bound], bound


def ramped(
    key: str,
    rows: Sequence[LiveRow],
    offset_of: Callable[[str], float],
    trials: Mapping[Tier, Trials],
    settings: AnchorSettings,
) -> ClassFit:
    """The class's served fit under ``live_update.ramp`` ``"capped_storms"`` (the module
    docstring's ramp): the tempered posterior, part of the way from the no-row fit.

    With no used row it is the no-row fit itself, bit for bit the fit as built. With ``0 < w <
    1`` its ``alpha``, both ends of its band and its delay share are ``start + w (raw -
    start)`` at the registered ``tau``. At ``w`` 1 it is the tempered posterior itself, with
    ``tau`` chosen as built. The counts (``rows``, ``closed``, ``market_days``, ``dates``...)
    are the used rows', as built, and ``predictive`` is the tempered posterior's (not served).
    The fit as built is made after the served one for the log line and the private report
    only (:attr:`Ramp.built`): if it raises, the served fit is untouched and the error's type
    is kept (:attr:`Ramp.built_error`)."""
    known: dict[str, float] = {}

    def offset(district: str) -> float:
        # the served fit and the fit as built place the same rows: each offset is found once
        found = known.get(district)
        if found is None:
            found = known[district] = offset_of(district)
        return found

    start = fit_class(key, [], offset, trials, settings)
    used = _used(rows, trials, settings)[0]
    full = settings.ramps[key]
    cap = settings.date_cap[key]
    told = _told(start)
    if not used:
        return replace(
            start,
            ramp=Ramp(
                w=0.0, bound="none", rows=0, storms=0.0, market_days=0.0, full=full,
                gap=settings.storm_gap, cap=cap, storm_count=0, start=told, raw=told, built=told,
            ),
        )  # fmt: skip
    table = storm_table(key, used, settings, start.alpha)
    w, bound = ramp_weight(len(used), table, full)
    weights = table.by_day(table.weight)
    delay_weights = table.by_day(table.delay_weight)
    raw = fit_class(
        key, rows, offset, trials, settings,
        weights=weights, delay_weights=delay_weights, tau_free=w >= 1,
    )  # fmt: skip
    served = raw
    if w < 1:
        low, high = start.alpha_band
        served = replace(
            raw,
            alpha=start.alpha + w * (raw.alpha - start.alpha),
            alpha_band=(
                low + w * (raw.alpha_band[0] - low),
                high + w * (raw.alpha_band[1] - high),
            ),
            q=start.q + w * (raw.q - start.q),
        )
    built: Told | None = _told(raw)
    error: str | None = None
    whole = weights is None and delay_weights is None
    if not (whole and (w >= 1 or raw.market_days < settings.tau_free_market_days)):
        # the fit as built is another fit (a weight under 1, or a tau as built would choose)
        try:
            built = _told(fit_class(key, rows, offset, trials, settings))
        except Exception as raised:  # for the line only: it never stops a run
            built, error = None, type(raised).__name__
    dates: dict[date, list[date]] = {}
    for day, storm in table.of.items():
        dates.setdefault(storm, []).append(day)
    whole_level = table.start + sum(table.information.values())
    whole_delay = table.delay_start + sum(table.open_rows.values())
    tempered = tuple(
        Tempered(
            storm=storm,
            dates=tuple(sorted(dates[storm])),
            share=table.information[storm] / whole_level,
            weight=table.weight[storm],
            delay_share=table.open_rows[storm] / whole_delay,
            delay_weight=table.delay_weight[storm],
        )
        for storm in sorted(table.information)
        if table.weight[storm] < 1 or table.delay_weight[storm] < 1
    )
    return replace(
        served,
        ramp=Ramp(
            w=w, bound=bound, rows=len(used), storms=table.counted,
            market_days=table.market_days, full=full, gap=settings.storm_gap, cap=cap,
            storm_count=len(table.information), start=told, raw=_told(raw), built=built,
            built_error=error, tempered=tempered,
        ),
    )  # fmt: skip


# --- a unit's standing -------------------------------------------------------------------------


def exposure_x(f: float, f_ref: float, offset: float) -> float:
    """``x = -ln((f + offset) / (f_ref + offset))``: above 0 for a unit with fewer of the
    class's days than the reference, below 0 for one with more."""
    return float(-np.log((f + offset) / (f_ref + offset)))


DELTA_CLASSES: Final = ("advisory",)
"""The classes an archive region delta may enter (the spec's G7: today only the advisory
Northeast qualifies). The warning class's region shares sit at the archive's ceiling (Ohio
Valley 106 of 107 closed against 1,027 of 1,071 nationally), where a log odds ratio rests on one
or two open days and on how the storm-day lists were picked; warning and cold take none."""


def region_delta(region: Tally | None, nation: Tally, settings: AnchorSettings) -> float:
    """The half-strength archive delta of a region, where its archive record of the class has
    level support (:func:`snowlight.predict.pool.level_supported`), else 0:
    ``strength * clip(log OR(region vs nation), -clip, clip)``."""
    if region is None or not level_supported(region.n, region.dates, region.busiest):
        return 0.0
    half = 0.5

    def log_odds(t: Tally) -> float:
        return float(np.log((t.y + half) / (t.n - t.y + half)))

    ratio = log_odds(region) - log_odds(nation)
    return settings.delta_strength * float(
        np.clip(ratio, -settings.delta_clip, settings.delta_clip)
    )


def said_standing(claimed: npt.NDArray[np.int8], p: Floats, level: Floats) -> npt.NDArray[np.int8]:
    """The standing a unit's sentence says: its exposure's (``claimed``), only where its served
    chance is on that side of its class's level by a published point ("more" of the class's
    alerts: under it; "fewer": over it), so "so it closes on a smaller share of them" is true of
    the number shown; else usual."""
    shown = np.round(p * 100)
    usual = np.round(level * 100)[None, :]
    more = (claimed == STANDINGS.index("more")) & (shown < usual)
    fewer = (claimed == STANDINGS.index("fewer")) & (shown > usual)
    return np.where(
        more, STANDINGS.index("more"), np.where(fewer, STANDINGS.index("fewer"), 0)
    ).astype(np.int8)


@dataclass(frozen=True, slots=True)
class Unit:
    """A unit the anchor gives chances: a district (its LEAID) or a private school."""

    leaid: str | None
    county: str | None
    region: str | None


@dataclass(frozen=True, slots=True)
class Pull:
    """What the plausibility pull did (G6, Addendum A item 5)."""

    pulled: int
    """Units moved toward their class level (``s`` under 1)."""
    capped: int
    """Units the class level itself leaves over ``district_max`` (its own exposure already puts
    them under it): every class's log-odds lowered by one shift to ``district_max``."""
    rounds: int
    """National rounds the largest-first steps took."""
    failing: tuple[str, ...]
    """National clauses still failing after the pull (empty: it passes)."""
    over: int
    """Units still over ``district_max`` (0 after the cap)."""


@dataclass(frozen=True, slots=True)
class Plausible:
    """What G6 (Addendum A item 5) found and did before anything serves."""

    before: Mapping[str, float]
    """The national implied closures with no pull, as they would publish
    (:func:`implied_summary`)."""
    after: Mapping[str, float]
    """... as published and served."""
    pull: Pull
    shrunk: Mapping[str, float]
    """A class whose level the national clauses refused, to the weight its live posterior keeps
    (``alpha = prior + w (posterior - prior)``, ``w`` falling from 1 in the pull's steps until
    they pass); empty: none."""
    levels: Mapping[str, float]
    """Each class's served level at the reference district (after any shrink)."""

    @property
    def passes(self) -> bool:
        """Every clause holds as served."""
        return not self.pull.failing and not self.pull.over

    @property
    def quiet(self) -> bool:
        """Nothing beyond the registered pull toward the class level was needed."""
        return self.passes and not self.pull.capped and not self.shrunk

    def summary(self) -> dict[str, object]:
        """The private report's numbers (``anchor.json``)."""
        return {
            "passes": self.passes,
            "before": dict(self.before),
            "after": dict(self.after),
            "pulled": self.pull.pulled,
            "capped": self.pull.capped,
            "rounds": self.pull.rounds,
            "failing": list(self.pull.failing),
            "over": self.pull.over,
            "shrunk": dict(self.shrunk),
            "levels": {k: round(v, 4) for k, v in self.levels.items()},
        }

    def line(self) -> str:
        """One log line: the national figures as published, the districts pulled and capped,
        and the classes shrunk (the cap and the shrink are the G6 backstop, acting only when a
        published chance would break G6)."""
        after = self.after
        said = (
            f"anchor plausibility: advisory mean {after.get('advisory_mean', 0):.2f} p99 "
            f"{after.get('advisory_p99', 0):.2f}, advisory and warning mean "
            f"{after.get('advisory_warning_mean', 0):.2f}, most {after.get('district_max', 0):.2f}"
            f"; pulled {self.pull.pulled}, capped {self.pull.capped}, shrunk {len(self.shrunk)}"
        )
        if self.shrunk:
            said += "; shrunk toward the prior: " + ", ".join(
                f"{k} to {w:.2f} of its posterior ({self.levels[k]:.3f})"
                for k, w in self.shrunk.items()
            )
        if not self.passes:
            said += f"; FAILS {', '.join(self.pull.failing) or 'district_max'}"
        return said


@dataclass(frozen=True, slots=True)
class UnitRates:
    """Each unit's chance of no school per class as published, the class's delay share, each
    unit's standing, and what the plausibility check did on the published chances."""

    p: Floats
    """(units, classes) in :data:`CLASSES` order, as published (on the grid it was asked
    for)."""
    q: tuple[float, ...]
    standing: npt.NDArray[np.int8]
    """(units, classes): the index in :data:`STANDINGS`, said only where the served chance is
    on its side of the class level by a published point."""
    plausible: Plausible


@dataclass(frozen=True, slots=True)
class Anchor:
    """The fitted classes and what each unit's chance is made from."""

    settings: AnchorSettings
    exposure: Exposure
    fits: Mapping[str, ClassFit]
    deltas: Mapping[str, Mapping[str, float]]
    """Class to region to its delta (only regions with level support are listed)."""
    labels: LiveLabels
    climate: Climate | None = None
    """The forecast climate the forecast adjustment is calibrated on (advisory-sane L5,
    :mod:`snowlight.predict.forecast_adjust`); ``None``: no adjustment, the class level alone."""
    adjust: AdjustSettings | None = None
    """The registered adjustment (``live_score.forecast_adjustment``), with ``climate``."""

    def class_of(self, situation: str) -> str | None:
        """The class a situation is served in, or ``None`` (the chain)."""
        found = self.settings.class_of.get(situation, CHAIN)
        return None if found == CHAIN else found

    def offsets(
        self, unit: Unit
    ) -> tuple[tuple[float, ...], tuple[int, ...], tuple[float, ...] | None]:
        """A unit's offset ``delta + beta * x`` per class, its standing index per class and its
        days a winter per class (``None``: not known)."""
        days, borrowed = self.exposure.of(unit.leaid, unit.county)
        offsets: list[float] = []
        standing: list[int] = []
        for i, klass in enumerate(CLASSES):
            delta = self.deltas.get(klass, {}).get(unit.region or "", 0.0)
            if days is None:
                offsets.append(delta)
                standing.append(0)
                continue
            x = exposure_x(days[i], self.exposure.f_ref[klass], self.settings.offset)
            moved = self.settings.beta * x
            offsets.append(delta + moved)
            standing.append(
                0
                if borrowed or abs(moved) <= STANDING_ODDS
                else STANDINGS.index("more" if moved < 0 else "fewer")
            )
        return tuple(offsets), tuple(standing), days

    def rates(
        self,
        units: Sequence[Unit],
        *,
        pull: npt.NDArray[np.bool_] | None = None,
        grid: Grid | None = PUBLISHED,
    ) -> UnitRates:
        """Every unit's chance per class as published on ``grid`` (``None``: raw), plausible
        (G6) as published before it serves: every clause is judged on the published chances.

        The pull (:func:`plausibility_pull`) holds every unit with known days to
        ``district_max`` and the ``pull`` units (default: every unit with known days; serving
        passes the deployed districts) to the national clauses. Where the national clauses
        still fail with every movable unit at its class level, the class level itself is not
        plausible: the classes the failing clauses name (advisory; with the advisory and
        warning clause, warning too) are shrunk toward their priors (``alpha = prior +
        w (posterior - prior)``, ``w`` from 1 down in the pull's steps) until they pass; the
        priors pass by construction. Addendum A item 4's fallback is the same move."""
        count = len(units)
        offsets = np.zeros((count, len(CLASSES)))
        claimed = np.zeros((count, len(CLASSES)), dtype=np.int8)
        days = np.zeros((count, len(CLASSES)))
        known = np.zeros(count, dtype=np.bool_)
        for i, unit in enumerate(units):
            found, stands, f = self.offsets(unit)
            offsets[i] = found
            claimed[i] = stands
            if f is not None:
                days[i] = f
                known[i] = True
        mask = known if pull is None else (known & pull)
        rules = self.settings.plausibility

        def at(weight: Mapping[str, float]) -> tuple[Floats, Floats]:
            p = np.zeros((count, len(CLASSES)))
            level = np.zeros(len(CLASSES))
            for j, klass in enumerate(CLASSES):
                fit = self.fits[klass]
                w = weight.get(klass, 1.0)
                alpha = fit.prior.alpha_mean + w * (fit.alpha - fit.prior.alpha_mean)
                unique, inverse = np.unique(offsets[:, j], return_inverse=True)
                p[:, j] = fit.level(unique, alpha)[inverse]
                level[j] = float(fit.level(0.0, alpha))
            return p, level

        p, level = at({})
        before = implied_summary(p if grid is None else grid.round(p), days, mask)
        result = plausibility_pull(p, level, days, known, mask, rules, grid)
        shrunk: dict[str, float] = {}
        if result.failing:
            named = (
                ("advisory", "warning")
                if "advisory_warning_mean" in result.failing
                else ("advisory",)
            )
            for k in range(1, round(1.0 / rules.step) + 1):
                w = max(0.0, round(1.0 - k * rules.step, 10))
                shrunk = dict.fromkeys(named, w)
                p, level = at(shrunk)
                result = plausibility_pull(p, level, days, known, mask, rules, grid)
                if not result.failing:
                    break
        return UnitRates(
            p=p,
            q=tuple(self.fits[k].q for k in CLASSES),
            standing=said_standing(claimed, p, level),
            plausible=Plausible(
                before=before,
                after=implied_summary(p, days, mask),
                pull=result,
                shrunk=shrunk,
                levels={k: float(level[j]) for j, k in enumerate(CLASSES)},
            ),
        )

    def summary(self) -> dict[str, object]:
        """The private report (``anchor.json``)."""
        return {
            "classes": {k: fit.summary() for k, fit in self.fits.items()},
            "deltas": {k: dict(v) for k, v in self.deltas.items()},
            "f_ref": dict(self.exposure.f_ref),
            "ramp": self.settings.ramp,
            "left_out": self.labels.left_out.summary(),
            "labels": {
                "found": self.labels.found,
                "days": self.labels.days,
                "rows": len(self.labels.rows),
                "through": max(r.day for r in self.labels.rows).isoformat()
                if self.labels.rows
                else None,
            },
        }


def implied_closures(p: Floats, days: Floats) -> tuple[Floats, Floats, Floats]:
    """Per unit, implied closures a winter: advisory, advisory and warning, every class."""
    advisory = CLASSES.index("advisory")
    warning = CLASSES.index("warning")
    each = p * days
    return each[:, advisory], each[:, advisory] + each[:, warning], each.sum(axis=1)


_EPS: Final = 1e-12
CLAUSES: Final = ("advisory_mean", "advisory_p99", "advisory_warning_mean")
"""The national clauses of G6, in the order they are checked."""


def failing(
    p: Floats, days: Floats, mask: npt.NDArray[np.bool_], rules: Plausibility
) -> tuple[str, ...]:
    """The national clauses (:data:`CLAUSES`) the ``mask`` units fail."""
    if not mask.any():
        return ()
    advisory, both, _ = implied_closures(p[mask], days[mask])
    found = (
        float(advisory.mean()) > rules.advisory_mean + _EPS,
        float(np.quantile(advisory, 0.99)) > rules.advisory_p99 + _EPS,
        float(both.mean()) > rules.advisory_warning_mean + _EPS,
    )
    return tuple(name for name, fails in zip(CLAUSES, found, strict=True) if fails)


def implied_summary(p: Floats, days: Floats, mask: npt.NDArray[np.bool_]) -> dict[str, float]:
    """The national implied closures a winter of the ``mask`` units (advisory mean and p99,
    advisory and warning mean, the most of any unit) and each class's chance averaged over its
    days (``<class>_day``: the chance on the average day of the class, ``sum f p / sum f``)."""
    if not mask.any():
        return {}
    advisory, both, total = implied_closures(p[mask], days[mask])
    found = {
        "advisory_mean": round(float(advisory.mean()), 4),
        "advisory_p99": round(float(np.quantile(advisory, 0.99)), 4),
        "advisory_warning_mean": round(float(both.mean()), 4),
        "district_max": round(float(total.max()), 4),
    }
    for j, klass in enumerate(CLASSES):
        weight = float(days[mask, j].sum())
        if weight > 0:
            found[f"{klass}_day"] = round(float((p[mask, j] * days[mask, j]).sum()) / weight, 4)
    return found


def _cap(p: Floats, days: Floats, limit: float) -> Floats:
    """``p`` with each row's log-odds lowered by the least one shift that brings its implied
    closures to ``limit`` (bisection; the closures fall as the shift grows)."""
    low = np.zeros(p.shape[0])
    high = np.full(p.shape[0], 40.0)
    odds = logit(p)
    for _ in range(60):
        middle = (low + high) / 2
        fits = (sigmoid(odds - middle[:, None]) * days).sum(axis=1) <= limit
        high = np.where(fits, middle, high)
        low = np.where(fits, low, middle)
    return sigmoid(odds - high[:, None])


def settle(
    p: Floats, days: Floats, guard: npt.NDArray[np.bool_], limit: float, grid: Grid | None
) -> Floats:
    """``p`` as published on ``grid`` (``None``: raw, unchanged), each ``guard`` unit still
    held to ``limit`` implied closures: a unit rounding puts over it takes, class by class
    from the one rounding raised most, the hundredth at or under its raw chance instead, so
    its published closures are at most its raw ones (the floor aside)."""
    if grid is None:
        return p.copy()
    published = grid.round(p)
    over = guard & ((published * days).sum(axis=1) > limit)
    if not over.any():
        return published
    lowered = grid.down(p)
    order = np.argsort(-(published - p), axis=1, kind="stable")
    for rank in range(p.shape[1]):
        still = np.flatnonzero(over)
        if not still.size:
            break
        column = order[still, rank]
        published[still, column] = lowered[still, column]
        over = guard & ((published * days).sum(axis=1) > limit)
    return published


def _national_step(  # noqa: PLR0913, PLR0917 - the chances, days, whom, rules, the pull
    p: Floats,
    days: Floats,
    mask: npt.NDArray[np.bool_],
    capped: npt.NDArray[np.bool_],
    rules: Plausibility,
    pulled: tuple[Floats, Floats, Floats],
    published: Callable[[Floats], Floats],
) -> bool:
    """One national round, in place: the ``mask`` units (not the ``capped``) with the most
    implied closures take one step each toward their level until the clauses pass (bisection
    over how many; a step must lower a unit's closures and add none of advisory, or of
    advisory and warning).
    ``pulled``: the levels' log-odds, each unit's own offset from them and its ``s``;
    ``published``: the chances as served (:func:`settle`), which the clauses are judged on.
    Returns whether any unit stepped."""
    base, own, scale = pulled
    lower = np.maximum(np.round(scale - rules.step, 10), 0.0)
    stepped = sigmoid(base + lower[:, None] * own)
    now_a, now_b, now_t = implied_closures(p, days)
    new_a, new_b, new_t = implied_closures(stepped, days)
    order = np.flatnonzero(
        mask
        & ~capped
        & (scale > 0)
        & (new_t < now_t - _EPS)
        & (new_a <= now_a + _EPS)
        & (new_b <= now_b + _EPS)
    )
    if not order.size:
        return False
    order = order[np.argsort(-now_t[order], kind="stable")]

    def fails_with_first(k: int) -> bool:
        moved = p.copy()
        moved[order[:k]] = stepped[order[:k]]
        return bool(failing(published(moved), days, mask, rules))

    take = order.size
    if not fails_with_first(order.size):
        low, high = 0, order.size  # failing with the first low, passing with the first high
        while high - low > 1:
            middle = (low + high) // 2
            if fails_with_first(middle):
                low = middle
            else:
                high = middle
        take = high
    chosen = order[:take]
    p[chosen] = stepped[chosen]
    scale[chosen] = lower[chosen]
    return True


def plausibility_pull(  # noqa: PLR0913, PLR0917 - the chances, levels, days, whom, rules
    p: Floats,
    level: Floats,
    days: Floats,
    guard: npt.NDArray[np.bool_],
    mask: npt.NDArray[np.bool_],
    rules: Plausibility,
    grid: Grid | None = None,
) -> Pull:
    """Pull, in place, the chances ``p`` (units, classes) until G6 holds as published on
    ``grid`` (``None``: on the raw chances); ``p`` ends as published.

    1. The registered pull: each ``guard`` unit over ``district_max`` implied closures is
       pulled toward its class levels (``served = level + s (own - level)`` on the log-odds
       scale, ``s`` from 1 down in steps, never below 0) to the largest ``s`` that passes.
    2. The cap (kept by the lead's ruling of Oct 31 as the G6 backstop on published chances,
       with the class shrink of :meth:`Anchor.rates`; both act only when a published value
       would break G6): a unit no ``s`` brings to
       ``district_max`` (its exposure already puts it under its class level, so pulling it
       toward the level adds closures) takes the ``s`` with the fewest closures, then one
       downward shift of every class's log-odds, the least that brings it to ``district_max``.
    3. The registered national steps, over the ``mask`` units: while a national clause fails,
       the units with the most implied closures take one more step each toward their level, in
       that order, until it passes (a step that would add advisory, or advisory and warning,
       closures is not taken; a capped unit takes none). Each round finds how many must step
       by bisection, which the order makes exact (every clause only eases as more step), and
       there are at most ``1 / step`` rounds.

    4. The chances are published on ``grid`` (:func:`settle`): a ``guard`` unit rounding
       would put over ``district_max`` takes the hundredth under its raw chance instead, and
       the national clauses of steps 3 are judged on the published chances throughout.

    A national clause the class levels themselves fail is left to the caller
    (:meth:`Anchor.rates` shrinks the class toward its prior)."""
    base = logit(level)[None, :]
    own = logit(p) - base
    step = rules.step
    count = round(1.0 / step)
    steps = np.array([round(1.0 - k * step, 10) for k in range(count + 1)])
    scale = np.ones(p.shape[0])
    capped = np.zeros(p.shape[0], dtype=np.bool_)
    limit = rules.district_max + _EPS
    total = (p * days).sum(axis=1)
    over = np.flatnonzero(guard & (total > limit))
    if over.size:
        tried = sigmoid(base[:, None, :] + steps[None, :, None] * own[over][:, None, :])
        implied = (tried * days[over][:, None, :]).sum(axis=2)
        passing = implied <= limit
        reached = passing.any(axis=1)
        # steps run from 1 down: the first passing is the largest s; with none, the fewest
        # closures (the largest s of a tie)
        best = np.where(reached, passing.argmax(axis=1), implied.argmin(axis=1))
        p[over] = tried[np.arange(over.size), best]
        scale[over] = steps[best]
        stuck = over[~reached]
        if stuck.size:
            p[stuck] = _cap(p[stuck], days[stuck], rules.district_max)
            capped[stuck] = True

    def published(chances: Floats) -> Floats:
        return settle(chances, days, guard, limit, grid)

    rounds = 0
    while failing(published(p), days, mask, rules) and rounds < count:
        if not _national_step(p, days, mask, capped, rules, (base, own, scale), published):
            break
        rounds += 1
    p[:] = published(p)
    total = (p * days).sum(axis=1)
    return Pull(
        pulled=int((scale < 1).sum()),
        capped=int(capped.sum()),
        rounds=rounds,
        failing=failing(p, days, mask, rules),
        over=int((guard & (total > limit)).sum()),
    )


def fit(
    settings: AnchorSettings,
    exposure: Exposure,
    labels: LiveLabels,
    places: Mapping[str, tuple[str | None, str | None]],
) -> Anchor:
    """The anchor: each class fitted on its live rows (``places``: LEAID to its county and
    region, for each row's offset), ramped from its start (:func:`ramped`) unless
    ``live_update.ramp`` is ``"off"`` (then the fit as built, :func:`fit_class`)."""
    deltas: dict[str, dict[str, float]] = {}
    for klass in CLASSES:
        nation = exposure.nation.get(klass)
        found: dict[str, float] = {}
        if nation is not None and klass in DELTA_CLASSES:
            for region, tally in exposure.regions.get(klass, {}).items():
                delta = region_delta(tally, nation, settings)
                if delta:
                    found[region] = delta
        deltas[klass] = found
    stub = Anchor(settings, exposure, {}, deltas, labels)
    fits: dict[str, ClassFit] = {}
    for j, klass in enumerate(CLASSES):
        rows = [
            row
            for row in labels.rows
            if settings.class_of.get(row.weather) == klass and row.day >= settings.fit_from
        ]

        def offset_of(leaid: str, j: int = j) -> float:
            county, region = places.get(leaid, (None, None))
            return stub.offsets(Unit(leaid, county, region))[0][j]

        fits[klass] = (
            ramped(klass, rows, offset_of, labels.trials, settings)
            if settings.ramp == "capped_storms"
            else fit_class(klass, rows, offset_of, labels.trials, settings)
        )
    return Anchor(settings, exposure, fits, deltas, labels)
