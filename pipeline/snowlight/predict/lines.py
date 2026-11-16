"""Each district's own part, in shadow (each-school P6a OWN-SHADOW): whether a district tends to
close early or hold out given the same forecast, fit every night and scored beside today's
chance. Nothing served reads anything here: every chance and every byte the pass publishes is
the same with this module on or off (a test holds it so).

**The prior-neutral base** (each-school 3.2, lead rulings LR23 and LR26). A unit ``i`` whose
own part has the prior N(0, ``V0``) gets, from today's chance ``base``::

    x   solves  E[sigmoid(x + b)] = base,  b ~ N(0, V0)          (the 20-point rule)
    p   = E[sigmoid(x + a)],               a ~ N(m, v)           (the part's posterior)

so a unit whose record says nothing (``m`` 0, ``v`` = ``V0``) gets ``base`` exactly, and a unit
with evidence moves by what it says, as an average, never a plug-in value. :func:`own_points`
splits the move into own's points (sign always ``m``'s) and the rest; :func:`folded_base` is
P7y's folded base (own applied to the class level first, clamped to 1%..99%).

**M5o, the own part** (r4 2.5 and 9). One tendency per district, N(0, ``s_own^2``) with a
half-normal(0.5) hyperprior, ``s_own`` and every ``|own|`` at most 1.5, fit by penalized
likelihood (Laplace) in the two forms r4 9 step 1 registers:

* **live rows** (:func:`fit_live`): the anchor's row likelihood (:mod:`snowlight.predict.
  anchor`) with the market-day effect ``e_j ~ N(0, tau_c^2)`` integrated on the 20-point rule,
  each row at ``x_i + own + e_j``, ``x_i`` the 20:07 frozen chance's prior-neutral log odds at
  ``tau_c`` (its ``o + t`` at its served class level; never ``W*``): ``no_school`` closed,
  ``delayed`` open, and ``unnamed`` as ``1 - s (p + (1 - p) q_c)`` (honesty rule 2: never a
  certain open), ``s`` its lists' sensitivity (each list's Beta posterior from its tier's
  prior and its own co-listing trials; the most sensitive list that read the row whole, the
  one-list form), ``q_c`` the anchor's delay share. Tier B rows enter only under the anchor's
  tier B rule;
* **archive rows** (:func:`fit_own`): the exact conditional likelihood within market-morning
  and class (the storm-picked level drops out exactly; no fixed effect per group, so no
  incidental-parameter bias in small groups), with the whole Hessian in the Laplace term.

Each market-morning carries its storm's weight under the anchor's ``storm_weights`` and the
class's ``max_date_share`` (r4 9 step 2: one storm cannot carry more than its share). Units
honesty rule 4 names (``each_school.own_excluded``: state-agency LEAs, units whose schools span
3 or more counties, CT Technical 0900002) never reach a fit. Rows enter a ledger once, in day
order, the first pass their frozen day is held (at most :data:`TAKE_UP_DAYS` days a pass); a
row of the served day or later never enters (the record job and the passes overlap), nor a
day-after row (rule 10: they wait for R10), nor one whose L1 class is not its served class.

**M5y, Kentucky's years** (each-school 7.1, lead rulings LR21 and LR24), read only through
R-KYY (:func:`read_kyy`): each district's count tendency ``t`` from its weather closing day
counts of school years before the served one, and one slope ``beta`` on rows K (dated W days of
a known class, with the class days the district held school), so ``own = beta t``. Rows K need
each Kentucky district's class on each dated day; the record holds every dated day's class as
``unknown`` until the class backfill (LR14, LR21), so at head M5y writes nothing, says so, and
pulls nothing from the store.

**MP and M5g** are registered off (:data:`ARMS`): MP needs P2f's private live labels and M5g
the grown record's rows (P2b, P2c), neither built.

**The record.** Only this module reads the record kind, and only through :data:`READS`; today
one, R-KYY. Nothing here touches the published file, the anchor or the learned model.
"""

import json
import math
import sys
import time
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NoReturn

import numpy as np
import numpy.typing as npt

# threadpoolctl comes with scikit-learn, which the pipeline depends on.
from threadpoolctl import (  # type: ignore[import-untyped, unused-ignore]
    threadpool_limits,
)

from snowlight.output import write_bytes_atomic
from snowlight.predict import frozen
from snowlight.predict import record as record_kind
from snowlight.predict.anchor import (
    LiveRow,
    Trials,
    row_information,
    sensitivity,
    storm_weights,
    storms_of,
)

if TYPE_CHECKING:
    from snowlight.predict.anchor import Anchor, AnchorSettings
    from snowlight.predict.config import LearnSettings

type Floats = npt.NDArray[np.float64]
type Ints = npt.NDArray[np.int64]

# --- what is registered ------------------------------------------------------------------------

ARMS: Final[Mapping[str, str | None]] = {
    "m5o": None,
    "m5y": None,
    "mp": "off: P2f's private live labels are not built",
    "m5g": "off: the grown record's rows (P2b, P2c) are not built",
}
"""Each shadow arm in registered order, and why it is off (``None``: on). Only the arms on are
written, in this order, to each shadow line's ``es``."""
WRITTEN: Final = tuple(arm for arm, off in ARMS.items() if off is None)
READS: Final[Mapping[str, tuple[str, ...] | None]] = {
    "R-P1": None,
    "R-P7P": None,
    "R-P7Y": None,
    "R-KYY": ("store_past", "read_kyy"),
}
"""The named reads of the record kind (each-school 10.5 with lead rulings LR19 and LR21), each
with the functions of this module that make it (its pull from the store and its reader;
``None``: its piece, P1, P7p or P7y, is not built, so no function reads it). Nothing else in
the package reads the record."""


class _RecordRead:
    """The capability to read the record kind from the evidence store (lead ruling LR-P6A-1):
    made once, here, at import (:data:`_READ`), and passed only by :func:`store_past`. The
    store refuses the record to every read without it, outside the record's own modules
    (:data:`snowlight.live.evidence.RECORD_OWNERS`), and checks it by identity, so a copy or a
    second one made by hand reads nothing. It is never pickled."""

    __slots__ = ()

    def __new__(cls) -> "_RecordRead":
        if sys._getframe(1).f_globals.get("__name__") != __name__ or "_READ" in globals():
            raise TypeError("only snowlight.predict.lines makes the record's capability, once")
        return super().__new__(cls)

    def __copy__(self) -> "_RecordRead":
        return self

    def __deepcopy__(self, memo: object) -> "_RecordRead":
        return self

    def __reduce__(self) -> NoReturn:
        raise TypeError("the record's capability is never pickled")


_READ: Final = _RecordRead()
POINTS: Final = 20
"""The quadrature rule's points (``live_score.anchor.quadrature_points``)."""
OWN_BOUND: Final = 1.5
"""The most ``|own|`` and ``s_own`` may be (r4 2.5)."""
OWN_SCALE: Final = 0.5
"""The half-normal hyperprior's scale of ``s_own``."""
SPREAD_STEP: Final = 0.02
"""The grid of ``s_own`` the fit chooses on, 0 to :data:`OWN_BOUND` (near the joint ascent's
answer, and 0)."""
CLASSES: Final = ("advisory", "warning")
FIT_FREEZE: Final = "d1_2007"
"""The scoring freeze whose frozen chance is a live row's offset (20:07 the evening before)."""
SWITCH_HOUR: Final = (19, 30)
"""The nightly fit runs in the first pass at or after 19:30 UTC (after the record job)."""
FIT_BUDGET: Final = 10.0
"""The seconds of a pass the nightly step may take (``each_school.fit_budget_seconds``); over
it, the pass says so in one warning line and goes on (the fit is in shadow)."""
TAKE_UP_DAYS: Final = 2
"""The labeled days a pass takes up into the ledger at most (``each_school.take_up_days``):
each reads L1's day and one freeze of its frozen day; a backlog is taken up over passes."""
LEDGER_WINTERS: Final = 2
"""The school years the ledger keeps: the served day's and the one before (a winter of
advisory and warning district-days is about 80,000 rows nationally)."""
LEDGER_ROWS: Final = 80_000
"""The most rows the ledger keeps, about a winter's nationally: past it, its oldest days go
whole, so the nightly step stays in :data:`FIT_BUDGET` (measured SYNTHETIC end to end at
79,524 rows and 29,074 districts, one full-scale day taken up: 6.8 s to 7.5 s, the fit 4.9 s to
5.1 s and its checks 1.0 s) and ``fit.json`` in the cache stays about 10 MB (10.1 MB there)."""
MAX_AGE: Final = timedelta(hours=36)
"""A fit older than this is made again by the next pass, whatever the hour; a line of a fit
older than this is not scored as current (:func:`snowlight.predict.backtest_lines.score_es`)."""
FIT_NAME: Final = "fit.json"
"""The nightly fit and its ledger, in the shadow arms' folder (codes, ids, days and numbers)."""
FAILED_NAME: Final = "fit-failed.json"
"""When the last nightly fit failed: none is tried again before the next 19:30 UTC."""
FIT_SCHEMA: Final = 3
BASE_TOL: Final = 1e-9
STEP_TOL: Final = 1e-6
"""A fit stops once no step moves a value by more than this (a part off by it moves a chance
by under 1e-6 and the marginal likelihood by under 1e-9 a unit)."""
SMALL_GROUP: Final = 12
"""A group of at most this many rows has its conditional likelihood by enumeration (exact
second moments); a larger one by recursion, with Hajek's form of its second moments."""
KENTUCKY: Final = "21"
LOW: Final = 1e-9
TINY: Final = 1e-300
LIVE_ROUNDS: Final = 60
"""The joint ascent's rounds at most (:func:`_live_search`); the registered grid is then
searched around where it stands."""
LIVE_TOL: Final = 1e-3
LIVE_LABELS: Final = ("no_school", "delayed", "unnamed")


# --- the prior-neutral base (each-school 3.2) -------------------------------------------------


def nodes(points: int = POINTS) -> tuple[Floats, Floats]:
    """The ``points``-point Gauss-Hermite rule for N(0, 1): nodes and weights summing to 1."""
    z, w = np.polynomial.hermite_e.hermegauss(points)
    return np.asarray(z, dtype=np.float64), np.asarray(w / w.sum(), dtype=np.float64)


_Z, _W = nodes()
_LOG_W = np.log(_W)


def _sigmoid(x: Floats) -> Floats:
    out: Floats = 0.5 * (1.0 + np.tanh(0.5 * x))
    return out


def expect(x: Floats | float, mean: Floats | float, var: Floats | float) -> Floats:
    """``E[sigmoid(x + a)]``, ``a ~ N(mean, var)``, on the 20-point rule (elementwise)."""
    x_, m_, v_ = np.broadcast_arrays(
        np.asarray(x, dtype=np.float64),
        np.asarray(mean, dtype=np.float64),
        np.asarray(var, dtype=np.float64),
    )
    shift = np.sqrt(np.maximum(v_, 0.0))[..., None] * _Z
    found: Floats = (_sigmoid((x_ + m_)[..., None] + shift) * _W).sum(axis=-1)
    return found


def solve_base(base: Floats | float, v0: Floats | float) -> Floats:
    """``x`` with ``E[sigmoid(x + b)] = base``, ``b ~ N(0, v0)``, by bisection to 1e-9 in
    probability (elementwise; ``base`` held within 1e-9 of 0 and 1)."""
    target = np.clip(np.asarray(base, dtype=np.float64), LOW, 1.0 - LOW)
    var = np.broadcast_to(np.asarray(v0, dtype=np.float64), target.shape)
    lo = np.full(target.shape, -60.0)
    hi = np.full(target.shape, 60.0)
    mid = 0.5 * (lo + hi)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        got = expect(mid, 0.0, var)
        if np.all(np.abs(got - target) < BASE_TOL * 0.1):
            break
        up = got < target
        lo = np.where(up, mid, lo)
        hi = np.where(up, hi, mid)
    return np.asarray(mid, dtype=np.float64)


def served(
    base: Floats | float, v0: Floats | float, m: Floats | float, v: Floats | float
) -> Floats:
    """The chance a unit gets from ``base`` with its part's prior variance ``v0`` and posterior
    ``N(m, v)`` (3.2): ``base`` exactly (to 1e-9) when the part is at its prior."""
    return expect(solve_base(base, v0), m, v)


def own_points(base: float, v0: float, m: float, v: float) -> tuple[float, float]:
    """Own's points (the chance at ``m`` less the chance at ``m`` 0, both at the unit's own
    ``v``; its sign is always ``m``'s) and the rest (the chance at ``m`` 0 less ``base``),
    in probability; ``base`` plus both is the served chance."""
    x = solve_base(base, v0)
    at = float(expect(x, m, v))
    at_zero = float(expect(x, 0.0, v))
    return at - at_zero, at_zero - base


FOLD_CLAMP: Final = (0.01, 0.99)


def folded_base(level: float, v0: float, m: float, v: float) -> tuple[float, int]:
    """P7y's folded base (lead rulings LR23, LR26): own applied to the class level first (3.2's
    map with the class level as ``base``), clamped to 1%..99%, and its whole points (1..99)."""
    p0 = min(max(float(served(level, v0, m, v)), FOLD_CLAMP[0]), FOLD_CLAMP[1])
    return p0, round(100 * p0)


# --- the own fit (M5o) ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OwnRow:
    """One live (or archive) row a fit reads: its unit, day, market-morning-and-class group, the
    log odds it was served at (its offset), whether it closed, and for a live row its L1 label,
    tier and the lists that read it whole."""

    unit: str
    day: date
    group: str
    klass: str
    offset: float
    closed: bool
    label: str = ""
    """A live row's label (:data:`LIVE_LABELS`); an archive row's is empty: its call is
    known (``closed``)."""
    tier: str = "A"
    lists: tuple[str, ...] = ()

    def as_json(self) -> list[object]:
        return [
            self.unit, self.day.isoformat(), self.group, self.klass, round(self.offset, 6),
            int(self.closed), self.label, self.tier, list(self.lists),
        ]  # fmt: skip

    @classmethod
    def of(cls, value: Sequence[object]) -> "OwnRow":
        unit, day, group, klass, offset, closed, label, tier, lists = value
        if not isinstance(lists, list):
            raise TypeError("a ledger row's lists are not a list")
        return cls(
            str(unit), date.fromisoformat(str(day)), str(group), str(klass), float(str(offset)),
            bool(closed), str(label), str(tier), tuple(str(item) for item in lists),
        )  # fmt: skip


@dataclass(frozen=True, slots=True)
class OwnFit:
    """A fit of the own part: its spread, each unit's posterior mean and variance (a unit not
    here is at its prior), what it read and how long it took."""

    spread: float
    units: Mapping[str, tuple[float, float]]
    rows: int = 0
    groups: int = 0
    seconds: float = 0.0
    excluded: int = 0
    """Rows of units honesty rule 4 names, left out."""

    def posterior(self, unit: str) -> tuple[float, float]:
        """``(m, v)`` of ``unit``: its fit's, else the prior's ``(0, s_own^2)``."""
        return self.units.get(unit, (0.0, self.spread**2))


def drop_served(rows: Iterable[OwnRow], served_day: date) -> list[OwnRow]:
    """Every row before ``served_day``: a row of the served day or later never reaches a fit
    (each-school 10.5)."""
    return [row for row in rows if row.day < served_day]


def _log_halfnormal(s: float, scale: float = OWN_SCALE) -> float:
    return math.log(math.sqrt(2.0 / math.pi) / scale) - s * s / (2 * scale * scale)


def _logsumexp(x: Floats, axis: int) -> Floats:
    top = np.max(x, axis=axis, keepdims=True)
    top = np.where(np.isfinite(top), top, 0.0)
    found: Floats = np.squeeze(top, axis=axis) + np.log(
        np.maximum(np.sum(np.exp(x - top), axis=axis), TINY)
    )
    return found


# --- storms (r4 9 step 2) ---


@dataclass(frozen=True, slots=True)
class Tempering:
    """The anchor's storm rule for a class's market-mornings (:func:`snowlight.predict.anchor.
    storm_table`): mornings ``gap`` weekdays apart or less are one storm; a market-morning of
    ``n`` rows counts ``n / (n + c)``; no storm holds more than ``cap`` of the whole, the
    start's ``start`` counted in."""

    gap: int
    cap: Mapping[str, float]
    start: Mapping[str, float]
    c: Mapping[str, float]

    @classmethod
    def of(cls, settings: "AnchorSettings", start_alpha: Mapping[str, float]) -> "Tempering":
        """From the anchor's settings and each class's no-row ``alpha``."""
        return cls(
            gap=settings.storm_gap,
            cap={k: settings.date_cap[k] for k in CLASSES},
            start={k: (settings.tau / settings.priors[k].alpha_sd) ** 2 for k in CLASSES},
            c={k: row_information(start_alpha[k], settings) for k in CLASSES},
        )


def group_weights(rows: Sequence[OwnRow], tempering: Tempering | None) -> dict[str, float]:
    """Each market-morning's storm weight (1 with no tempering): per class, the anchor's
    ``storm_weights`` over its storms' information, so no storm counts more than its class's
    ``max_date_share`` of the whole."""
    sizes = Counter(row.group for row in rows)
    found = dict.fromkeys(sizes, 1.0)
    if tempering is None:
        return found
    days = {row.group: row.day for row in rows}
    classes = {row.group: row.klass for row in rows}
    for klass in sorted(set(classes.values())):
        mine = [g for g in sizes if classes[g] == klass]
        if klass not in tempering.cap:
            continue
        of = storms_of({days[g] for g in mine}, tempering.gap)
        information: dict[date, float] = {}
        c = tempering.c[klass]
        for g in mine:
            storm = of[days[g]]
            information[storm] = information.get(storm, 0.0) + sizes[g] / (sizes[g] + c)
        weight = storm_weights(information, tempering.start[klass], tempering.cap[klass])
        for g in mine:
            found[g] = weight[of[days[g]]]
    return found


# --- the conditional likelihood within a group (archive rows; rows K) ---


@dataclass(frozen=True, slots=True)
class _Bucket:
    """Groups of one size (and, small ones, one count closed), as arrays: each row's index, its
    call, each group's weight and count closed, and (small groups) every set of that size."""

    rows: Ints
    y: Floats
    weight: Floats
    k: Ints
    sets: Floats | None


def _buckets(groups: Sequence[Sequence[int]], y: Floats, weight: Floats) -> list[_Bucket]:
    by: dict[tuple[int, int], list[int]] = {}
    for g, members in enumerate(groups):
        n = len(members)
        k = int(sum(y[i] for i in members))
        by.setdefault((n, k if n <= SMALL_GROUP else -1), []).append(g)
    found: list[_Bucket] = []
    for (n, k), picked in sorted(by.items()):
        rows = np.array([groups[g] for g in picked], dtype=np.int64)
        sets = None
        if k >= 0:
            sets = np.zeros((math.comb(n, k), n))
            for m, chosen in enumerate(combinations(range(n), k)):
                sets[m, list(chosen)] = 1.0
        counts = np.rint(y[rows].sum(axis=1)).astype(np.int64)
        found.append(_Bucket(rows, y[rows], weight[picked], counts, sets))
    return found


def _recursion(eta: Floats, k: Ints) -> tuple[Floats, Floats]:
    """Per group (rows of ``eta``, each with its count closed ``k``): ``log e_k(exp eta)`` and
    each row's chance of being among the ``k`` closed, by the forward and backward recursions
    in log space."""
    b, n = eta.shape
    top = int(k.max())
    fwd = np.full((b, n + 1, top + 1), -np.inf)
    fwd[:, :, 0] = 0.0
    for i in range(n):
        fwd[:, i + 1, 1:] = np.logaddexp(fwd[:, i, 1:], fwd[:, i, :-1] + eta[:, i : i + 1])
    bwd = np.full((b, n + 2, top + 1), -np.inf)
    bwd[:, :, 0] = 0.0
    for i in range(n - 1, -1, -1):
        bwd[:, i + 1, 1:] = np.logaddexp(bwd[:, i + 2, 1:], bwd[:, i + 2, :-1] + eta[:, i : i + 1])
    at = np.arange(b)
    total = fwd[at, n, k]
    # e_{k-1} of every row but i: before i (fwd[i]) times after i (bwd[i + 2]), over the split
    split = k[:, None] - 1 - np.arange(top)[None, :]
    right = bwd[
        at[:, None, None], np.arange(2, n + 2)[None, :, None], np.maximum(split, 0)[:, None, :]
    ]
    both = np.where((split >= 0)[:, None, :], fwd[:, :n, :top] + right, -np.inf)
    chance = np.exp(eta + _logsumexp(both, axis=2) - total[:, None])
    return total, chance


def _conditional(
    buckets: Sequence[_Bucket], eta: Floats
) -> tuple[float, Floats, list[tuple[Ints, Floats]]]:
    """The weighted conditional log likelihood of every group, each row's weighted residual
    (call less its chance among the closed) and each bucket's weighted covariance of the
    calls given the count (rows, ``(B, n, n)``)."""
    ll = 0.0
    resid = np.zeros(eta.shape[0])
    blocks: list[tuple[Ints, Floats]] = []
    for bucket in buckets:
        e = eta[bucket.rows]
        w = bucket.weight[:, None]
        if bucket.sets is not None:
            logs = e @ bucket.sets.T
            total = _logsumexp(logs, axis=1)
            prob = np.exp(logs - total[:, None])
            chance = prob @ bucket.sets
            second = np.einsum("bm,mi,mj->bij", prob, bucket.sets, bucket.sets)
            cov = second - chance[:, :, None] * chance[:, None, :]
        else:
            total, chance = _recursion(e, bucket.k)
            var = chance * (1 - chance)
            spread = np.maximum(var.sum(axis=1), TINY)
            # Hajek's form: the calls' covariance given their count
            cov = np.einsum("bi,ij->bij", var, np.eye(var.shape[1])) - (
                var[:, :, None] * var[:, None, :] / spread[:, None, None]
            )
        ll += float(np.sum(bucket.weight * ((e * bucket.y).sum(axis=1) - total)))
        np.add.at(resid, bucket.rows, w * (bucket.y - chance))
        blocks.append((bucket.rows, cov * w[:, :, None]))
    return ll, resid, blocks


@dataclass(frozen=True, slots=True)
class _Archive:
    unit: Ints
    offset: Floats
    buckets: tuple[_Bucket, ...]
    units: tuple[str, ...]
    groups: int


def _archive(rows: Sequence[OwnRow], weights: Mapping[str, float]) -> _Archive:
    """The rows of groups with both outcomes (a group all closed or all open says nothing
    within it), as buckets."""
    by: dict[str, list[OwnRow]] = {}
    for row in rows:
        by.setdefault(row.group, []).append(row)
    kept = [
        found for _, found in sorted(by.items()) if 0 < sum(r.closed for r in found) < len(found)
    ]
    flat = [row for found in kept for row in found]
    units = tuple(sorted({row.unit for row in flat}))
    at = {u: k for k, u in enumerate(units)}
    groups: list[list[int]] = []
    start = 0
    for found in kept:
        groups.append(list(range(start, start + len(found))))
        start += len(found)
    y = np.array([float(r.closed) for r in flat])
    weight = np.array([weights.get(found[0].group, 1.0) for found in kept])
    return _Archive(
        unit=np.array([at[r.unit] for r in flat], dtype=np.int64),
        offset=np.array([r.offset for r in flat]),
        buckets=tuple(_buckets(groups, y, weight)),
        units=units,
        groups=len(kept),
    )


def _unit_hessian(d: _Archive, blocks: Sequence[tuple[Ints, Floats]]) -> Floats:
    h = np.zeros((len(d.units), len(d.units)))
    for rows, cov in blocks:
        u = d.unit[rows]
        np.add.at(h, (u[:, :, None], u[:, None, :]), cov)
    return h


def _archive_at(d: _Archive, s: float, own: Floats, bound: float) -> tuple[float, Floats, Floats]:
    """The Laplace log marginal at spread ``s`` (own's prior N(0, s^2), the whole Hessian),
    own's mode and its posterior variances."""
    n = len(d.units)
    if s <= 0:
        ll, _, _ = _conditional(d.buckets, d.offset)
        return ll + _log_halfnormal(0.0), np.zeros(n), np.zeros(n)
    prec = 1.0 / (s * s)
    own = own.copy()
    for _ in range(100):
        ll, resid, blocks = _conditional(d.buckets, d.offset + own[d.unit])
        grad = np.bincount(d.unit, resid, n) - own * prec
        a = _unit_hessian(d, blocks) + prec * np.eye(n)
        step = np.clip(np.linalg.solve(a, grad), -1.0, 1.0)
        own = np.clip(own + step, -bound, bound)
        if float(np.max(np.abs(step))) < STEP_TOL:
            break
    ll, _, blocks = _conditional(d.buckets, d.offset + own[d.unit])
    h = _unit_hessian(d, blocks)
    _, logdet = np.linalg.slogdet(np.eye(n) + s * s * h)
    marginal = ll - float(own @ own) * prec / 2 - 0.5 * float(logdet) + _log_halfnormal(s)
    var = np.diag(np.linalg.inv(h + prec * np.eye(n)))
    return marginal, own, np.asarray(var, dtype=np.float64)


def _polish(
    at: Callable[[float, Floats], tuple[float, Floats, Floats]],
    s: float,
    own: Floats,
    bound: float,
    step: float,
) -> tuple[float, Floats, Floats]:
    """The registered grid's best ``s_own`` near the joint answer ``s``: each grid point within
    two steps of it, and 0, by its full Laplace marginal, each from the joint answer's own."""
    near = round(round(s / step) * step, 6)
    picks = sorted({0.0, *(round(near + k * step, 6) for k in range(-2, 3))})
    best: tuple[float, float, Floats, Floats] = (-math.inf, 0.0, own * 0, own * 0)
    for pick in picks:
        if pick < 0 or pick > bound + 1e-9:
            continue
        marginal, found, var = at(pick, own * (pick / s if s > 0 else 0.0))
        if marginal > best[0]:
            best = (marginal, pick, found, var)
    return best[1], best[2], best[3]


def _archive_search(d: _Archive, bound: float, step: float) -> tuple[float, Floats, Floats]:
    """``s_own`` on archive rows: the joint ascent of own's mode (a Newton step on the whole
    Hessian) and the spread of highest marginal with own and the Hessian's eigenvalues held,
    until both stand, then :func:`_polish` on the registered grid."""
    n = len(d.units)
    own, s = np.zeros(n), OWN_SCALE
    for _ in range(LIVE_ROUNDS):
        _, resid, blocks = _conditional(d.buckets, d.offset + own[d.unit])
        h = _unit_hessian(d, blocks)
        prec = 1.0 / (s * s)
        grad = np.bincount(d.unit, resid, n) - own * prec
        move = np.clip(np.linalg.solve(h + prec * np.eye(n), grad), -1.0, 1.0)
        own = np.clip(own + move, -bound, bound)
        moved = _spread_at(own, np.clip(np.linalg.eigvalsh(h), 0.0, None), bound)
        done = float(np.max(np.abs(move))) < LIVE_TOL and abs(moved - s) < LIVE_TOL
        s = moved
        if done:
            break
    return _polish(lambda pick, start: _archive_at(d, pick, start, bound), s, own, bound, step)


def _excluded(rows: Sequence[OwnRow], excluded: Collection[str]) -> tuple[list[OwnRow], int]:
    kept = [row for row in rows if row.unit not in excluded]
    return kept, len(rows) - len(kept)


def fit_own(
    rows: Sequence[OwnRow],
    *,
    bound: float = OWN_BOUND,
    step: float = SPREAD_STEP,
    excluded: Collection[str] = (),
    tempering: Tempering | None = None,
) -> OwnFit:
    """The own part on archive rows (see the module): the exact conditional likelihood within
    market-morning and class, each storm under ``tempering``; ``s_own`` the grid point of the
    highest Laplace marginal with its hyperprior, each unit with rows in a group of both
    outcomes its posterior ``(m, v)``; no such row, or ``s_own`` 0: no unit moves."""
    started = time.monotonic()
    use, dropped = _excluded(rows, excluded)
    d = _archive(use, group_weights(use, tempering))
    if not d.units:
        return OwnFit(0.0, {}, len(use), 0, time.monotonic() - started, dropped)
    with threadpool_limits(limits=1):  # small dense matrices: one thread is fastest, and safe
        s_hat, own_hat, var = _archive_search(d, bound, step)
    units = (
        {} if s_hat <= 0 else {u: (float(own_hat[k]), float(var[k])) for k, u in enumerate(d.units)}
    )
    return OwnFit(s_hat, units, len(use), d.groups, time.monotonic() - started, dropped)


# --- the live rows' likelihood (the anchor's, r4 9 step 1) ---


@dataclass(frozen=True, slots=True)
class LiveTerms:
    """What a live row's likelihood takes from the anchor of the run, per class: its market-day
    spread ``tau``, delay share ``q``, each tier's sensitivity and whether tier B enters, each
    list's sensitivity (its tier's Beta prior and its own co-listing trials) and the storm
    rule."""

    tau: Mapping[str, float]
    q: Mapping[str, float]
    tier_prior: Mapping[str, tuple[float, float]]
    tier_b: Collection[str]
    """The classes whose anchor fit lets tier B in (each class by its own fit's rule)."""
    lists: Mapping[str, float] = field(default_factory=dict)
    tempering: Tempering | None = None
    trials: Mapping[str, int] = field(default_factory=dict)
    """Each list's co-listing trials (a list with none sits at its tier's prior mean)."""
    delays: Collection[str] | None = None
    """The lists that post delays (honesty rule 3: a list that never names a delay says
    nothing about one, so its unnamed row takes no delay share); ``None``: every list takes
    its class's ``q``."""

    memo: dict[tuple[str, tuple[str, ...]], tuple[str | None, float]] = field(
        default_factory=dict, init=False, compare=False, repr=False
    )
    """Each (tier, lists) pair's :meth:`pick`, worked out once per fit."""

    def pick(self, row: OwnRow) -> tuple[str | None, float]:
        """The list whose sensitivity a row takes (the most sensitive that read it whole; a
        list with no trials at its tier's prior mean) and that sensitivity (the prior mean when
        no list read it)."""
        key = (row.tier, row.lists)
        found = self.memo.get(key)
        if found is None:
            prior = sensitivity(Trials(), self.tier_prior.get(row.tier, self.tier_prior["A"]))
            best = max(row.lists, key=lambda name: self.lists.get(name, prior), default=None)
            found = (best, prior if best is None else self.lists.get(best, prior))
            self.memo[key] = found
        return found

    def best(self, row: OwnRow) -> str | None:
        """The list whose sensitivity a row takes (:meth:`pick`)."""
        return self.pick(row)[0]

    def q_of(self, row: OwnRow) -> float:
        """The row's delay share: its class's ``q``, or 0 when the list it takes posts no
        delays (:attr:`delays`)."""
        if self.delays is None:
            return self.q[row.klass]
        best = self.best(row)
        return self.q[row.klass] if best is not None and best in self.delays else 0.0

    def no_trial(self, row: OwnRow) -> bool:
        """Whether the list a row takes has no co-listing trials (or no list read it)."""
        best = self.best(row)
        return best is None or self.trials.get(best, 0) == 0

    def uses(self, row: OwnRow) -> bool:
        """Tier A, and tier B only under the anchor's tier B rule of the row's own class
        (Addendum B1.5)."""
        return row.klass in self.tau and (
            row.tier == "A" or (row.tier == "B" and row.klass in self.tier_b)
        )

    def s_of(self, row: OwnRow) -> float:
        """The row's sensitivity: the most sensitive list that read it whole (one list per row,
        as the anchor registers; a list with no trials at its tier's prior mean)."""
        return self.pick(row)[1]

    @classmethod
    def of(
        cls,
        anchor: "Anchor",
        lists: Mapping[str, Sequence[object]],
        delays: Collection[str] | None = None,
    ) -> "LiveTerms":
        """From the run's anchor, each list's ``[tier, hits, trials]`` and the lists that post
        delays."""
        settings = anchor.settings
        fits = {k: anchor.fits[k] for k in CLASSES if k in anchor.fits}
        priors = {"A": settings.tier_a_prior, "B": settings.tier_b_prior}
        tier_b = frozenset(k for k, f in fits.items() if f.tier_b)
        per_list: dict[str, float] = {}
        trials: dict[str, int] = {}
        for name, (tier, hits, count) in sorted(lists.items()):
            prior = priors.get(str(tier), priors["A"])
            per_list[name] = sensitivity(Trials(int(str(hits)), int(str(count))), prior)
            trials[name] = int(str(count))
        start = {
            k: (f.ramp.start.alpha if f.ramp is not None else f.prior.alpha_mean)
            for k, f in fits.items()
        }
        return cls(
            tau={k: f.tau for k, f in fits.items()},
            q={k: f.q for k, f in fits.items()},
            tier_prior=priors,
            tier_b=tier_b,
            lists=per_list,
            tempering=Tempering.of(settings, start) if set(start) == set(CLASSES) else None,
            trials=trials,
            delays=None if delays is None else frozenset(delays),
        )


def solve_fast(base: Floats, var: Floats) -> Floats:
    """``x`` with ``E[sigmoid(x + b)] = base``, ``b ~ N(0, var)`` (elementwise), by Newton
    from the probit-style start, to 1e-9 in probability (:func:`solve_base`'s answer, faster)."""
    target = np.clip(base, LOW, 1.0 - LOW)
    x = np.log(target / (1 - target)) * np.sqrt(1.0 + math.pi * var / 8.0)
    sd = np.sqrt(np.maximum(var, 0.0))[:, None]
    for _ in range(50):
        s = _sigmoid(x[:, None] + sd * _Z)
        got = s @ _W
        slope = (s * (1 - s)) @ _W
        move = np.clip((got - target) / np.maximum(slope, 1e-12), -4.0, 4.0)
        x = x - move
        if float(np.max(np.abs(got - target))) < BASE_TOL * 0.1:
            break
    return np.asarray(x, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class _Live:
    unit: Ints
    group: Ints
    starts: Ints
    x: Floats
    a: Floats
    b: Floats
    tau: Floats
    weight: Floats
    units: tuple[str, ...]


def _live(rows: Sequence[OwnRow], terms: LiveTerms, weights: Mapping[str, float]) -> _Live:
    order = sorted(rows, key=lambda r: (r.group, r.unit))
    units = tuple(sorted({row.unit for row in order}))
    at = {u: k for k, u in enumerate(units)}
    names = sorted({row.group for row in order})
    g_at = {g: k for k, g in enumerate(names)}
    group = np.array([g_at[r.group] for r in order], dtype=np.int64)
    first: dict[str, str] = {}
    for r in order:
        first.setdefault(r.group, r.klass)
    tau_g = np.array([terms.tau[first[g]] for g in names], dtype=np.float64)
    s = np.array([terms.s_of(r) for r in order])
    q = np.array([terms.q_of(r) for r in order])
    base = 1.0 / (1.0 + np.exp(-np.array([r.offset for r in order])))
    tau_row = tau_g[group] if names else np.zeros(0)
    return _Live(
        unit=np.array([at[r.unit] for r in order], dtype=np.int64),
        group=group,
        starts=np.array(
            [k for k in range(len(order)) if k == 0 or group[k] != group[k - 1]], dtype=np.int64
        ),
        x=solve_fast(base, tau_row**2) if order else np.zeros(0),
        a=np.array(
            [
                -1.0 if r.label == "no_school" else 1.0 if r.label == "delayed" else sk * (1 - qk)
                for r, sk, qk in zip(order, s, q, strict=True)
            ]
        ),
        b=np.array(
            [
                0.0 if r.label == "no_school" else 1.0 if r.label == "delayed" else 1 - sk * qk
                for r, sk, qk in zip(order, s, q, strict=True)
            ]
        ),
        tau=tau_g,
        weight=np.array([weights.get(g, 1.0) for g in names]),
        units=units,
    )


def _live_pieces(d: _Live, own: Floats) -> tuple[float, Floats, Floats]:
    """The weighted log marginal likelihood over each market-day's effect, and each row's
    weighted score and information in its unit's part (the diagonal of the Hessian: units
    meet only through a market-day's effect). Every label's row likelihood is ``B - A p``:
    ``no_school`` ``p`` (``A`` -1, ``B`` 0), ``delayed`` ``1 - p``, ``unnamed``
    ``1 - s q - s (1 - q) p``."""
    eta = (d.x + own[d.unit])[:, None] + d.tau[d.group][:, None] * _Z[None, :]
    p = _sigmoid(eta)
    f = np.maximum(d.b[:, None] - d.a[:, None] * p, TINY)
    ratio = d.a[:, None] * (p * (1 - p)) / f
    by = np.add.reduceat(np.log(f), d.starts, axis=0) + _LOG_W[None, :]
    total = _logsumexp(by, axis=1)
    post = np.exp(by - total[:, None])[d.group]
    weighted = post * ratio
    g = -weighted.sum(axis=1)
    h = (weighted * (1 - 2 * p)).sum(axis=1) + g * g
    w = d.weight[d.group]
    return float(np.sum(d.weight * total)), w * g, w * np.maximum(h, 1e-12)


def _live_at(d: _Live, s: float, own: Floats, bound: float) -> tuple[float, Floats, Floats]:
    n = len(d.units)
    if s <= 0:
        ll, _, _ = _live_pieces(d, np.zeros(n))
        return ll + _log_halfnormal(0.0), np.zeros(n), np.zeros(n)
    prec = 1.0 / (s * s)
    own = own.copy()
    for _ in range(100):
        _, g, h = _live_pieces(d, own)
        grad = np.bincount(d.unit, g, n) - own * prec
        info = np.bincount(d.unit, h, n) + prec
        step = np.clip(grad / info, -1.0, 1.0)
        own = np.clip(own + step, -bound, bound)
        if float(np.max(np.abs(step))) < STEP_TOL:
            break
    ll, _, h = _live_pieces(d, own)
    info = np.bincount(d.unit, h, n)
    marginal = (
        ll - float(own @ own) * prec / 2 - 0.5 * float(np.sum(np.log1p(s * s * info)))
    ) + _log_halfnormal(s)
    return marginal, own, 1.0 / (info + prec)


def _spread_at(own: Floats, info: Floats, bound: float) -> float:
    """The spread of highest Laplace marginal for ``own`` and each unit's information held
    (the joint step: its derivative is the marginal's at the mode), on a 0.005 grid."""
    grid = np.arange(0.005, bound + 1e-9, 0.005)
    total = float(own @ own)
    value = (
        -total / (2 * grid**2)
        - 0.5 * np.log1p(grid[:, None] ** 2 * info[None, :]).sum(axis=1)
        - grid**2 / (2 * OWN_SCALE**2)
    )
    return float(grid[int(np.argmax(value))])


def _live_search(d: _Live, bound: float, step: float) -> tuple[float, Floats, Floats]:
    """``s_own`` on the registered grid: first the joint ascent of own's mode and the spread
    (a Newton step of own, then the spread of highest marginal with own held, until both
    stand), then each grid point within two steps of it, and 0, by the full Laplace marginal
    (:func:`_live_at`), each from the joint answer's own."""
    n = len(d.units)
    own, s = np.zeros(n), OWN_SCALE
    for _ in range(LIVE_ROUNDS):
        _, g, h = _live_pieces(d, own)
        info = np.bincount(d.unit, h, n)
        prec = 1.0 / (s * s)
        move = np.clip((np.bincount(d.unit, g, n) - own * prec) / (info + prec), -1.0, 1.0)
        own = np.clip(own + move, -bound, bound)
        moved = _spread_at(own, info, bound)
        if float(np.max(np.abs(move))) < LIVE_TOL and abs(moved - s) < LIVE_TOL:
            s = moved
            break
        s = moved
    return _polish(lambda pick, start: _live_at(d, pick, start, bound), s, own, bound, step)


def fit_live(
    rows: Sequence[OwnRow],
    terms: LiveTerms,
    *,
    bound: float = OWN_BOUND,
    step: float = SPREAD_STEP,
    excluded: Collection[str] = (),
) -> OwnFit:
    """The own part on live rows (see the module): the anchor's row likelihood with each row's
    lists' sensitivity and the class's delay share, the market-day effect integrated, each
    storm under the anchor's rule; ``s_own`` and each unit's ``(m, v)`` as :func:`fit_own`."""
    started = time.monotonic()
    use, dropped = _excluded(rows, excluded)
    use = [row for row in use if row.label in LIVE_LABELS and terms.uses(row)]
    if not use:
        return OwnFit(0.0, {}, 0, 0, time.monotonic() - started, dropped)
    d = _live(use, terms, group_weights(use, terms.tempering))
    s_hat, own_hat, var = _live_search(d, bound, step)
    units = (
        {} if s_hat <= 0 else {u: (float(own_hat[k]), float(var[k])) for k, u in enumerate(d.units)}
    )
    return OwnFit(s_hat, units, len(use), len(d.tau), time.monotonic() - started, dropped)


def posting_delays(rows: Iterable[OwnRow]) -> frozenset[str]:
    """The lists that read a ``delayed`` row whole (honesty rule 3's lists that post delays)."""
    return frozenset(name for row in rows if row.label == "delayed" for name in row.lists)


@dataclass(frozen=True, slots=True)
class LiveChecks:
    """The live fit's own checks (honesty rule 2 and 11(g)): the rows the fit read whose list
    has no co-listing trials (it sits at its tier's prior mean, so a list that names few of
    its closings reads its districts as holding out), each unit's share of them, the units
    read by no other list (open to that bias until a trial reads their list), and 11(g)'s
    report of the own part against each unit's list sensitivity and no-trial share."""

    rows: int = 0
    no_trial_rows: int = 0
    open_units: tuple[str, ...] = ()
    share: Mapping[str, float] = field(default_factory=dict)
    misattribution: Mapping[str, tuple[int, float, float, float]] = field(default_factory=dict)
    flagged: tuple[str, ...] = ()

    def as_json(self) -> dict[str, object]:
        return {
            "rows": self.rows,
            "no_trial_rows": self.no_trial_rows,
            "open_units": list(self.open_units),
            "share": {u: round(v, 4) for u, v in sorted(self.share.items())},
            "misattribution": {
                k: [n, round(r, 4), round(lo, 4), round(hi, 4)]
                for k, (n, r, lo, hi) in sorted(self.misattribution.items())
            },
            "flagged": list(self.flagged),
        }


def live_traits(rows: Sequence[OwnRow], terms: LiveTerms) -> dict[str, dict[str, float]]:
    """Each unit's list sensitivity (the mean over its rows of the list each takes) and its
    no-trial share, the traits 11(g) runs the live fit against."""
    s: dict[str, list[float]] = {}
    none: dict[str, list[float]] = {}
    for row in rows:
        s.setdefault(row.unit, []).append(terms.s_of(row))
        none.setdefault(row.unit, []).append(1.0 if terms.no_trial(row) else 0.0)
    return {
        "list sensitivity": {u: sum(v) / len(v) for u, v in s.items()},
        "no-trial share": {u: sum(v) / len(v) for u, v in none.items()},
    }


def live_checks(
    rows: Sequence[OwnRow], terms: LiveTerms, own: OwnFit, excluded: Collection[str] = ()
) -> LiveChecks:
    """:class:`LiveChecks` of the rows :func:`fit_live` read."""
    from snowlight.predict import backtest_lines  # noqa: PLC0415 - it imports this module

    use = [
        row for row in rows
        if row.unit not in excluded and row.label in LIVE_LABELS and terms.uses(row)
    ]  # fmt: skip
    traits = live_traits(use, terms)
    share = traits["no-trial share"]
    found = backtest_lines.misattribution(own, traits)
    return LiveChecks(
        rows=len(use),
        no_trial_rows=sum(1 for row in use if terms.no_trial(row)),
        open_units=tuple(sorted(u for u, v in share.items() if v >= 1.0)),
        share=share,
        misattribution=found,
        flagged=tuple(backtest_lines.flagged(found)),
    )


# --- the live rows (labels and the frozen record) ---------------------------------------------


def group_of(day: date, market: str | None, unit: str, klass: str) -> str:
    """A row's market-morning-and-class group (a district with no market is its own)."""
    return f"{day.isoformat()}|{market if market is not None else '~' + unit}|{klass}"


def live_rows(
    labeled: Sequence[LiveRow],
    frozen_rows: Sequence[Mapping[str, object]],
    *,
    class_of: Callable[[str], str | None],
    lists: Mapping[str, Sequence[str]] | None = None,
    excluded: Collection[str] = (),
) -> list[OwnRow]:
    """One labeled day's rows a fit may read: each labeled district served an advisory or
    warning chance from the model at the 20:07 freeze (not said open, its row's lines as
    :func:`snowlight.predict.frozen.freeze_lines` gives them), its offset that unrounded
    chance's log odds, with its L1 label, tier and the lists that read it whole. Left out: a
    unit honesty rule 4 names, a day-after row (rule 10), and a row whose L1 class of the day
    is not its served class (the bus switch's rule)."""
    frozen_at: dict[str, tuple[str, float]] = {}
    for row in frozen_rows:
        p, klass = row.get("pr"), row.get("c")
        if row.get("s") != 1 or row.get("sa") or klass not in CLASSES:
            continue
        if not isinstance(p, float) or not 0.0 < p < 1.0:
            continue
        frozen_at[str(row["l"])] = (str(klass), p)
    found: list[OwnRow] = []
    for label in labeled:
        if label.district in excluded or label.weather.endswith("_after"):
            continue
        served_as = frozen_at.get(label.district)
        if served_as is None or class_of(label.weather) != served_as[0]:
            continue
        klass, p = served_as
        p = min(max(p, 1e-6), 1 - 1e-6)
        found.append(
            OwnRow(
                unit=label.district,
                day=label.day,
                group=group_of(label.day, label.market, label.district, klass),
                klass=klass,
                offset=math.log(p / (1 - p)),
                closed=label.label == "no_school",
                label=label.label,
                tier=label.tier,
                lists=tuple(sorted((lists or {}).get(label.district, ()))),
            )
        )
    return found


# --- R-KYY and M5y (Kentucky's years) ---------------------------------------------------------


def school_year(day: date, back: int = 0) -> str:
    """The school year a day is in (from July 1): ``2025-26``; with ``back``, that many years
    before it."""
    start = (day.year if day.month >= 7 else day.year - 1) - back  # noqa: PLR2004 - July
    return f"{start}-{(start + 1) % 100:02d}"


KY_FIRST: Final = "2021-22"
"""The first school year of Kentucky's W counts any ``t`` reads (the registered window: for the
gate fold, 2021-22 to 2023-24; COVID's 2019-20 and 2020-21 never): the nightly M5y's R-KYY reads
the same years as the fold the gate judges."""


@dataclass(frozen=True, slots=True)
class KyInputs:
    """What R-KYY gives a fit: each Kentucky district's weather day count per school year (the
    days known to be the weather's: ``days - not_weather - unconfirmed`` where checked, else
    ``days``) and its dated W days, every one of a school year before ``before``."""

    before: str
    counts: Mapping[tuple[str, str], int]
    dated: tuple[tuple[str, date, str], ...]
    """``(unit, day, class)`` of each dated W day (class ``unknown`` until the backfill)."""


def read_kyy(kept: Mapping[str, bytes], served_day: date) -> KyInputs:
    """R-KYY (lead ruling LR21): the record kind's Kentucky ``YearCount`` rows of code W and its
    dated W ``PastDay`` rows, read only, each newest edition, every one of a school year before
    the served day's (a later year never reaches a fit, a served chance or a gate; the 2024-25
    cross-fit is :func:`snowlight.predict.backtest_lines.ky_cross_fit`'s, reported only), and
    each count of :data:`KY_FIRST` or later."""
    before = school_year(served_day)
    counts: dict[tuple[str, str], int] = {}
    for count in record_kind.kept_counts(kept):
        if count.code != "W" or not count.unit.startswith(KENTUCKY) or count.year >= before:
            continue
        if count.year < KY_FIRST:  # the gate fold's window, so the shadow arm is the gated one
            continue
        if count.covid or count.disaster:
            continue
        known = count.days - (count.not_weather or 0) - (count.unconfirmed or 0)
        counts[(count.unit, count.year)] = known
    past = {key: data for key, data in kept.items() if key.startswith(record_kind.PAST_PREFIX)}
    dated: list[tuple[str, date, str]] = []
    newest = record_kind.newest_past(past, record_kind.PAST_DAYS, record_kind.past_days_of)
    for _key, rows in newest:
        for row in rows:
            if row.code != "W" or not row.unit.startswith(KENTUCKY) or not row.weather_day:
                continue
            if school_year(row.day) >= before or row.day >= served_day:
                continue
            dated.append((row.unit, row.day, str(row.klass)))
    return KyInputs(before, dict(sorted(counts.items())), tuple(sorted(dated)))


@dataclass(frozen=True, slots=True)
class Tendency:
    """Each Kentucky district's count tendency ``t`` (posterior mean and variance) and its
    spread ``s_t`` and the district-year spread ``s_e``."""

    s_t: float
    s_e: float
    units: Mapping[str, tuple[float, float]]


def fit_tendency(counts: Mapping[tuple[str, str], int], exposure: Mapping[str, float]) -> Tendency:
    """The count tendency (r4 3 rule 9, as a Gaussian on the log scale): each district-year's
    ``r = ln((C + 0.5) / (E g_y))``, ``E`` the district's expected class days a year
    (``exposure``), ``g_y`` the state-year's level, is ``t + e + noise`` with the noise's
    variance ``1 / (C + 0.5)``; ``s_t`` and ``s_e`` by the marginal likelihood on a grid. A
    district with no exposure is left out."""
    years: dict[str, list[tuple[str, int]]] = {}
    for (unit, year), c in counts.items():
        if exposure.get(unit, 0.0) > 0:
            years.setdefault(year, []).append((unit, c))
    by: dict[str, list[tuple[float, float]]] = {}
    for entries in years.values():
        total_c = sum(c for _, c in entries) + 0.5 * len(entries)
        total_e = sum(exposure[u] for u, _ in entries)
        level = total_c / total_e
        for u, c in entries:
            by.setdefault(u, []).append(
                (math.log((c + 0.5) / (exposure[u] * level)), 1.0 / (c + 0.5))
            )
    if not by:
        return Tendency(0.0, 0.0, {})
    names = sorted(by)
    at = np.array([k for k, u in enumerate(names) for _ in by[u]], dtype=np.int64)
    r = np.array([x for u in names for x, _ in by[u]])
    noise = np.array([n for u in names for _, n in by[u]])
    grid = np.round(np.arange(0.0, 1.51, 0.05), 6)
    best: tuple[float, float, float] = (-math.inf, 0.0, 0.0)
    for spread_t in grid:
        for spread_e in grid:
            # each district's covariance is diag(noise + s_e^2) + s_t^2 J: Sherman-Morrison
            d = noise + spread_e * spread_e
            a = np.bincount(at, 1.0 / d, len(names))
            b = np.bincount(at, r / d, len(names))
            q = np.bincount(at, r * r / d, len(names))
            one = 1.0 + spread_t * spread_t * a
            logdet = float(np.sum(np.log(d))) + float(np.sum(np.log(one)))
            quad = float(np.sum(q - spread_t * spread_t * b * b / one))
            ll = -0.5 * (logdet + quad)
            if ll > best[0]:
                best = (ll, float(spread_t), float(spread_e))
    _, s_t, s_e = best
    units: dict[str, tuple[float, float]] = {}
    for name in names:
        prec = sum(1.0 / (n + s_e * s_e) for _, n in by[name])
        if s_t <= 0:
            units[name] = (0.0, 0.0)
            continue
        var = 1.0 / (prec + 1.0 / (s_t * s_t))
        units[name] = (var * sum(x / (n + s_e * s_e) for x, n in by[name]), var)
    return Tendency(s_t, s_e, units)


@dataclass(frozen=True, slots=True)
class Slope:
    """The Kentucky slope ``beta`` and its variance (``None``: no rows K to fit it on)."""

    beta: float | None
    var: float
    rows: int
    why: str | None = None


def fit_slope(
    rows: Sequence[OwnRow],
    tendency: Mapping[str, tuple[float, float]],
    *,
    tempering: Tempering | None = None,
) -> Slope:
    """``beta`` on rows K (dated W days of a known class against the class days of districts not
    listed, each row's offset its replay's) by the exact conditional likelihood within date and
    class (the storm-picked level drops out, with no fixed effect per group), the covariate each
    district's ``t`` from years before the row's: Newton on ``beta``."""
    use = [row for row in rows if row.unit in tendency and row.klass in CLASSES]
    d = _archive(use, group_weights(use, tempering))
    if not d.groups:
        return Slope(None, 0.0, 0, "no rows K of a known class")
    t = np.array([tendency[u][0] for u in d.units])[d.unit]
    beta, info = 0.0, 0.0
    for _ in range(100):
        _, resid, blocks = _conditional(d.buckets, d.offset + beta * t)
        info = sum(float(np.einsum("bi,bij,bj->", t[r], cov, t[r])) for r, cov in blocks)
        if info <= 0:
            return Slope(None, 0.0, len(use), "no spread of t within a group")
        step = float(resid @ t) / info
        beta += max(min(step, 1.0), -1.0)
        if abs(step) < STEP_TOL:
            break
    return Slope(beta, 1.0 / info, len(use))


@dataclass(frozen=True, slots=True)
class KyFit:
    """M5y's parts: each Kentucky district's own mean and variance and its prior variance."""

    v0: float
    units: Mapping[str, tuple[float, float]]
    why: str | None = None


def ky_fit(tendency: Tendency, slope: Slope) -> KyFit:
    """``own = beta t`` with its variance from both (3.2: prior variance ``(beta^2 + var(beta))
    s_t^2``); off (``why``) while there is no slope."""
    if slope.beta is None:
        return KyFit(0.0, {}, slope.why)
    b, vb = slope.beta, slope.var
    units = {u: (b * t, b * b * v + t * t * vb + v * vb) for u, (t, v) in tendency.units.items()}
    return KyFit((b * b + vb) * tendency.s_t**2, units)


# --- the nightly fit and the shadow arms ------------------------------------------------------


def next_window(at: datetime) -> datetime:
    """The first 19:30 UTC after ``at``."""
    hour = datetime.combine(at.astimezone(UTC).date(), datetime.min.time(), UTC).replace(
        hour=SWITCH_HOUR[0], minute=SWITCH_HOUR[1]
    )
    return hour if at < hour else hour + timedelta(days=1)


@dataclass
class Shadow:
    """The shadow arms a pass writes (:class:`snowlight.predict.frozen.EsArms`), from the
    nightly fit kept in ``folder`` (``fit.json``), made again by :meth:`refresh`."""

    folder: Path = frozen.ES_FOLDER
    reads: Path | None = None
    """L1's private record (``live_read.READS_DIR``; ``None``: no live labels)."""
    since: date | None = None
    """The first labeled day the ledger takes (``live_update.fit_from``)."""
    learn: "LearnSettings | None" = None
    """The take-back lists (``config.learn``), as the anchor drops them."""
    class_of: Mapping[str, str] = field(default_factory=dict)
    """A situation key to its class (``live_score.classes``)."""
    frozen_folder: Path = frozen.FOLDER
    kyy_store: Callable[[], AbstractContextManager[Any]] | None = None
    """Opens the evidence store for R-KYY's pull (``None``: no store; M5y writes nothing). It
    is a store, not a pull: the store refuses the record kind to every read without this
    module's capability (:class:`_RecordRead`, lead ruling LR-P6A-1), so what it opens yields
    no record row to any other caller; only :meth:`_fit` opens it, and reads it through
    :func:`store_past` with the capability."""
    exposure: Mapping[str, float] = field(default_factory=dict)
    """Each district's expected advisory and warning days a year (M5y's ``E``)."""
    excluded: frozenset[str] = frozenset()
    """The units honesty rule 4 names (``each_school.own_excluded``): never in a fit."""
    take_up: int = TAKE_UP_DAYS
    say: Callable[[str], None] = lambda _line: None
    own: OwnFit | None = None
    ky: KyFit | None = None
    computed: datetime | None = None
    failed: datetime | None = None
    """When the last nightly fit failed (none is tried again before :func:`next_window`)."""
    ledger: list[OwnRow] = field(default_factory=list)
    checks: LiveChecks | None = None
    """The last fit's :class:`LiveChecks` (kept in ``fit.json``; ``None`` before a fit)."""
    entered: dict[str, str] = field(default_factory=dict)
    """Each labeled day the ledger took up: ``taken``, ``absent`` (its frozen day released or
    too old to come back), ``excluded`` (a take-back day) or ``unread``."""
    lists: dict[str, list[object]] = field(default_factory=dict)
    """Each list's ``[tier, hits, trials]`` over the taken-up days in the ledger's window
    (:meth:`window`): the sum of :attr:`day_lists`."""
    day_lists: dict[str, dict[str, list[object]]] = field(default_factory=dict)
    """Each taken-up day's lists' ``[tier, hits, trials]``, dropped with the ledger's days."""
    loaded: bool = False

    @property
    def arms(self) -> tuple[str, ...]:
        return WRITTEN

    @property
    def fit(self) -> str | None:
        return None if self.computed is None else self.computed.isoformat()

    def due(self, now: datetime) -> bool:
        """Whether a pass at ``now`` makes the fit again: none yet, one older than
        :data:`MAX_AGE`, or none since today's 19:30 UTC once it has passed; never before the
        next 19:30 UTC after a fit that failed."""
        self.load()
        if self.failed is not None and now < next_window(self.failed):
            return False
        if self.computed is None or now - self.computed > MAX_AGE:
            return True
        return now >= next_window(self.computed)

    def refresh(self, now: datetime, anchor: "Anchor | None" = None) -> bool:
        """Take up at most :attr:`take_up` labeled days into the ledger (one on the pass that
        makes the fit, so the step stays in :data:`FIT_BUDGET` with a margin), and make the
        nightly fit when it is due (:meth:`due`) from the run's ``anchor``: keep it and say it
        in one line; whether it was made. It never raises: a step that fails is said in one
        line, the last fit kept, and a failed fit is not tried again before the next 19:30 UTC."""
        started = time.monotonic()
        try:
            self.load()  # the kept ledger first: a day it holds is never read again
            due = self.due(now)
            took = self._take_up(now, min(1, self.take_up) if due else self.take_up)
            if took and not due:
                self.save()
        except Exception as error:  # the shadow never touches the pass
            self.say(f"predict lines: the ledger's take-up: {type(error).__name__}: the last kept")
            return False
        if not due:
            self._over(time.monotonic() - started)
            return False
        try:
            self._fit(now, anchor)
        except Exception as error:  # the shadow never touches the pass
            self.failed = now
            self._mark_failed()
            self.say(
                f"predict lines: the nightly fit: {type(error).__name__}: the last kept, "
                f"tried again from {next_window(now):%Y-%m-%d %H:%MZ}"
            )
            return False
        seconds = time.monotonic() - started
        self._over(seconds)
        own = self.own or OwnFit(0.0, {})
        ky = "" if self.ky is None else f", m5y {len(self.ky.units)} districts"
        why = "" if self.ky is None or self.ky.why is None else f" (m5y off: {self.ky.why})"
        checks = self.checks or LiveChecks()
        flags = ", ".join(checks.flagged) or "none"
        self.say(
            f"predict lines: fit {now:%Y-%m-%d %H:%MZ} in {seconds:.2f} s: {len(self.ledger):,} "
            f"rows, {own.groups:,} market-mornings, s_own {own.spread:.2f}, {len(own.units):,} "
            f"districts read, {len(self.excluded):,} units excluded ({own.excluded:,} rows), "
            f"{checks.no_trial_rows:,} rows on a list with no trials ({len(checks.open_units):,} "
            f"districts on no other), 11(g) flags {flags}, {took} days taken up{ky}{why}"
        )
        return True

    def _over(self, seconds: float) -> None:
        if seconds > FIT_BUDGET:
            self.say(
                f"::warning::predict lines: the nightly step took {seconds:.1f} s, over its "
                f"{FIT_BUDGET:.0f} s of the pass"
            )

    def _fit(self, now: datetime, anchor: "Anchor | None") -> None:
        if anchor is None:
            raise ValueError("no anchor this pass")
        served_day = now.astimezone(UTC).date()
        self.window(served_day)
        rows = drop_served(self.ledger, served_day)
        terms = LiveTerms.of(anchor, self.lists, posting_delays(rows))
        own = fit_live(rows, terms, excluded=self.excluded)
        self.checks = live_checks(rows, terms, own, self.excluded)
        ky: KyFit
        rows_k = _rows_k()
        if rows_k is None:
            ky = KyFit(0.0, {}, "rows K need each district's class days (not built)")
        elif not _own(_rows_k) or not _own(rows_k):
            ky = KyFit(0.0, {}, f"rows K refused: not {__name__}'s own")
        elif self.kyy_store is None:
            ky = KyFit(0.0, {}, "no evidence store")
        else:
            try:
                with self.kyy_store() as store:
                    inputs = read_kyy(store_past(store, _READ), served_day)
            except Exception as error:  # the store is down: M5y waits, M5o is made all the same
                ky = KyFit(0.0, {}, f"R-KYY's pull failed ({type(error).__name__})")
            else:
                tendency = fit_tendency(inputs.counts, self.exposure)
                slope = fit_slope(drop_served(rows_k(inputs), served_day), tendency.units)
                ky = ky_fit(tendency, slope)
        self.own, self.ky, self.computed, self.failed = own, ky, now, None
        self.save()
        (self.folder / FAILED_NAME).unlink(missing_ok=True)

    def _take_up(self, now: datetime, most: int) -> int:
        """At most ``most`` labeled days before the served day, each once, in day order, from
        their 20:07 freeze. A day whose frozen day is still to come, or missing while the
        evidence step may restore it, waits."""
        if self.reads is None:
            return 0
        from snowlight.predict import anchor_labels  # noqa: PLC0415

        served_day = now.astimezone(UTC).date()
        index = frozen.load_index(self.frozen_folder)
        oldest = served_day - timedelta(days=frozen.RESTORE_DAYS)
        taken = 0
        for day in anchor_labels.labeled_days(self.reads, self.since):
            key = day.isoformat()
            if day >= served_day or key in self.entered:
                continue
            if taken >= most:
                break
            if key in index.done or (key not in index.days and day < oldest):
                self.entered[key] = "absent"
                continue
            how, found = frozen.freeze_lines(self.frozen_folder, day, FIT_FREEZE, index)
            if how != "ready" or found is None:
                continue  # wait, or missing: the evidence step may restore it
            taken += 1
            try:
                read = anchor_labels.day_lists(self.reads, day, self.learn)
            except (OSError, ValueError, KeyError, TypeError):
                self.entered[key] = "unread"
                continue
            if read is None:
                self.entered[key] = "excluded"
                continue
            labeled, sources, trials = read
            self.ledger.extend(
                live_rows(
                    labeled,
                    found,
                    class_of=self.class_of.get,
                    lists=sources,
                    excluded=self.excluded,
                )
            )
            self.day_lists[key] = {
                name: [tier, hits, count] for name, (tier, hits, count) in sorted(trials.items())
            }
            self.entered[key] = "taken"
        if taken:
            self.window(served_day)
        return taken

    def window(self, served_day: date) -> int:
        """Keep the ledger to its window: the rows of :data:`LEDGER_WINTERS` school years to
        the served day's, and at most :data:`LEDGER_ROWS`, its oldest days going whole; the
        rows dropped (their days stay entered, so none is taken up again). Each list's trials
        are kept to the same days (:attr:`lists`)."""
        first = school_year(served_day, LEDGER_WINTERS - 1)
        kept = [row for row in self.ledger if school_year(row.day) >= first]
        if len(kept) > LEDGER_ROWS:
            days = Counter(row.day for row in kept)
            left, cut = len(kept), date.min
            for day in sorted(days):
                if left <= LEDGER_ROWS:
                    break
                left -= days[day]
                cut = day
            kept = [row for row in kept if row.day > cut]
        else:
            cut = date.min
        dropped = len(self.ledger) - len(kept)
        self.ledger = kept
        self.day_lists = {
            key: found
            for key, found in self.day_lists.items()
            if school_year(date.fromisoformat(key)) >= first and date.fromisoformat(key) > cut
        }
        self.lists = summed_lists(self.day_lists)
        return dropped

    def save(self) -> None:
        own = self.own or OwnFit(0.0, {})
        body = {
            "schema": FIT_SCHEMA,
            "computed": self.fit,
            "spread": own.spread,
            "units": {u: [round(m, 6), round(v, 6)] for u, (m, v) in sorted(own.units.items())},
            "rows": own.rows,
            "groups": own.groups,
            "excluded": own.excluded,
            "seconds": round(own.seconds, 3),
            "m5y": None
            if self.ky is None
            else {
                "v0": self.ky.v0,
                "why": self.ky.why,
                "units": {
                    u: [round(m, 6), round(v, 6)] for u, (m, v) in sorted(self.ky.units.items())
                },
            },
            "checks": None if self.checks is None else self.checks.as_json(),
            "entered": dict(sorted(self.entered.items())),
            "day_lists": dict(sorted(self.day_lists.items())),
            "ledger": [row.as_json() for row in self.ledger],
        }
        self.folder.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(self.folder / FIT_NAME, json.dumps(body, sort_keys=True).encode())

    def _mark_failed(self) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            write_bytes_atomic(
                self.folder / FAILED_NAME,
                json.dumps(
                    {"failed": None if self.failed is None else self.failed.isoformat()}
                ).encode(),
            )
        except OSError:
            return

    def load(self) -> None:
        """The kept fit, once per process (none, or one of another schema, or one that does
        not read or is not the shape this writes: none, and the ledger begins afresh)."""
        if self.loaded:
            return
        self.loaded = True
        try:
            failed: Any = json.loads((self.folder / FAILED_NAME).read_bytes())
            self.failed = datetime.fromisoformat(str(failed["failed"]))
        except Exception:  # no mark, or one that does not read: none
            self.failed = None
        try:
            body: Any = json.loads((self.folder / FIT_NAME).read_bytes())
        except (OSError, ValueError):
            return
        if not isinstance(body, dict) or body.get("schema") != FIT_SCHEMA:
            return
        try:
            units = {str(u): (float(m), float(v)) for u, (m, v) in body["units"].items()}
            own = OwnFit(
                float(body["spread"]), units, int(body["rows"]), int(body["groups"]),
                excluded=int(body.get("excluded", 0)),
            )  # fmt: skip
            found = body.get("m5y")
            ky = (
                None
                if found is None
                else KyFit(
                    float(found["v0"]),
                    {str(u): (float(m), float(v)) for u, (m, v) in found["units"].items()},
                    None if found.get("why") is None else str(found["why"]),
                )
            )
            computed = (
                None if body.get("computed") is None else datetime.fromisoformat(body["computed"])
            )
            entered = {str(k): str(v) for k, v in body.get("entered", {}).items()}
            day_lists: dict[str, dict[str, list[object]]] = {
                str(day): {str(k): [str(v[0]), int(v[1]), int(v[2])] for k, v in found.items()}
                for day, found in body["day_lists"].items()
            }
            ledger = [OwnRow.of(row) for row in body.get("ledger", [])]
        except Exception:  # a kept fit of the wrong shape is no fit
            return
        self.own, self.ky, self.computed = own, ky, computed
        self.entered, self.day_lists, self.ledger = entered, day_lists, ledger
        self.lists = summed_lists(day_lists)

    def lines(self, rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
        """Each served advisory or warning row's arm chances (:data:`WRITTEN`), from its frozen
        unrounded chance as the base; none before a fit."""
        self.load()
        if self.own is None:
            return []
        picked: list[tuple[str, float]] = []
        for row in rows:
            p = row.get("pr")
            if row.get("s") != 1 or row.get("c") not in CLASSES or row.get("sa"):
                continue
            if not isinstance(p, float) or not 0.0 < p < 1.0:
                continue
            picked.append((str(row["l"]), p))
        return [
            {"l": unit, "es": [frozen.es_round(v) if v is not None else None for v in values]}
            for (unit, _), values in zip(picked, self.chances(picked), strict=True)
        ]

    def chances(self, picked: Sequence[tuple[str, float]]) -> list[tuple[float | None, ...]]:
        """Each ``(unit, base)``'s chance under each written arm (``None``: no part for it),
        worked out for the whole freeze at once over arrays; a unit at its prior keeps its
        base exactly."""
        own = self.own or OwnFit(0.0, {})
        m5o: list[float] = [base for _, base in picked]
        moved = [k for k, (unit, _) in enumerate(picked) if unit in own.units]
        if moved:
            mv = np.array([own.units[picked[k][0]] for k in moved], dtype=np.float64)
            base = np.array([picked[k][1] for k in moved], dtype=np.float64)
            for k, p in zip(moved, served(base, own.spread**2, mv[:, 0], mv[:, 1]), strict=True):
                m5o[k] = float(p)
        m5y: list[float | None] = [None] * len(picked)
        ky = self.ky
        if ky is not None and ky.why is None:
            read = [k for k, (unit, _) in enumerate(picked) if unit in ky.units]
            if read:
                kv = np.array([ky.units[picked[k][0]] for k in read], dtype=np.float64)
                base = np.array([picked[k][1] for k in read], dtype=np.float64)
                for k, p in zip(read, served(base, ky.v0, kv[:, 0], kv[:, 1]), strict=True):
                    m5y[k] = float(p)
        return list(zip(m5o, m5y, strict=True))


def _rows_k() -> Callable[[KyInputs], Sequence[OwnRow]] | None:
    """R-KYY's rows K maker (dated W days against each district's class days): ``None`` while
    the class days are not built (LR14 and LR21), so R-KYY pulls nothing. Private to this
    module (lead ruling LR-P6A-6): no caller hands :meth:`Shadow._fit` a consumer of R-KYY's
    rows, and the fit refuses a maker that is not this module's own (:func:`_own`)."""
    return None


def _own(fn: object) -> bool:
    """Whether a callable was made in this module (a rows K maker from anywhere else is
    refused)."""
    return getattr(fn, "__module__", None) == __name__


def store_past(store: Any, capability: object) -> dict[str, bytes]:
    """R-KYY's pull: the record kind's past keys from the evidence store (``past/...`` sorts
    after every day key, so asking from the last date reads them alone), newest version each.
    Bound to the record's capability (lead ruling LR-P6A-1): the store reads the record only
    with :data:`_READ`, which :meth:`Shadow._fit` alone passes.

    Called from outside this module it reads nothing, with the capability or without: the
    store admits the capability only from a call made here, and this read only from a caller
    here (:meth:`Shadow._fit`).

    Raises:
        snowlight.live.evidence.RecordRefusedError: ``capability`` is not this module's, or the
            caller is not in this module.
    """
    from snowlight.live.evidence import RECORD, RecordRefusedError  # noqa: PLC0415

    if sys._getframe(1).f_globals.get("__name__") != __name__:
        raise RecordRefusedError(f"{RECORD}: refused, R-KYY's pull is read only by {__name__}")
    found: dict[str, bytes] = store.pull(RECORD, date.max, capability=capability)
    return {key: data for key, data in found.items() if key.startswith(record_kind.PAST_PREFIX)}


def exposure_of(days: Mapping[str, Sequence[float]], classes: Sequence[str]) -> dict[str, float]:
    """M5y's ``E``: each district's advisory and warning days a winter weighed by the classes'
    registered levels (10% and 45%; only the ratio between districts counts)."""
    levels = {"advisory": 0.10, "warning": 0.45}
    return {
        leaid: sum(levels.get(k, 0.0) * d for k, d in zip(classes, found, strict=True))
        for leaid, found in days.items()
    }


def summed_lists(
    day_lists: Mapping[str, Mapping[str, Sequence[object]]],
) -> dict[str, list[object]]:
    """Each list's ``[tier, hits, trials]`` summed over the days given (its tier the last
    day's)."""
    found: dict[str, list[object]] = {}
    for _day, lists in sorted(day_lists.items()):
        for name, (tier, hits, count) in lists.items():
            had = found.setdefault(name, [tier, 0, 0])
            had[0] = tier
            had[1] = int(str(had[1])) + int(str(hits))
            had[2] = int(str(had[2])) + int(str(count))
    return dict(sorted(found.items()))


def with_fit(shadow: Shadow, own: OwnFit, ky: KyFit | None = None, *, at: datetime) -> Shadow:
    """``shadow`` with a fit given (tests and the drill), made at ``at``: the world's clock, so
    whether the fit is due never hangs on the real date."""
    return replace(shadow, own=own, ky=ky, computed=at, loaded=True)
