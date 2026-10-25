"""The reasons' terms: what the forecast amounts and the districts next door add to the base
(S7 spec c.2, pieces 2 and 3; addendum 2026-10-24 g).

``logit p = logit(p_base) + sum_j f_j(x_j)``: ``p_base`` is the published pooled chance
(:mod:`snowlight.predict.pool`), and each term ``f_j`` is a monotone step function of one
input level with ``f_j(reference) = 0``, fit by L2-penalized logistic regression with the base
as offset and sign bounds (:func:`fit`). The inputs, the same in training and serving:

* the forecast bucket of the district at the class snapshot (:mod:`snowlight.predict.ndfd`
  ``bucket_codes``: one code of 0 quiet, 1-5 snow, 6-8 ice, 9-12 how cold it feels, 13
  unknown, in the history's priority), read as three levels (:func:`levels_of`): snow 0-5,
  ice 0-2 (under 0.10, 0.10 to 0.25, 0.25 inches or more), cold 0-4 (warmer than 10 F, then
  each bucket colder). A level the code hides (snow under an ice code, cold under a snow or
  ice code) is unknown, and an unknown level adds nothing. A day of freezing drizzle (code 6,
  ice under 0.10 inch) has no snow level either: what it is forecast for is the ice, so it is
  never read as a light snow day;
* the share of the districts next door already posted closed or remote
  (:mod:`snowlight.predict.posts`, :mod:`snowlight.predict.nowcast`), as a level: 0 none, 1 up
  to a quarter, 2 up to half, 3 more than half.

Which terms a day has follows the day's own weather (:data:`TERMS_OF`), never only the
weather whose days its base counts: a class that is not modeled publishes its fallback's rates
(``model.fallback``: lake effect snow, ice, tropical and cold days take the winter storm
warning days'), and such a day must not take the fallback's snow term. A snow term also needs
the base to count days of its own group (:data:`SNOW_GROUP`), as its band and its words ("than
most storms", "than most advisory days") are of those days; an advisory day counted over winter
storm warning days has no snow term.

Terms and signs (spec c.2): ice, cold and neighbors only add (reference level 0). Snow is
counted against the recorded days of the same weather: the base is a rate over those days,
so its typical storm is already in it. The snow term is 0 on every bucket that is not above
or below most of them, positive only on a bucket above more than half of the counted days'
buckets ("more than most storms") and negative only on one below more than half
(:func:`zero_band`). The snow terms are per class group (advisory days; winter storm and
blizzard warning days), each against its own days' buckets, pooled over the nation (the
archive holds too few known days of any one district to say its own typical storm); lake
effect snow, tropical, ice, cold and clear days have no snow term. On warning days the snow
term only adds (:data:`ADD_ONLY_SNOW`): the forecast is read at 9 PM the evening before and
counts only the snow still to fall, so a storm mostly fallen by then would read lighter than
most storms though it is not.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize  # type: ignore[import-untyped]

from snowlight.predict.situations import WeatherClass

type Floats = npt.NDArray[np.float64]
type Ints = npt.NDArray[np.int64]

UNKNOWN: Final = -1
"""A level the inputs do not give: the term adds nothing."""
UNKNOWN_CODE: Final = 13


class Term(StrEnum):
    """One reason's term."""

    SNOW_ADVISORY = "snow_advisory"
    """Snow on advisory days, against the recorded advisory days."""
    SNOW_STORM = "snow_storm"
    """Snow on winter storm and blizzard warning days, against those recorded days."""
    ICE = "ice"
    COLD = "cold"
    NEIGHBORS = "neighbors"


LEVELS: Final[dict[Term, int]] = {
    Term.SNOW_ADVISORY: 6,
    Term.SNOW_STORM: 6,
    Term.ICE: 3,
    Term.COLD: 5,
    Term.NEIGHBORS: 4,
}
ADD_ONLY: Final = frozenset({Term.ICE, Term.COLD, Term.NEIGHBORS})
ADD_ONLY_SNOW: Final = frozenset({Term.SNOW_STORM})
"""Snow terms that only add (no step below their band): see the module docstring."""
SNOW_TERMS: Final = frozenset({Term.SNOW_ADVISORY, Term.SNOW_STORM})

TERMS_OF: Final[dict[WeatherClass, tuple[Term, ...]]] = {
    WeatherClass.NONE: (Term.NEIGHBORS,),
    WeatherClass.ADVISORY: (Term.SNOW_ADVISORY, Term.ICE, Term.NEIGHBORS),
    WeatherClass.TROPICAL: (Term.NEIGHBORS,),
    WeatherClass.COLD: (Term.COLD, Term.NEIGHBORS),
    WeatherClass.LAKE_SNOW: (Term.NEIGHBORS,),
    WeatherClass.SNOW_WARNING: (Term.SNOW_STORM, Term.ICE, Term.NEIGHBORS),
    WeatherClass.ICE: (Term.ICE, Term.NEIGHBORS),
    WeatherClass.BLIZZARD: (Term.SNOW_STORM, Term.ICE, Term.NEIGHBORS),
}
"""The terms of a day of this weather (the day's own class, whatever its base counts)."""
SNOW_GROUP: Final[dict[Term, frozenset[WeatherClass]]] = {
    Term.SNOW_ADVISORY: frozenset({WeatherClass.ADVISORY}),
    Term.SNOW_STORM: frozenset({WeatherClass.SNOW_WARNING, WeatherClass.BLIZZARD}),
}
"""A snow term's class group: the day's own class and the class its base counts must both be
in it."""
TERM_ORDER: Final = tuple(Term)


def has_term(term: Term, own: WeatherClass, counted: WeatherClass) -> bool:
    """Whether a day of weather ``own``, its base counted over ``counted``'s days, has
    ``term``."""
    if term not in TERMS_OF[own]:
        return False
    group = SNOW_GROUP.get(term)
    return group is None or counted in group


@dataclass(frozen=True, slots=True)
class Levels:
    """One unit-day's input levels (:data:`UNKNOWN` where not given)."""

    snow: int = UNKNOWN
    ice: int = UNKNOWN
    cold: int = UNKNOWN
    neighbors: int = UNKNOWN

    def of(self, term: Term) -> int:
        """The level a term reads."""
        if term in {Term.SNOW_ADVISORY, Term.SNOW_STORM}:
            return self.snow
        if term == Term.ICE:
            return self.ice
        if term == Term.COLD:
            return self.cold
        return self.neighbors


def levels_of(code: int | None) -> tuple[int, int, int]:
    """(snow, ice, cold) levels of a forecast bucket code (:data:`UNKNOWN` where it hides
    them: an ice code, freezing drizzle's among them, hides the snow, a snow or ice code hides
    the cold; 13 or ``None`` hides all)."""
    if code is None or code == UNKNOWN_CODE:
        return UNKNOWN, UNKNOWN, UNKNOWN
    if code == 0:
        return 0, 0, 0
    if 1 <= code <= 5:  # noqa: PLR2004 - snow buckets
        return code, 0, UNKNOWN
    if code == 6:  # noqa: PLR2004 - freezing drizzle: under 0.10 inch of ice, the snow not read
        return UNKNOWN, 0, UNKNOWN
    if code in {7, 8}:
        return UNKNOWN, code - 6, UNKNOWN
    if 9 <= code <= 12:  # noqa: PLR2004 - how cold it feels, no snow or ice
        return 0, 0, code - 8
    raise ValueError(f"not a forecast bucket code: {code}")


SNOW_EDGES: Final = (0.5, 2.0, 4.0, 6.0, 9.0)
"""Inches where snow levels 1 to 5 start (the history's buckets, ``ndfd.SNOW_FROM``)."""


NEIGHBOR_STEPS: Final = (0.25, 0.5)


def neighbor_level(share: float | None) -> int:
    """The neighbors' level: 0 none posted, 1 up to a quarter, 2 up to half, 3 more."""
    if share is None or math.isnan(share):
        return UNKNOWN
    if share <= 0:
        return 0
    if share <= NEIGHBOR_STEPS[0]:
        return 1
    if share <= NEIGHBOR_STEPS[1]:
        return 2
    return 3


def zero_band(counts: Sequence[int]) -> tuple[int, int]:
    """The snow buckets the term is 0 on, (low, high), from the counted days' buckets: a
    bucket is above most of them when more than half are lower, below most when more than half
    are higher; the band is every bucket that is neither (it holds the median, so it is never
    empty). With no counted days the band is every bucket (no snow term)."""
    total = sum(counts)
    if total <= 0:
        return 0, len(counts) - 1
    inside = [
        b
        for b in range(len(counts))
        if 2 * sum(counts[:b]) <= total and 2 * sum(counts[b + 1 :]) <= total
    ]
    return min(inside), max(inside)


@dataclass(frozen=True, slots=True)
class Shape:
    """A term's steps: 0 on [low, high]; ``up[k]`` added at each level above ``high`` from
    ``high + 1 + k`` on, ``down[k]`` taken away at each level below ``low`` from ``low - 1 - k``
    down."""

    levels: int
    low: int
    high: int

    @property
    def ups(self) -> int:
        """Increments above the band."""
        return self.levels - 1 - self.high

    @property
    def downs(self) -> int:
        """Increments below the band."""
        return self.low

    @property
    def size(self) -> int:
        """Parameters."""
        return self.ups + self.downs

    def columns(self, level: Ints) -> Floats:
        """The design columns of ``level`` (rows, size): +1 per up step reached, -1 per down
        step reached; an unknown level reaches none."""
        known = level >= 0
        found = np.zeros((level.size, self.size))
        for k in range(self.ups):
            found[:, k] = (known & (level >= self.high + 1 + k)).astype(np.float64)
        for k in range(self.downs):
            found[:, self.ups + k] = -(known & (level <= self.low - 1 - k)).astype(np.float64)
        return found


@dataclass(frozen=True, slots=True)
class TermFit:
    """One fitted term: its shape and its steps (all at least 0)."""

    term: Term
    shape: Shape
    up: tuple[float, ...]
    down: tuple[float, ...]
    counts: tuple[int, ...] = ()
    """The counted days' levels (snow terms), which the band was taken from."""

    def value(self, level: int) -> float:
        """``f(level)`` on the logit scale (0 for an unknown level)."""
        if level < 0:
            return 0.0
        if level > self.shape.high:
            return float(sum(self.up[: level - self.shape.high]))
        if level < self.shape.low:
            return -float(sum(self.down[: self.shape.low - level]))
        return 0.0


@dataclass(frozen=True, slots=True)
class Model:
    """Every fitted term."""

    fits: Mapping[Term, TermFit]
    penalty: float

    def values(self, own: WeatherClass, counted: WeatherClass, levels: Levels) -> dict[Term, float]:
        """The terms of a day of weather ``own`` whose base counts ``counted``'s days
        (:func:`has_term`), each ``f(level)``; terms that add nothing are left out."""
        found: dict[Term, float] = {}
        for term in TERMS_OF[own]:
            fit = self.fits.get(term)
            if fit is None or not has_term(term, own, counted):
                continue
            value = fit.value(levels.of(term))
            if value != 0.0:
                found[term] = value
        return found


NO_TERMS: Final = Model({}, 0.0)


def logit(p: Floats) -> Floats:
    """The log odds, the chance kept inside (1e-6, 1 - 1e-6)."""
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return np.asarray(np.log(q / (1 - q)), dtype=np.float64)


def sigmoid(x: Floats) -> Floats:
    """The inverse of :func:`logit`."""
    return np.asarray(1.0 / (1.0 + np.exp(-x)), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class Design:
    """The rows a fit sees: the base's log odds, the outcome, each term's level, the weather
    whose days the base counts and the day's own weather."""

    offset: Floats
    y: Floats
    weather: Ints
    """The weather class whose days the base counts (its situation's, or the fallback's)."""
    levels: Mapping[Term, Ints]
    weight: Floats | None = None
    """Each row's weight in the fit (``None``: 1 each)."""
    own: Ints | None = None
    """The day's own weather class (``None``: the counted one)."""

    def subset(self, keep: npt.NDArray[np.bool_]) -> "Design":
        """The rows ``keep`` selects."""
        return Design(
            self.offset[keep],
            self.y[keep],
            self.weather[keep],
            {term: level[keep] for term, level in self.levels.items()},
            None if self.weight is None else self.weight[keep],
            None if self.own is None else self.own[keep],
        )

    def weights(self) -> Floats:
        """Each row's weight."""
        return np.ones(self.y.size) if self.weight is None else self.weight

    def own_weather(self) -> Ints:
        """Each row's own weather class."""
        return self.weather if self.own is None else self.own


def applies(term: Term, own: Ints, counted: Ints | None = None) -> npt.NDArray[np.bool_]:
    """Rows that have ``term`` (:func:`has_term`): the day's own weather ``own``, the base's
    counted weather ``counted`` (``None``: the same)."""
    classes = [int(w) for w, terms in TERMS_OF.items() if term in terms]
    found = np.isin(own, np.array(classes, dtype=np.int64))
    group = SNOW_GROUP.get(term)
    if group is not None:
        counted = own if counted is None else counted
        found &= np.isin(counted, np.array(sorted(int(w) for w in group), dtype=np.int64))
    return np.asarray(found, dtype=np.bool_)


def _applies(term: Term, design: Design) -> npt.NDArray[np.bool_]:
    return applies(term, design.own_weather(), design.weather)


def shapes_for(design: Design) -> dict[Term, Shape]:
    """Each term's shape: add-only terms from level 0; a snow term's band from its rows' snow
    buckets (:func:`zero_band`), from level 0 for one that only adds (:data:`ADD_ONLY_SNOW`)."""
    found: dict[Term, Shape] = {}
    for term in TERM_ORDER:
        levels = LEVELS[term]
        if term in ADD_ONLY:
            found[term] = Shape(levels, 0, 0)
            continue
        level = design.levels[term][_applies(term, design)]
        counts = np.bincount(level[level >= 0], minlength=levels)[:levels]
        low, high = zero_band([int(c) for c in counts])
        found[term] = Shape(levels, 0 if term in ADD_ONLY_SNOW else low, high)
    return found


def _matrix(design: Design, shapes: Mapping[Term, Shape]) -> tuple[Floats, list[tuple[Term, int]]]:
    blocks: list[Floats] = []
    owners: list[tuple[Term, int]] = []
    for term in TERM_ORDER:
        shape = shapes[term]
        if not shape.size:
            continue
        level = np.where(_applies(term, design), design.levels[term], UNKNOWN)
        blocks.append(shape.columns(level.astype(np.int64)))
        owners.extend((term, k) for k in range(shape.size))
    if not blocks:
        return np.zeros((design.y.size, 0)), owners
    return np.hstack(blocks), owners


def _solve(x: Floats, offset: Floats, y: Floats, w: Floats, penalty: float) -> Floats:
    if not x.shape[1] or not y.size:
        return np.zeros(x.shape[1])

    def loss(theta: Floats) -> tuple[float, Floats]:
        z = offset + x @ theta
        # log(1 + e^z) - y z, stably.
        value = float(np.sum(w * (np.logaddexp(0.0, z) - y * z)) + 0.5 * penalty * theta @ theta)
        grad = x.T @ (w * (sigmoid(z) - y)) + penalty * theta
        return value, np.asarray(grad, dtype=np.float64)

    found = minimize(
        loss,
        np.zeros(x.shape[1]),
        jac=True,
        method="L-BFGS-B",
        bounds=[(0.0, None)] * x.shape[1],
        options={"maxiter": 500},
    )
    return np.asarray(found.x, dtype=np.float64)


def fit_with(design: Design, penalty: float, shapes: Mapping[Term, Shape] | None = None) -> Model:
    """The terms fit on ``design`` with L2 ``penalty`` (bounds keep every step at least 0, so
    each term is monotone with its sign)."""
    shapes = dict(shapes) if shapes is not None else shapes_for(design)
    x, owners = _matrix(design, shapes)
    theta = _solve(x, design.offset, design.y, design.weights(), penalty)
    fits: dict[Term, TermFit] = {}
    for term in TERM_ORDER:
        shape = shapes[term]
        mine = [float(theta[i]) for i, (owner, _k) in enumerate(owners) if owner == term]
        counts: tuple[int, ...] = ()
        if term not in ADD_ONLY:
            level = design.levels[term][_applies(term, design)]
            counts = tuple(int(c) for c in np.bincount(level[level >= 0], minlength=LEVELS[term]))
        fits[term] = TermFit(
            term, shape, up=tuple(mine[: shape.ups]), down=tuple(mine[shape.ups :]), counts=counts
        )
    return Model(fits, penalty)


def contributions(model: Model, design: Design) -> dict[Term, Floats]:
    """Each fitted term's ``f(level)`` on every row (0 where the row does not have it)."""
    found: dict[Term, Floats] = {}
    for term in TERM_ORDER:
        fit = model.fits.get(term)
        if fit is None:
            continue
        level = np.where(_applies(term, design), design.levels[term], UNKNOWN)
        found[term] = np.array([fit.value(int(v)) for v in level.tolist()], dtype=np.float64)
    return found


def predict(model: Model, design: Design) -> Floats:
    """The chance with the terms, unrounded."""
    z = design.offset.copy()
    for value in contributions(model, design).values():
        z += value
    return sigmoid(z)


PENALTIES: Final = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0)
"""The L2 penalties the inner leave-one-season-out loop picks from. A pick at either end is
reported (``backtest_terms``). A grid widened to 0.03 and 10,000 was tried on the labels of
2026-10-25: the early folds then picked 0.03 and 2023-24 10,000, again the ends, and the
pooled storm Brier was worse (7.2% against 6.3%): with one or two seasons holding forecast
levels, the inner loop has too little to choose a penalty from, so the grid stays."""


def _held_out_loss(design: Design, seasons: Ints, penalty: float) -> float:
    total = 0.0
    for season in sorted(set(seasons.tolist())):
        held = seasons == season
        model = fit_with(design.subset(~held), penalty)
        p = np.clip(predict(model, design.subset(held)), 1e-6, 1 - 1e-6)
        y = design.y[held]
        w = design.weights()[held]
        total += float(-np.sum(w * (y * np.log(p) + (1 - y) * np.log(1 - p))))
    return total


def fit(design: Design, seasons: Ints, penalties: Sequence[float] = PENALTIES) -> Model:
    """The terms fit on every row, with the penalty that gives the lowest log loss leaving one
    season out at a time, inside these rows' seasons only (a single season: the middle one).
    Each inner fit takes its bands from its own rows only, never the season it leaves out; the
    final fit takes them from every row."""
    distinct = sorted(set(seasons.tolist()))
    if len(distinct) < 2:  # noqa: PLR2004 - nothing to leave out
        return fit_with(design, penalties[len(penalties) // 2])
    best: tuple[float, float] | None = None
    for penalty in penalties:
        loss = _held_out_loss(design, seasons, penalty)
        if best is None or loss < best[0] - 1e-9:
            best = (loss, penalty)
    assert best is not None  # noqa: S101
    return fit_with(design, best[1])
