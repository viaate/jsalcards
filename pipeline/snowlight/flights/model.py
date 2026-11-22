"""The flight chances (D6): the model, its fit on history and its held-out test.

Targets, each per airport and local block (:mod:`snowlight.flights.blocks`):

* ``dep_canc``: the chance a departure is cancelled; ``dep_late``: the chance a departure leaves
  45+ minutes late (a share of all scheduled departures, so a cancelled one is not late);
* ``arr_canc`` and ``arr_late``: the same for arrivals at the airport, by scheduled arrival block;
* ``rough``: per airport day, the chance that 10% or more of its departures are cancelled (a day
  counts with :data:`MIN_DAY_FLIGHTS` departures or more).

Each target and lead class (:func:`snowlight.flights.features.lead_class`) has its own weighted
binomial logistic regression (:func:`fit`, plain iteratively reweighted least squares with a small
ridge), on the forecast features of the 00Z NBS runs and the airport's own usual rate for that
block and month (:func:`base_rates`, from the BTS history before the test year, shrunk toward the
national rate for small airports).

The test (:func:`evaluate`) is the newest 12 posted months, never used in fitting or tuning: for
every airport, target and lead, the Brier score per departure (or per day for ``rough``) against
the airport's own usual rate, the expected against the observed count, and the reliability of
the chance in bins. A chance is published only where :func:`passes` holds; elsewhere the files
give the usual rate, marked as such (D6).
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.flights.features import LEADS

type Floats = npt.NDArray[np.float64]

TARGETS: Final = ("dep_canc", "dep_late", "arr_canc", "arr_late", "rough")
BLOCK_TARGETS: Final = TARGETS[:4]
ROUGH_SHARE: Final = 0.10
MIN_DAY_FLIGHTS: Final = 5
SHRINK_FLIGHTS: Final = 300.0
SHRINK_DAYS: Final = 60.0
RIDGE: Final = 1.0
EPS: Final = 1e-6

HUBS: Final = ("ATL", "ORD", "DFW", "DEN", "CLT", "LAX", "LAS", "PHX", "SEA", "MCO")
"""The busiest hubs, whose weather knocks on to everyone (the ``hub_*`` features)."""

FEATURES: Final = (
    "base",
    "snow",
    "snow_before",
    "ice",
    "p_snow",
    "p_zr",
    "thunder",
    "gust",
    "wind",
    "low_vis",
    "low_cig",
    "cold",
    "south_snow",
    "hub_snow",
    "hub_storm",
    "day_snow",
    "day_ice",
    "day_storm",
    "pre_snow",
    "pre_ice",
    "obs_snow",
    "obs_snow_old",
    "obs_frz",
)
"""The model's inputs (:func:`design`): the run's forecast, the usual rate, the hubs, and the
weather that already came before the run (``obs_*``, :func:`snowlight.flights.obs.before_runs`),
so the day after a storm knows the storm."""

AFTER_STORM_HOURS: Final = 6
"""A row is the day after a storm when the 48 hours before its run had this many hours of
falling snow or freezing rain (:func:`after_storm`)."""


def after_storm(snow: float, snow_old: float, frz: float) -> bool:
    """Whether a run came after an observed storm (``obs_snow``, ``obs_snow_old``, ``obs_frz``
    in hours)."""
    return snow + snow_old + frz >= AFTER_STORM_HOURS


def after_storm_expr() -> pl.Expr:
    """:func:`after_storm` over a frame with the observed-before columns."""
    return (
        pl.col("obs_snow").fill_null(0.0)
        + pl.col("obs_snow_old").fill_null(0.0)
        + pl.col("obs_frz").fill_null(0.0)
    ) >= AFTER_STORM_HOURS


SOUTH_LATITUDE: Final = 37.0
"""South of this, snow is rare and the same snow stops more flights (``south_snow``)."""

# --- the gate --------------------------------------------------------------------------------

MIN_EVENTS: Final = 10
"""A block target needs this many events (cancellations, late departures) in the test year."""
MIN_ROUGH_DAYS: Final = 2
"""The rough-day chance needs this many rough days in the test year."""
CALIBRATION: Final = (0.67, 1.5)
"""Expected events over observed in the test year must fall in this range."""
HIGH_CHANCE: Final = 0.20
"""Where the model said this or more in the test year, the share that happened must be at least
half the chance said (:data:`HIGH_FLOOR`)."""
HIGH_FLOOR: Final = 0.5
MIN_BIN_ROWS: Final = 2
"""Each reliability bin of :data:`HIGH_CHANCE` or more with this many block-days (days for the
rough-day chance) must also see at least :data:`HIGH_FLOOR` of the chance it said: the blocks of
one airport and day are one storm, so they are counted as one unit each, not by their flights."""
MIN_TARGET_SKILL: Final = 0.01
"""A target and lead is published anywhere only when its skill out of selection is at least
this: the airports chosen on the even ISO weeks of the test year, scored together on the odd
ones, and the reverse (:func:`confirmed`). Below it no airport's chance is published for that
target and lead, whatever its own score: a skill that does not hold out of selection is luck."""
SINGLE_FLIGHTS: Final = 30
"""A high bin of a single block-day still counts when it has this many flights, and fails when it
saw under :data:`SINGLE_FLOOR` of the chance it said."""
SINGLE_FLOOR: Final = 0.25
HEAVY_SHARE: Final = 0.30
"""A heavy block-day (day, for the rough-day chance): this share or more of its flights
cancelled (late, for the late chances), with :data:`HEAVY_FLIGHTS` flights or more."""
HEAVY_FLIGHTS: Final = 10
UNDER_FACTOR: Final = 1 / 3
"""A heavy block-day is under said when the chance said was under this part of the share that
happened."""
UNDER_RARE: Final = 0.25
"""Under-said heavy block-days must stay rare: at most this share of the heavy ones (and
:data:`UNDER_FREE` is always allowed), else the chance is not published."""
UNDER_FREE: Final = 1
UNDER_SEEN: Final = 1.5
"""The two-sided bin check: a bin of :data:`UNDER_BIN_LOW` or more fails when the share that
happened was over this many times the chance it said (said too low), once it has
:data:`UNDER_ROWS` block-days (days, for the rough-day chance) and :data:`UNDER_EVENTS` events
or more."""
UNDER_BIN_LOW: Final = 0.02
UNDER_ROWS: Final = 5
UNDER_EVENTS: Final = 5
BINS: Final = (0.0, 0.01, 0.02, 0.05, 0.10, 0.20, 0.35, 0.50, 0.75, 1.0001)


def logit(p: Floats) -> Floats:
    """The log odds of chances, kept off 0 and 1."""
    q = np.clip(p, EPS, 1 - EPS)
    return np.asarray(np.log(q / (1 - q)), dtype=np.float64)


def expit(x: Floats) -> Floats:
    """Chances from log odds."""
    return np.asarray(1 / (1 + np.exp(-np.clip(x, -30, 30))), dtype=np.float64)


# --- base rates ------------------------------------------------------------------------------


def base_rates(table: pl.LazyFrame) -> pl.DataFrame:
    """Each airport's usual cancelled and late shares by block and month of year.

    ``table``: a ``dep`` or ``arr`` compact table (codes current) over the base months. Out:
    ``apt``, ``block``, ``moy``, ``canc``, ``late`` (shares), ``n`` (flights behind them).
    """
    by_apt = (
        table.with_columns(pl.col("day").dt.month().cast(pl.Int8).alias("moy"))
        .group_by("apt", "block", "moy")
        .agg(pl.col("n").sum(), pl.col("canc").sum(), pl.col("late").sum())
    )
    national = by_apt.group_by("block", "moy").agg(
        (pl.col("canc").sum() / pl.col("n").sum()).alias("nat_canc"),
        (pl.col("late").sum() / pl.col("n").sum()).alias("nat_late"),
    )
    return (
        by_apt.join(national, on=["block", "moy"])
        .with_columns(
            (
                (pl.col("canc") + SHRINK_FLIGHTS * pl.col("nat_canc"))
                / (pl.col("n") + SHRINK_FLIGHTS)
            ).alias("canc"),
            (
                (pl.col("late") + SHRINK_FLIGHTS * pl.col("nat_late"))
                / (pl.col("n") + SHRINK_FLIGHTS)
            ).alias("late"),
        )
        .select("apt", "block", "moy", "canc", "late", "n")
        .sort("apt", "block", "moy")
        .collect()
    )


def airport_days(dep: pl.LazyFrame) -> pl.LazyFrame:
    """Each airport day's departures and whether it was rough (10%+ cancelled)."""
    return (
        dep.group_by("apt", "day")
        .agg(pl.col("n").sum(), pl.col("canc").sum())
        .filter(pl.col("n") >= MIN_DAY_FLIGHTS)
        .with_columns((pl.col("canc") >= ROUGH_SHARE * pl.col("n")).alias("rough"))
    )


def rough_rates(dep: pl.LazyFrame) -> pl.DataFrame:
    """Each airport's usual share of rough days by month of year (``apt``, ``moy``, ``rough``,
    ``days``)."""
    days = airport_days(dep).with_columns(pl.col("day").dt.month().cast(pl.Int8).alias("moy"))
    by_apt = days.group_by("apt", "moy").agg(
        pl.col("rough").sum().alias("hits"), pl.len().alias("days")
    )
    national = by_apt.group_by("moy").agg(
        (pl.col("hits").sum() / pl.col("days").sum()).alias("nat")
    )
    return (
        by_apt.join(national, on="moy")
        .with_columns(
            ((pl.col("hits") + SHRINK_DAYS * pl.col("nat")) / (pl.col("days") + SHRINK_DAYS)).alias(
                "rough"
            )
        )
        .select("apt", "moy", "rough", "days")
        .sort("apt", "moy")
        .collect()
    )


# --- the design matrix -----------------------------------------------------------------------


def design(frame: pl.DataFrame) -> Floats:
    """The model's inputs (:data:`FEATURES`) for rows of block features with ``base`` (the usual
    chance) and ``lat``."""

    def col(name: str) -> Floats:
        return frame.get_column(name).cast(pl.Float64).fill_null(0.0).to_numpy()

    snow = np.log1p(np.clip(col("snow"), 0, None))
    south = (col("lat") < SOUTH_LATITUDE).astype(np.float64)
    columns = {
        "base": logit(col("base")),
        "snow": snow,
        "snow_before": np.log1p(np.clip(col("snow_before"), 0, None)),
        "ice": np.log1p(20 * np.clip(col("ice") + col("ice_before"), 0, None)),
        "p_snow": col("p_snow"),
        "p_zr": col("p_zr"),
        "thunder": col("thunder"),
        "gust": np.clip(col("gust") - 20, 0, None) / 10,
        "wind": np.clip(col("wind") - 15, 0, None) / 10,
        "low_vis": np.clip(3 - col("vis"), 0, None) / 3,
        "low_cig": np.clip(10 - col("cig"), 0, None) / 10,
        "cold": np.clip(20 - col("tmp"), 0, None) / 20,
        "south_snow": snow * south,
        "hub_snow": np.log1p(np.clip(col("hub_snow"), 0, None)),
        "hub_storm": col("hub_storm"),
        "day_snow": np.log1p(np.clip(col("day_snow"), 0, None)),
        "day_ice": np.log1p(20 * np.clip(col("day_ice"), 0, None)),
        "day_storm": col("day_storm"),
        "pre_snow": np.log1p(np.clip(col("pre_snow"), 0, None)),
        "pre_ice": np.log1p(20 * np.clip(col("pre_ice"), 0, None)),
        "obs_snow": np.log1p(np.clip(col("obs_snow"), 0, None)),
        "obs_snow_old": np.log1p(np.clip(col("obs_snow_old"), 0, None)),
        "obs_frz": np.log1p(np.clip(col("obs_frz"), 0, None)),
    }
    return np.column_stack([columns[name] for name in FEATURES])


# --- fitting ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fitted:
    """One fitted regression: ``p = expit(intercept + ((x - mean) / scale) @ coef)``."""

    intercept: float
    coef: tuple[float, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]

    def predict(self, x: Floats) -> Floats:
        """The chances for a design matrix."""
        z = (x - np.asarray(self.mean)) / np.asarray(self.scale)
        return expit(self.intercept + z @ np.asarray(self.coef))

    def as_json(self) -> dict[str, object]:
        """For the model file."""
        return {
            "intercept": round(self.intercept, 6),
            "coef": [round(c, 6) for c in self.coef],
            "mean": [round(m, 6) for m in self.mean],
            "scale": [round(s, 6) for s in self.scale],
        }

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> "Fitted":
        """Read one regression of the model file."""

        def floats(key: str) -> tuple[float, ...]:
            raw = value[key]
            if not isinstance(raw, list):
                raise TypeError(f"{key} is not a list")
            return tuple(float(v) for v in raw)

        return cls(
            intercept=float(str(value["intercept"])),
            coef=floats("coef"),
            mean=floats("mean"),
            scale=floats("scale"),
        )


def _loss(z: Floats, beta: Floats, y: Floats, weights: Floats, penalty: Floats) -> float:
    eta = np.clip(z @ beta, -30, 30)
    # Weighted binomial deviance per trial, plus the ridge.
    log_like = weights * (y * eta - np.logaddexp(0.0, eta))
    return float(-log_like.sum() + 0.5 * (penalty * beta**2).sum())


def fit(x: Floats, events: Floats, trials: Floats, ridge: float = RIDGE, steps: int = 50) -> Fitted:
    """A weighted binomial logistic regression: ``events`` of ``trials`` per row, by damped Newton
    steps (halved until the loss falls) with a ridge on the standardized coefficients (not the
    intercept)."""
    keep = trials > 0
    x, events, trials = x[keep], events[keep], trials[keep]
    weights = trials / trials.sum()
    mean = (x * weights[:, None]).sum(axis=0)
    spread = np.sqrt(((x - mean) ** 2 * weights[:, None]).sum(axis=0))
    scale = np.where(spread > EPS, spread, 1.0)
    z = np.column_stack([np.ones(len(x)), (x - mean) / scale])
    y = events / trials
    beta = np.zeros(z.shape[1])
    beta[0] = float(logit(np.asarray([max(float(y @ weights), EPS)]))[0])
    penalty = np.full(z.shape[1], ridge / trials.sum())
    penalty[0] = 0.0
    loss = _loss(z, beta, y, weights, penalty)
    for _ in range(steps):
        p = expit(z @ beta)
        w = weights * p * (1 - p)
        gradient = z.T @ (weights * (y - p)) - penalty * beta
        hessian = (z * w[:, None]).T @ z + np.diag(penalty + 1e-12)
        step = np.linalg.solve(hessian, gradient)
        size = 1.0
        trial, trial_loss = beta, loss
        while size > 1e-4:  # noqa: PLR2004 - give up on a step this small
            trial = beta + size * step
            trial_loss = _loss(z, trial, y, weights, penalty)
            if trial_loss <= loss:
                break
            size /= 2
        else:
            break
        moved = float(np.max(np.abs(trial - beta)))
        beta, loss = trial, trial_loss
        if moved < 1e-7:  # noqa: PLR2004 - converged
            break
    return Fitted(
        intercept=float(beta[0]),
        coef=tuple(float(b) for b in beta[1:]),
        mean=tuple(float(m) for m in mean),
        scale=tuple(float(s) for s in scale),
    )


# --- the test --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Score:
    """One airport's (or the pool's) test of one target and lead."""

    units: float
    """Departures (arrivals, days) tested."""
    events: float
    expected: float
    brier: float
    brier_base: float
    high_said: float = 0.0
    """The mean chance where the model said :data:`HIGH_CHANCE` or more."""
    high_seen: float = 0.0
    """The share that happened there."""
    high_units: float = 0.0
    bad_bins: int = 0
    """Bins of :data:`HIGH_CHANCE` or more, with :data:`MIN_BIN_ROWS` rows or more, that saw
    less than :data:`HIGH_FLOOR` of the chance they said (or a single block-day of
    :data:`SINGLE_FLIGHTS` flights or more that saw less than :data:`SINGLE_FLOOR` of it)."""
    under_bins: int = 0
    """Bins of :data:`UNDER_BIN_LOW` or more that saw over :data:`UNDER_SEEN` times the chance
    they said (:data:`UNDER_ROWS` rows and :data:`UNDER_EVENTS` events or more)."""
    heavy: int = 0
    """Heavy block-days (:data:`HEAVY_SHARE`)."""
    under: int = 0
    """Heavy block-days whose chance said was under :data:`UNDER_FACTOR` of what happened."""

    @property
    def under_ok(self) -> bool:
        """Whether under-said heavy block-days stayed rare (:data:`UNDER_RARE`)."""
        return self.under <= max(UNDER_FREE, UNDER_RARE * self.heavy)

    @property
    def skill(self) -> float:
        """How much lower the Brier score is than the usual rate's (1 is perfect, 0 no better)."""
        return 1 - self.brier / self.brier_base if self.brier_base > 0 else 0.0

    @property
    def calibration(self) -> float:
        """Expected events over observed (``inf`` when none happened)."""
        return self.expected / self.events if self.events > 0 else math.inf


def score(  # noqa: PLR0913, PLR0917 - the chances, the usual rates and what happened
    p: Floats,
    base: Floats,
    events: Floats,
    trials: Floats,
    seen: Floats | None = None,
    size: Floats | None = None,
) -> Score:
    """The test of chances ``p`` against the usual ``base`` on rows of ``events`` in ``trials``.

    ``seen`` and ``size``: each row's share that happened and its flights, for the under-said
    count (default ``events / trials`` and ``trials``; the rough-day chance gives the day's
    cancelled share and departures)."""
    if seen is None:
        seen = np.divide(events, trials, out=np.zeros_like(events), where=trials > 0)
    if size is None:
        size = trials
    heavy = (size >= HEAVY_FLIGHTS) & (seen >= HEAVY_SHARE)
    under = heavy & (p < UNDER_FACTOR * seen)
    misses = trials - events
    model = events * (1 - p) ** 2 + misses * p**2
    usual = events * (1 - base) ** 2 + misses * base**2
    units = float(trials.sum())
    high = p >= HIGH_CHANCE
    high_units = float(trials[high].sum())
    bad_bins = 0
    under_bins = len(under_said(p, events, trials))
    for low, top in pairwise(BINS):
        if low < HIGH_CHANCE:
            continue
        inside = (p >= low) & (p < top)
        units_in = float(trials[inside].sum())
        rows_in = int(inside.sum())
        if units_in <= 0 or rows_in == 0:
            continue
        said = float((p[inside] * trials[inside]).sum() / units_in)
        share = float(events[inside].sum() / units_in)
        if rows_in >= MIN_BIN_ROWS:
            bad_bins += share < HIGH_FLOOR * said
        elif float(size[inside].sum()) >= SINGLE_FLIGHTS:
            bad_bins += share < SINGLE_FLOOR * said
    return Score(
        units=units,
        events=float(events.sum()),
        expected=float((p * trials).sum()),
        brier=float(model.sum() / units) if units else 0.0,
        brier_base=float(usual.sum() / units) if units else 0.0,
        high_said=float((p[high] * trials[high]).sum() / high_units) if high_units else 0.0,
        high_seen=float(events[high].sum() / high_units) if high_units else 0.0,
        high_units=high_units,
        bad_bins=bad_bins,
        under_bins=under_bins,
        heavy=int(heavy.sum()),
        under=int(under.sum()),
    )


def under_said(p: Floats, events: Floats, trials: Floats) -> list[tuple[float, float]]:
    """The reliability bins of :data:`UNDER_BIN_LOW` or more, with :data:`UNDER_ROWS` rows and
    :data:`UNDER_EVENTS` events or more, whose share that happened was over :data:`UNDER_SEEN`
    times the chance they said (``(low, top)`` of each)."""
    out: list[tuple[float, float]] = []
    for low, top in pairwise(BINS):
        if low < UNDER_BIN_LOW:
            continue
        inside = (p >= low) & (p < top)
        units_in = float(trials[inside].sum())
        events_in = float(events[inside].sum())
        if units_in <= 0 or int(inside.sum()) < UNDER_ROWS or events_in < UNDER_EVENTS:
            continue
        said = float((p[inside] * trials[inside]).sum() / units_in)
        if events_in / units_in > UNDER_SEEN * said:
            out.append((low, top))
    return out


def drop_under_said(
    p: Floats,
    events: Floats,
    trials: Floats,
    airports: np.ndarray,
    shown: np.ndarray,
) -> list[str]:
    """The airports to take out so the chances shown (``shown``), pooled over the airports,
    have no bin said too low (:func:`under_said`): one at a time, the airport with the most
    events over what it said in the failing bins (ties by code). The per-airport check cannot
    see a bin of a few block-days at each of many airports; pooled, they are what a reader sees
    at that chance."""
    shown = shown.copy()
    out: list[str] = []
    while bad := under_said(p[shown], events[shown], trials[shown]):
        excess: dict[str, float] = {}
        for low, top in bad:
            inside = shown & (p >= low) & (p < top)
            for code in np.unique(airports[inside]).tolist():
                rows = inside & (airports == code)
                more = float(events[rows].sum() - (p[rows] * trials[rows]).sum())
                excess[str(code)] = excess.get(str(code), 0.0) + more
        worst = max(sorted(excess), key=lambda code: excess[code])
        out.append(worst)
        shown &= airports != worst
    return out


def passes(target: str, test: Score, halves: Sequence[Score] = ()) -> bool:
    """Whether a chance may be published for an airport, target and lead (D6): enough events,
    skill above 0, calibrated, no high bin badly over said (pooled and per bin), no bin badly
    under said (:attr:`Score.under_bins`), and skill above
    0 in each half of the test year (``halves``: the even and the odd ISO weeks), and heavy
    block-days said far too low kept rare (:attr:`Score.under_ok`)."""
    least = MIN_ROUGH_DAYS if target == "rough" else MIN_EVENTS
    if test.events < least or test.skill <= 0:
        return False
    low, high = CALIBRATION
    if not low <= test.calibration <= high:
        return False
    if test.bad_bins or test.under_bins or not test.under_ok:
        return False
    if any(half.skill <= 0 for half in halves):
        return False
    return not (test.high_units > 0 and test.high_seen < HIGH_FLOOR * test.high_said)


def combined(scores: Sequence[Score]) -> Score:
    """Scores of disjoint rows added together (units, events, expected and both Brier sums)."""
    units = sum(s.units for s in scores)
    return Score(
        units=units,
        events=sum(s.events for s in scores),
        expected=sum(s.expected for s in scores),
        brier=sum(s.brier * s.units for s in scores) / units if units else 0.0,
        brier_base=sum(s.brier_base * s.units for s in scores) / units if units else 0.0,
        heavy=sum(s.heavy for s in scores),
        under=sum(s.under for s in scores),
    )


AFTER_MIN_EVENTS: Final = 50
"""Held-out events a lead needs before its chances are shown the day after a storm (LR-F6)."""
AFTER_DRAWS: Final = 1000
"""Day-level bootstrap draws of the after-storm skill."""
AFTER_SEED: Final = 20261122
"""The bootstrap's fixed seed, so the gate and the report reproduce."""
AFTER_BOUND: Final = 0.05
"""The skill's lower bound is its 5th percentile over the draws (a 90% two-sided bound)."""


def skill_lower(  # noqa: PLR0913, PLR0917 - the rows and their days
    p: Floats,
    base: Floats,
    events: Floats,
    trials: Floats,
    days: np.ndarray,
    seed: int = AFTER_SEED,
) -> float:
    """The lower 90% bound of the skill of chances ``p`` over the usual ``base``, by a
    day-level bootstrap with a fixed seed: whole days are drawn again with replacement, so the
    block-days of one storm stand or fall together. ``-inf`` with no rows."""
    if len(p) == 0:
        return float("-inf")
    _, day = np.unique(days, return_inverse=True)
    misses = trials - events
    model = np.bincount(day, weights=events * (1 - p) ** 2 + misses * p**2)
    usual = np.bincount(day, weights=events * (1 - base) ** 2 + misses * base**2)
    rng = np.random.default_rng(seed)
    count = len(model)
    skills = np.empty(AFTER_DRAWS)
    for draw in range(AFTER_DRAWS):
        weights = np.bincount(rng.integers(0, count, count), minlength=count)
        lower_usual = float(weights @ usual)
        skills[draw] = 1 - float(weights @ model) / lower_usual if lower_usual > 0 else 0.0
    return float(np.quantile(skills, AFTER_BOUND))


def after_storm_ok(test: Score, lower: float) -> bool:
    """Whether a target and lead's chances may be published the day after a storm (LR-F6):
    its rows after an observed storm (:func:`after_storm`) at the airports that passed, pooled,
    have at least :data:`AFTER_MIN_EVENTS` events, skill whose lower 90% bound by days
    (``lower``, :func:`skill_lower`) is above 0, are calibrated, have no bin badly under said
    (:attr:`Score.under_bins`), and keep heavy block-days said far too low rare. With too few
    such rows in the test year it is not known, so not."""
    if test.units <= 0 or test.events < AFTER_MIN_EVENTS or test.skill <= 0 or lower <= 0:
        return False
    if test.under_bins:
        return False
    low, high = CALIBRATION
    return low <= test.calibration <= high and test.under_ok


def confirmed(
    target: str, even: Mapping[str, Score], odd: Mapping[str, Score]
) -> tuple[Score, int, int]:
    """The skill out of selection: airports that pass on the even weeks scored together on the
    odd weeks, and the reverse. Out: that score, and how many airports each half chose."""
    chosen_even = [code for code, test in even.items() if passes(target, test)]
    chosen_odd = [code for code, test in odd.items() if passes(target, test)]
    scored = [odd[code] for code in chosen_even if code in odd]
    scored += [even[code] for code in chosen_odd if code in even]
    return combined(scored), len(chosen_even), len(chosen_odd)


def reliability(p: Floats, events: Floats, trials: Floats) -> list[dict[str, float]]:
    """The pooled reliability table: per bin of the chance said, the units, the mean chance said
    and the share that happened."""
    rows: list[dict[str, float]] = []
    for low, high in pairwise(BINS):
        inside = (p >= low) & (p < high)
        units = float(trials[inside].sum())
        if units == 0:
            continue
        rows.append(
            {
                "low": low,
                "high": min(high, 1.0),
                "units": units,
                "said": float((p[inside] * trials[inside]).sum() / units),
                "seen": float(events[inside].sum() / units),
            }
        )
    return rows


@dataclass(slots=True)
class Model:
    """The fitted chances: a regression per target and lead, the usual rates, and the gate."""

    fitted: dict[tuple[str, int], Fitted] = field(default_factory=dict)
    published: dict[tuple[str, str, int], bool] = field(default_factory=dict)
    """``(airport, target, lead)``: whether its chance passed the held-out test."""
    after: dict[tuple[str, int], bool] = field(default_factory=dict)
    """``(target, lead)``: whether its chances passed the day after a storm
    (:func:`after_storm_ok`); where not, those days show the usual rate."""
    inputs: tuple[str, ...] = FEATURES
    """The inputs the regressions use, in :data:`FEATURES` order: the groups that passed the
    check on the validation year (:func:`snowlight.flights.train.choose_inputs`)."""

    def chance(self, target: str, lead: int, x: Floats) -> Floats:
        """The model's chances for a target and lead class, from a design matrix of every
        input (:func:`design`)."""
        return self.fitted[(target, lead)].predict(x[:, columns(self.inputs)])

    def is_published(self, airport: str, target: str, lead: int) -> bool:
        """Whether this airport's chance for the target and lead passed."""
        return self.published.get((airport, target, lead), False)

    def shows(self, airport: str, target: str, lead: int, *, stormy: bool) -> bool:
        """Whether the files show this airport's chance (else its usual rate): it passed, and,
        the day after a storm (``stormy``), the target and lead passed then too."""
        if not self.is_published(airport, target, lead):
            return False
        return not stormy or self.after.get((target, lead), False)


def columns(inputs: Sequence[str]) -> list[int]:
    """The columns of :func:`design` that ``inputs`` names.

    Raises:
        ValueError: a name is not an input, or they are not in :data:`FEATURES` order.
    """
    index = [FEATURES.index(name) for name in inputs]
    if index != sorted(set(index)):
        raise ValueError("inputs are not in the order of FEATURES")
    return index


def without(groups: Sequence[str]) -> tuple[str, ...]:
    """Every input but those whose names start with one of ``groups`` (``day_``, ...)."""
    return tuple(name for name in FEATURES if not name.startswith(tuple(groups)))


def leads() -> Sequence[int]:
    """Every lead class."""
    return LEADS
