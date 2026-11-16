"""The gates of each district's own part that need no traits (each-school P6a, P6's gate items):
the unit-by-unit G1 arithmetic, within-morning discrimination, the archive's walk-forward
scores, the shuffle null and the misattribution report (r4 11(a), 11(g)), the record-length and
locale groups, the shift sum, and the scoring reader of the shadow arms' kind (``es``).

Nothing here serves or writes anything a pass reads. The archive runs read the internal labels
table off the pass (the builder's dry run calls these functions; no command is registered for it,
and the labels read are the final ones: per-fold labels, r4 10.2 and rule 12.3, are not kept).
Record counts a gate uses are by storm (honesty rule 11: dates under 5 days apart are one
storm), with the mornings reported beside. Scores are level-free on the archive
(r4 10.4: each arm's own best single shift per class and fold, fit on the held-out rows; the one
named exemption), absolute beside; G3 is within a market-morning and class, where the level
drops out. Codes, ids and numbers only.
"""

import math
import random
import time
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Final

import numpy as np

from snowlight.predict import frozen
from snowlight.predict.anchor import LiveLabels, storms_of
from snowlight.predict.forecast_adjust import AdjustSettings
from snowlight.predict.lines import (
    CLASSES,
    KY_FIRST,
    MAX_AGE,
    OwnFit,
    OwnRow,
    Tempering,
    drop_served,
    fit_own,
    served,
)

LIMITS: Final = (0.005, 0.002)
"""G1's per-unit no-harm limits: log loss and Brier, a row (b')."""
NAMED: Final = 0.05
"""G1(c): units worse (or better) by more than this, nats a row."""
GROUP_MIN: Final = 30
SIGN_UNITS: Final = 100
SIGN_P: Final = 0.05
BOOT: Final = 2000
BOOT_CHUNK: Final = 100
"""The bootstrap's resamples worked out together (memory: this many rows of the units)."""
SAME: Final = 1e-12
"""A resample whose spread is under this share of its sum of squares holds one value."""
LENGTHS: Final = ((0, 0, "0"), (1, 3, "1-3"), (4, 10**9, "4+"))
"""Record-length groups: recorded storms of the unit before the row (rule 11)."""
STORM_DAYS: Final = 5
"""Honesty rule 11: dates less than this many days apart are one storm."""
STORM_GAP: Final = 1
"""The live walk-forward's storms (r4 10.2): the anchor's rule, mornings at most this many
weekdays apart one storm (``live_update.ramp_storm_gap``, registered 1)."""
STATE_MIN: Final = 10
"""G1(e): each state with this many units or more is judged..."""
STATE_LIMIT: Final = 0.01
"""...its mean ``Delta_u`` at least minus this, nats a row."""
SHUFFLE_POINTS: Final = (1.0, 3.0)
"""r4 11(a): a shuffle's served chances differ from S by under 1 point for the median unit and
under 3 points at the 99th percentile."""
LOCALES: Final = {"1": "city", "2": "suburb", "3": "town", "4": "rural"}
EPS: Final = 1e-12


def log_loss(p: float, y: bool) -> float:
    q = min(max(p, EPS), 1 - EPS)
    return -math.log(q if y else 1 - q)


def brier(p: float, y: bool) -> float:
    return (p - float(y)) ** 2


@dataclass(frozen=True, slots=True)
class Scored:
    """One held-out row scored by the reference (S) and the arm: its unit, group, outcome,
    both chances, the unit's record length before it and its locale group."""

    unit: str
    group: str
    closed: bool
    ref: float
    arm: float
    length: str = "0"
    locale: str = "unknown"
    mornings: int = 0
    """The unit's recorded mornings before the row (reported beside its storms)."""
    storm: str = ""
    """The row's storm (its first date), for a walk-forward by storm."""


@dataclass(frozen=True, slots=True)
class G1:
    """G1's arithmetic (r4 10.5): per unit ``Delta_u`` (reference less arm, positive better)."""

    units: int
    median_ll: float
    median_brier: float
    sign_p: float | None
    """The one-sided sign test's p of worse against better (``None``: fewer than 100 units
    whose ``Delta_u`` is not 0, so (b') judges)."""
    lower_ll: float
    lower_brier: float
    """(b'): the lower 90% unit-bootstrap bounds of the mean ``Delta_u``."""
    worse: int
    better: int
    named: tuple[tuple[str, int, float], ...]
    """(c): each unit worse by more than :data:`NAMED`, with its rows and ``Delta_u``."""
    groups: Mapping[str, tuple[int, float, bool | None]]
    """(d) and (e): each record-length (by storms), locale and state group: units, mean
    ``Delta_u`` and whether it passes (``None``: too few units, reported only). A judged (d)
    group passes on its mean and on (b) or (b') within it; a judged state on its mean."""
    mornings: Mapping[str, tuple[int, float]] = field(default_factory=dict)
    """The record-length groups by mornings instead of storms, reported only (rule 11)."""

    @property
    def passed(self) -> bool:
        b = _b_holds(self.sign_p, self.lower_ll, self.lower_brier)
        d = all(ok is not False for _, _, ok in self.groups.values())
        return (
            self.median_ll >= 0 and self.median_brier >= 0 and b and self.worse <= self.better and d
        )


def _b_holds(sign_p: float | None, lower_ll: float, lower_brier: float) -> bool:
    """(b) with its sign test where it ran, else (b')."""
    if sign_p is not None:
        return sign_p >= SIGN_P
    return lower_ll >= -LIMITS[0] and lower_brier >= -LIMITS[1]


def _b_of(d_ll: Mapping[str, float], d_b: Mapping[str, float], units: Sequence[str]) -> bool:
    """(b) or (b') over ``units`` alone."""
    worse = sum(1 for u in units if d_ll[u] < 0)
    better = sum(1 for u in units if d_ll[u] > 0)
    return _b_holds(
        _sign_p(worse, better) if worse + better >= SIGN_UNITS else None,
        _boot_lower([d_ll[u] for u in units]),
        _boot_lower([d_b[u] for u in units]),
    )


def storm_count(days: Iterable[date]) -> int:
    """The storms of a record (honesty rule 11): its dates, those under :data:`STORM_DAYS`
    days apart one storm."""
    found, last = 0, None
    for day in sorted(set(days)):
        if last is None or (day - last).days >= STORM_DAYS:
            found += 1
        last = day
    return found


def storms_by_date(days: Iterable[date]) -> dict[date, date]:
    """Each date's storm by rule 11, named by its first date."""
    found: dict[date, date] = {}
    first: date | None = None
    last: date | None = None
    for day in sorted(set(days)):
        if first is None or last is None or (day - last).days >= STORM_DAYS:
            first = day
        found[day] = first
        last = day
    return found


def length_of(n: int) -> str:
    return next(label for lo, hi, label in LENGTHS if lo <= n <= hi)


def _sign_p(worse: int, better: int) -> float:
    """One-sided binomial p of at least ``worse`` worse among ``worse + better`` at 1/2."""
    n = worse + better
    return float(sum(math.comb(n, k) for k in range(worse, n + 1)) / 2**n)


def _boot_lower(values: Sequence[float], seed: int = 3) -> float:
    if not values:
        return 0.0
    rng = np.random.default_rng(seed)
    arr = np.asarray(values)
    means = arr[rng.integers(0, len(arr), (BOOT, len(arr)))].mean(axis=1)
    return float(np.quantile(means, 0.05))


def _deltas(rows: Iterable[Scored]) -> tuple[dict[str, float], dict[str, float]]:
    """Each unit's ``Delta_u`` (log loss, Brier) over ``rows`` alone, the mean over its rows."""
    by: dict[str, list[Scored]] = {}
    for row in rows:
        by.setdefault(row.unit, []).append(row)
    d_ll: dict[str, float] = {}
    d_b: dict[str, float] = {}
    for unit, found in by.items():
        d_ll[unit] = sum(
            log_loss(r.ref, r.closed) - log_loss(r.arm, r.closed) for r in found
        ) / len(found)
        d_b[unit] = sum(brier(r.ref, r.closed) - brier(r.arm, r.closed) for r in found) / len(found)
    return d_ll, d_b


def g1(rows: Sequence[Scored]) -> G1:
    """G1 (a) to (d) on scored rows (see :class:`G1`). A record-length group (by storms or
    by mornings, taken before each row) judges each unit on its ``Delta_u`` over that unit's
    rows in the group alone, so a unit whose record-less rows are harmed cannot pass the
    record-less group on its later rows; locale and state are per unit and use the unit's
    ``Delta_u`` over all its rows (the same thing, since a unit's rows share them)."""
    by: dict[str, list[Scored]] = {}
    for row in rows:
        by.setdefault(row.unit, []).append(row)
    d_ll, d_b = _deltas(rows)
    worse = sum(1 for v in d_ll.values() if v < 0)
    better = sum(1 for v in d_ll.values() if v > 0)
    groups: dict[str, tuple[int, float, bool | None]] = {}
    picks: list[tuple[str, Callable[[Scored], str], str]] = [
        *((f"length {label}", lambda r: r.length, label) for *_, label in LENGTHS),
        *((f"locale {loc}", lambda r: r.locale, loc) for loc in LOCALES.values()),
    ]
    for name, key, value in picks:
        g_ll, g_b = _deltas(r for r in rows if key(r) == value)
        units = sorted(g_ll)
        if not units:
            continue
        mean = sum(g_ll[u] for u in units) / len(units)
        ok = None if len(units) < GROUP_MIN else mean >= -LIMITS[0] and _b_of(g_ll, g_b, units)
        groups[name] = (len(units), mean, ok)
    states = {u: u[:2] for u in by if len(u) == 7 and u.isdigit()}  # noqa: PLR2004 - an LEA id
    for state in sorted(set(states.values())):
        units = sorted(u for u, at in states.items() if at == state)
        mean = sum(d_ll[u] for u in units) / len(units)
        groups[f"state {state}"] = (
            len(units), mean, None if len(units) < STATE_MIN else mean >= -STATE_LIMIT,
        )  # fmt: skip
    mornings: dict[str, tuple[int, float]] = {}
    for *_, label in LENGTHS:
        m_ll, _ = _deltas(r for r in rows if length_of(r.mornings) == label)
        if m_ll:
            mornings[f"mornings {label}"] = (len(m_ll), sum(m_ll.values()) / len(m_ll))
    return G1(
        units=len(by),
        median_ll=float(np.median(list(d_ll.values()))) if d_ll else 0.0,
        median_brier=float(np.median(list(d_b.values()))) if d_b else 0.0,
        sign_p=_sign_p(worse, better) if worse + better >= SIGN_UNITS else None,
        lower_ll=_boot_lower(list(d_ll.values())),
        lower_brier=_boot_lower(list(d_b.values())),
        worse=sum(1 for v in d_ll.values() if v < -NAMED),
        better=sum(1 for v in d_ll.values() if v > NAMED),
        named=tuple(sorted((u, len(by[u]), round(v, 4)) for u, v in d_ll.items() if v < -NAMED)),
        groups=groups,
        mornings=mornings,
    )


def cll(group: Sequence[tuple[float, bool]]) -> float:
    """The exact conditional log likelihood of a group's closings given how many closed
    (``live_switch.cll``'s rule): the closed set's odds over every set of that size's, in log
    space (a morning of hundreds of rows neither overflows nor underflows)."""
    k = sum(1 for _, y in group if y)
    if k in {0, len(group)}:
        return 0.0
    logs = [
        math.log(min(max(p, EPS), 1 - EPS)) - math.log1p(-min(max(p, EPS), 1 - EPS))
        for p, _ in group
    ]
    le = [0.0] + [-math.inf] * k
    for lo in logs:
        for j in range(k, 0, -1):
            le[j] = float(np.logaddexp(le[j], le[j - 1] + lo))
    return sum(lo for lo, (_, y) in zip(logs, group, strict=True) if y) - le[k]


def g3(rows: Sequence[Scored]) -> tuple[float, int]:
    """G3's held-out difference (arm less reference) of the within-group conditional log
    likelihood, summed, and the groups with both outcomes."""
    by: dict[str, list[Scored]] = {}
    for row in rows:
        by.setdefault(row.group, []).append(row)
    diff, mixed = 0.0, 0
    for found in by.values():
        if 0 < sum(r.closed for r in found) < len(found):
            mixed += 1
            diff += cll([(r.arm, r.closed) for r in found]) - cll(
                [(r.ref, r.closed) for r in found]
            )
    return diff, mixed


# --- the level-free shift (r4 10.4) -----------------------------------------------------------


def best_shift(rows: Sequence[tuple[float, bool]], chance: Callable[[float], list[float]]) -> float:
    """The single shift ``c`` (log odds) of highest likelihood for ``chance(c)`` on ``rows``
    (golden section on -6..6)."""
    ys = [y for _, y in rows]

    def ll(c: float) -> float:
        return -sum(log_loss(p, y) for p, y in zip(chance(c), ys, strict=True))

    lo, hi = -6.0, 6.0
    ratio = (math.sqrt(5) - 1) / 2
    a, b = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
    fa, fb = ll(a), ll(b)
    for _ in range(60):
        if fa < fb:
            lo, a, fa = a, b, fb
            b = lo + ratio * (hi - lo)
            fb = ll(b)
        else:
            hi, b, fb = b, a, fa
            a = hi - ratio * (hi - lo)
            fa = ll(a)
    return (lo + hi) / 2


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _plain(rows: Sequence[OwnRow]) -> Callable[[float], list[float]]:
    def chance(c: float) -> list[float]:
        return [_sig(r.offset + c) for r in rows]

    return chance


def score_fold(  # noqa: PLR0913 - the fold, its groups and the fit's keywords
    train: Sequence[OwnRow],
    test: Sequence[OwnRow],
    *,
    locale: Mapping[str, str] | None = None,
    fit: OwnFit | None = None,
    excluded: Collection[str] = (),
    tempering: Tempering | None = None,
) -> tuple[list[Scored], OwnFit]:
    """One walk-forward fold: the own part fit on ``train`` only, ``test`` scored level-free by
    S (the row's offset, its own best shift per class) and M5o (the prior-neutral base over S's
    chance, its own best shift per class). A unit rule 4 names is scored by S alone. Each row's
    record length is its unit's recorded storms before its date (rule 11; ``train`` and the
    held-out winter's earlier rows), its mornings beside."""
    own = fit_own(train, excluded=excluded, tempering=tempering) if fit is None else fit
    v0 = own.spread**2
    record: dict[str, list[date]] = {}
    for row in [*train, *test]:
        record.setdefault(row.unit, []).append(row.day)
    storm_of = storms_by_date(r.day for r in test)
    found: list[Scored] = []
    for klass in CLASSES:
        rows = [r for r in test if r.klass == klass]
        if not rows:
            continue
        pairs = [(r.offset, r.closed) for r in rows]
        c_s = best_shift(pairs, _plain(rows))

        def arm(c: float, rows: Sequence[OwnRow] = rows) -> list[float]:
            return [
                float(served(_sig(r.offset + c), v0, *own.posterior(r.unit)))
                if r.unit in own.units
                else _sig(r.offset + c)
                for r in rows
            ]

        c_m = best_shift(pairs, arm)
        for r, p_arm in zip(rows, arm(c_m), strict=True):
            before = [day for day in record.get(r.unit, ()) if day < r.day]
            found.append(
                Scored(
                    unit=r.unit,
                    group=r.group,
                    closed=r.closed,
                    ref=_sig(r.offset + c_s),
                    arm=p_arm,
                    length=length_of(storm_count(before)),
                    locale=(locale or {}).get(r.unit, "unknown"),
                    mornings=len(set(before)),
                    storm=storm_of[r.day].isoformat(),
                )
            )
    return found, own


def season_of(day: date) -> int:
    """The winter a day is in (from July 1), by its first year."""
    return day.year if day.month >= 7 else day.year - 1  # noqa: PLR2004 - July


def walk_forward(
    rows: Sequence[OwnRow],
    first: int,
    *,
    locale: Mapping[str, str] | None = None,
    excluded: Collection[str] = (),
    tempering: Tempering | None = None,
) -> dict[int, tuple[list[Scored], OwnFit]]:
    """Each winter from ``first`` held out in turn, the fit on the winters before it only
    (r4 12 rule 3: a held-out winter's rows reach no fit of its fold); rule 4's units in no
    fit."""
    winters = sorted({season_of(r.day) for r in rows if season_of(r.day) >= first})
    found: dict[int, tuple[list[Scored], OwnFit]] = {}
    for winter in winters:
        train = [r for r in rows if season_of(r.day) < winter]
        test = [r for r in rows if season_of(r.day) == winter]
        found[winter] = score_fold(
            train, test, locale=locale, excluded=excluded, tempering=tempering
        )
    return found


# --- 11(a), 11(g) and the shift sum -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Null:
    """The shuffle null (r4 11(a)): each shuffle's fitted spread, the real one, how many
    shuffles came under the floor, and the seconds it took (off the pass)."""

    real: float
    spreads: tuple[float, ...]
    floor: float
    seconds: float
    gaps: tuple[tuple[float, float], ...] = ()
    """Each shuffle's served chances against S, in points: the median unit's mean gap and the
    99th percentile's."""

    @property
    def under(self) -> int:
        return sum(1 for s in self.spreads if s < self.floor)

    @property
    def close(self) -> int:
        """The shuffles whose chances stay within :data:`SHUFFLE_POINTS` of S."""
        median, p99 = SHUFFLE_POINTS
        return sum(1 for m, top in self.gaps if m < median and top < p99)

    @property
    def passed(self) -> bool:
        """r4 11(a) as registered: under the floor, and the served chances within 1 point of
        S for the median unit and 3 points at the 99th percentile, each in at least 95% of
        shuffles."""
        need = math.ceil(0.95 * len(self.spreads))
        return self.under >= need and self.close >= need

    @property
    def above(self) -> bool:
        """The permutation rule (r4 11(a) for P7y): the real spread above the shuffles' 95th
        percentile. A spread fit by its likelihood is above 0 in about a third to a half of
        the shuffles of a world with none (a variance at its boundary), so the registered rule
        fails such a world too; both are reported."""
        return bool(self.real > float(np.quantile(self.spreads, 0.95))) if self.spreads else False


def chance_gaps(rows: Sequence[OwnRow], own: OwnFit) -> tuple[float, float]:
    """A fit's served chances against S on ``rows`` (the prior-neutral base over each row's
    chance), in points: the median unit's mean absolute gap and the 99th percentile unit's."""
    by: dict[str, list[float]] = {}
    v0 = own.spread**2
    for r in rows:
        base = _sig(r.offset)
        p = float(served(base, v0, *own.posterior(r.unit))) if r.unit in own.units else base
        by.setdefault(r.unit, []).append(abs(p - base) * 100)
    if not by:
        return 0.0, 0.0
    means = np.array([sum(v) / len(v) for v in by.values()])
    return float(np.median(means)), float(np.quantile(means, 0.99))


def shuffle_null(  # noqa: PLR0913 - the rows, the shuffles and the fit's keywords
    rows: Sequence[OwnRow],
    times: int,
    *,
    seed: int = 17,
    floor: float = 0.05,
    excluded: Collection[str] = (),
    tempering: Tempering | None = None,
) -> Null:
    """The calls shuffled ``times`` times within each market-morning and class, refit each time;
    a part with no spread must fit under ``floor`` in at least 95% of shuffles. Each call moves
    with its own offset (the districts of the morning are shuffled over its rows): a call moved
    away from its offset would read the offset's own signal as a spread."""
    started = time.monotonic()
    rows = [row for row in rows if row.unit not in excluded]  # rule 4's units in no fit
    rng = random.Random(seed)  # noqa: S311 - a seeded shuffle, not a secret
    by: dict[str, list[int]] = {}
    for k, row in enumerate(rows):
        by.setdefault(row.group, []).append(k)
    spreads: list[float] = []
    gaps: list[tuple[float, float]] = []
    for _ in range(times):
        units = [r.unit for r in rows]
        for found in by.values():
            moved = [units[k] for k in found]
            rng.shuffle(moved)
            for k, unit in zip(found, moved, strict=True):
                units[k] = unit
        shuffled = [replace(r, unit=u) for r, u in zip(rows, units, strict=True)]
        fit = fit_own(shuffled, tempering=tempering)
        spreads.append(fit.spread)
        gaps.append(chance_gaps(shuffled, fit))
    real = fit_own(rows, tempering=tempering).spread
    return Null(real, tuple(spreads), floor, time.monotonic() - started, tuple(gaps))


def correlation(
    xs: Sequence[float], ys: Sequence[float], *, seed: int = 5
) -> tuple[float, float, float]:
    """Pearson's r with its 90% bootstrap interval (r4 11(g))."""
    return correlations(xs, [ys], seed=seed)[0]


def correlations(
    xs: Sequence[float], yss: Sequence[Sequence[float]], *, seed: int = 5
) -> list[tuple[float, float, float]]:
    """:func:`correlation` of ``xs`` with each of ``yss`` on the same resamples (each the
    same as alone: the draws depend only on ``seed`` and the length)."""
    x = np.asarray(xs, dtype=np.float64)
    ys = [np.asarray(v, dtype=np.float64) for v in yss]
    n = len(x)
    out: list[tuple[float, float, float] | None] = [
        (0.0, 0.0, 0.0) if n < 3 or float(np.std(x)) == 0 or float(np.std(y)) == 0 else None  # noqa: PLR2004
        for y in ys
    ]
    live = [k for k, v in enumerate(out) if v is None]
    if not live:
        return [v or (0.0, 0.0, 0.0) for v in out]
    rng = np.random.default_rng(seed)
    xc = x - x.mean()  # r is the same; the sums below lose less
    ycs = [ys[k] - ys[k].mean() for k in live]
    sums = np.stack([xc, xc * xc, *ycs, *(y * y for y in ycs), *(xc * y for y in ycs)], axis=1)
    draws = [rng.integers(0, n, n) for _ in range(BOOT)]
    m = len(live)
    found: list[list[float]] = [[] for _ in live]
    for start in range(0, BOOT, BOOT_CHUNK):  # each resample's sums from its counts
        counts = np.stack([np.bincount(k, minlength=n) for k in draws[start : start + BOOT_CHUNK]])
        got = counts.astype(np.float64) @ sums
        sx, sxx = got[:, 0], got[:, 1]
        vx = sxx - sx * sx / n
        for k in range(m):
            sy, syy, sxy = got[:, 2 + k], got[:, 2 + m + k], got[:, 2 + 2 * m + k]
            vy = syy - sy * sy / n
            keep = (vx > SAME * sxx) & (vy > SAME * syy)  # a resample of one value has no r
            found[k].extend(((sxy - sx * sy / n)[keep] / np.sqrt(vx[keep] * vy[keep])).tolist())
    for k, at in enumerate(live):
        r = float(np.corrcoef(x, ys[at])[0, 1])
        lo, hi = np.quantile(found[k], [0.05, 0.95]) if found[k] else (0.0, 0.0)
        out[at] = (r, float(lo), float(hi))
    return [v or (0.0, 0.0, 0.0) for v in out]


def misattribution(
    own: OwnFit, traits: Mapping[str, Mapping[str, float]]
) -> dict[str, tuple[int, float, float, float]]:
    """Own's posterior mean against each unit trait it must not stand in for (11(g): list
    coverage, missing outcomes, forecast misses where known): units, r and its 90% interval.
    An ``|r|`` over 0.2 with an interval that excludes 0 keeps the part off until explained."""
    found: dict[str, tuple[int, float, float, float]] = {}
    by_units: dict[tuple[str, ...], list[str]] = {}  # traits on the same units share resamples
    for name, values in traits.items():
        by_units.setdefault(tuple(sorted(u for u in own.units if u in values)), []).append(name)
    for units, names in by_units.items():
        xs = [own.units[u][0] for u in units]
        each = correlations(xs, [[traits[name][u] for u in units] for name in names])
        for name, (r, lo, hi) in zip(names, each, strict=True):
            found[name] = (len(units), r, lo, hi)
    return {name: found[name] for name in traits}


def flagged(found: Mapping[str, tuple[int, float, float, float]]) -> list[str]:
    """The traits 11(g) flags: ``|r|`` over 0.2 with an interval excluding 0."""
    return [
        name
        for name, (_, r, lo, hi) in found.items()
        if abs(r) > 0.2 and (lo > 0 or hi < 0)  # noqa: PLR2004
    ]


def _level(rows: Sequence[OwnRow], own: OwnFit) -> float:
    pairs = [(r.offset, r.closed) for r in rows]
    return best_shift(
        pairs, lambda c: [_sig(r.offset + c + own.posterior(r.unit)[0]) for r in rows]
    )


def shift_sum(
    before: Sequence[OwnRow],
    storm: Sequence[OwnRow],
    *,
    excluded: Collection[str] = (),
    tempering: Tempering | None = None,
) -> tuple[float, float, float]:
    """r4 9 step 4: one storm's rows added to the joint fit of the class level and own. On the
    storm's units, in log odds: the level's separate shift (refit with own held at its fit
    before), own's separate shifts (refit with the level held: own's fit is within a
    market-morning, so the level never enters it), and how far the joint shift (both refit) is
    off their sum, at most (0.01 passes). Returns the level's shift, own's largest shift and
    the largest miss. Both fits are the registered one (:func:`walk_forward`'s): rule 4's
    units in neither, the storms tempered."""
    own0 = fit_own(before, excluded=excluded, tempering=tempering)
    own1 = fit_own([*before, *storm], excluded=excluded, tempering=tempering)
    after = [*before, *storm]
    level_before = _level(before, own0) if before else 0.0
    level_held = _level(after, own0)
    level_joint = _level(after, own1)
    most_own = 0.0
    off = 0.0
    for unit in sorted({r.unit for r in storm}):
        own_shift = own1.posterior(unit)[0] - own0.posterior(unit)[0]
        joint = (level_joint + own1.posterior(unit)[0]) - (level_before + own0.posterior(unit)[0])
        most_own = max(most_own, abs(own_shift))
        off = max(off, abs(joint - ((level_held - level_before) + own_shift)))
    return level_held - level_before, most_own, off


# --- the scoring reader of the shadow arms' kind ----------------------------------------------


@dataclass
class EsScore:
    """The shadow arms scored on live labeled rows (each row once, at each scoring freeze, on
    its frozen chances: never a recomputation): per arm and freeze, the scored rows, and the
    lines left out because their fit was older than :data:`snowlight.predict.lines.MAX_AGE`
    at the freeze (lines written after failed nights are not scored as current)."""

    rows: dict[tuple[str, str], list[Scored]] = field(default_factory=dict)
    stale: int = 0
    capped: dict[str, int] = field(default_factory=dict)
    """Per freeze, the scored district rows whose base was held at the class order's cap (r5
    3.2 puts the base before the cap and the cap after the own part; the frozen record keeps
    only the chance after it, so these rows' base is after the cap and no cap acts on the arm:
    a known deviation, counted so a gate reads how many rows it touches)."""


CAP_EPS: Final = 1e-4
"""The frozen terms' rounding (4 decimals): a bound under the class's own by more is a cap."""


def uncapped_highs(settings: AdjustSettings) -> dict[str, float]:
    """Each class's upper bound on the day's total before the class order's cap: the class's
    ``high``, or with ``snow_amount`` on the asymptote ``snow_amount_high``
    (:func:`snowlight.predict.forecast_adjust.term_parts`)."""
    return {
        k: settings.snow_amount_high if settings.snow_amount else high
        for k, (_, high) in settings.bounds.items()
    }


def at_order_cap(terms: Mapping[str, object] | None, high: float | None) -> bool:
    """Whether a frozen row's terms were held at the class order's cap: the bound used
    (``hi``, already the cap where one applied) under the class's own ``high`` and the held
    total at it, over the raw total's reach."""
    if terms is None or high is None:
        return False
    hi = terms.get("hi")
    raw, held = terms.get("raw"), terms.get("b")
    if not isinstance(hi, (int, float)) or not isinstance(raw, list) or not isinstance(held, list):
        return False
    total = sum(float(v) for v in held)
    return hi < high - CAP_EPS and total >= hi - CAP_EPS and sum(float(v) for v in raw) > hi


SCORING: Final = ("d1_2007", "d0_0507")


def _fresh(es: frozen.EsFreeze) -> bool:
    if es.fit is None or es.at is None:
        return False
    try:
        return es.at - datetime.fromisoformat(es.fit) <= MAX_AGE
    except (TypeError, ValueError):
        return False


def _scored_days(
    labels: LiveLabels,
    served_day: date,
    class_of: Callable[[str], str | None],
    tier_b: Collection[str],
) -> dict[date, list[tuple[str, str | None, bool, str | None]]]:
    """Each labeled day before ``served_day`` that :func:`score_es` scores, with each row's
    unit, market, call and class: tier A, tier B where its class's rule lets it in, no day
    after."""
    by_day: dict[date, list[tuple[str, str | None, bool, str | None]]] = {}
    for row in labels.rows:
        if row.day >= served_day or row.weather.endswith("_after"):
            continue
        if row.tier != "A" and class_of(row.weather) not in tier_b:
            continue
        by_day.setdefault(row.day, []).append(
            (row.district, row.market, row.label == "no_school", class_of(row.weather))
        )
    return by_day


def score_es(  # noqa: PLR0913 - the days, the labels and the label rules
    days: Mapping[date, Sequence[frozen.EsFreeze]],
    district: Mapping[date, frozen.FrozenDay],
    labels: LiveLabels,
    served_day: date,
    *,
    class_of: Callable[[str], str | None],
    tier_b: Collection[str] = frozenset(),
    storm_gap: int = STORM_GAP,
    highs: Mapping[str, float] | None = None,
    locale: Mapping[str, str] | None = None,
    earlier: Mapping[str, Collection[date]] | None = None,
) -> EsScore:
    """The scoring reader of ``es`` (kind ``frozen_es``): each labeled live row of an
    advisory or warning day before ``served_day`` with a shadow line at a scoring freeze from a
    fit no older than ``MAX_AGE``, scored against S (the frozen published chance before
    rounding of the same freeze), under the bus switch's label rules
    (:func:`snowlight.predict.live_switch.bus_groups`): L1's class of the day is the row's
    served class, ``no_school`` closed; tier A, and tier B only when the anchor's tier B rule
    let it in for the row's class (``tier_b``, the classes whose fit admits it); a day-after
    row waits (rule 10). Each row carries its storm, by the anchor's storm rule (r4 10.2: the
    live walk-forward is by storm, mornings at most ``storm_gap`` weekdays apart one storm,
    ``live_update.ramp_storm_gap``); rule 11's storms stay the record counts'. With ``highs``
    (:func:`uncapped_highs`), each freeze counts its scored rows held at the class order's cap
    (:attr:`EsScore.capped`). Each row carries, as :func:`score_fold`'s do, its unit's record
    length (rule 11: its recorded storms before the row's day, from its labeled days here and
    any ``earlier`` days of its record, such as the archive's), its mornings and its
    ``locale``, so the record-length and locale groups of :func:`g1` read live rows right."""
    found = EsScore()
    by_day = _scored_days(labels, served_day, class_of, tier_b)
    storm_of = storms_of(by_day, storm_gap)
    record: dict[str, set[date]] = {u: set(days) for u, days in (earlier or {}).items()}
    for day, labeled in by_day.items():
        for unit, *_ in labeled:
            record.setdefault(unit, set()).add(day)
    for day, labeled in sorted(by_day.items()):
        ref = {
            (r.freeze, r.leaid): r
            for r in (district[day].rows if day in district else ())
            if r.p_raw is not None and r.klass in CLASSES and r.served and not r.said_open
        }
        for es in days.get(day, ()):
            if es.freeze not in SCORING:
                continue
            if not _fresh(es):
                found.stale += len(es.chances)
                continue
            for unit, market, closed, klass in labeled:
                base = ref.get((es.freeze, unit))
                values = es.chances.get(unit)
                if base is None or values is None or base.p_raw is None or base.klass != klass:
                    continue
                if highs is not None and at_order_cap(base.terms, highs.get(klass or "")):
                    found.capped[es.freeze] = found.capped.get(es.freeze, 0) + 1
                before = [d for d in record.get(unit, ()) if d < day]
                for arm, p in zip(es.arms, values, strict=True):
                    if p is None:
                        continue
                    found.rows.setdefault((arm, es.freeze), []).append(
                        Scored(
                            unit=unit,
                            group=f"{day}|{market or '~' + unit}|{base.klass}",
                            closed=closed,
                            ref=base.p_raw,
                            arm=p,
                            length=length_of(storm_count(before)),
                            locale=(locale or {}).get(unit, "unknown"),
                            mornings=len(before),
                            storm=storm_of[day].isoformat(),
                        )
                    )
    return found


# --- Kentucky's folds (G-OWN-YEAR's arithmetic; M5y in shadow) -------------------------------


@dataclass(frozen=True, slots=True)
class KyFold:
    """One Kentucky fold: the slope it fit, on how many rows K, its scored rows, G1(a)'s set
    (the districts with a count and 2 or more rows K in the test year) and the mean-chance gap
    (arm less S, points) against ``each_school.ky_gap_points``."""

    beta: float | None
    rows: int
    scored: tuple[Scored, ...]
    g1_units: frozenset[str] = frozenset()
    gap_points: float = 0.0


def _ky_window(counts: Mapping[tuple[str, str], int], before: str) -> dict[tuple[str, str], int]:
    return {k: v for k, v in counts.items() if KY_FIRST <= k[1] < before}


def ky_fold(
    counts: Mapping[tuple[str, str], int],
    rows_k: Sequence[OwnRow],
    exposure: Mapping[str, float],
    *,
    fit_year: str,
    test_year: str,
) -> KyFold:
    """A Kentucky fold (7.1): ``beta`` on ``fit_year``'s rows K with ``t`` from the counts of
    the years before it, scored on ``test_year``'s rows K with ``t`` from the years before
    that; nothing of ``test_year`` or later reaches the fit."""
    from snowlight.predict.lines import (  # noqa: PLC0415
        fit_slope,
        fit_tendency,
        ky_fit,
        school_year,
    )

    t_fit = fit_tendency(_ky_window(counts, fit_year), exposure)
    train = [r for r in rows_k if school_year(r.day) == fit_year]
    slope = fit_slope(train, t_fit.units)
    t_test = fit_tendency(_ky_window(counts, test_year), exposure)
    parts = ky_fit(t_test, slope)
    test = [r for r in rows_k if school_year(r.day) == test_year]
    counted = {unit for unit, year in counts if KY_FIRST <= year < test_year}
    per_unit = Counter(r.unit for r in test)
    g1_units = frozenset(u for u, n in per_unit.items() if n >= 2 and u in counted)  # noqa: PLR2004
    scored: list[Scored] = []
    if parts.why is None:
        for klass in CLASSES:
            rows = [r for r in test if r.klass == klass and r.unit in parts.units]
            if not rows:
                continue
            pairs = [(r.offset, r.closed) for r in rows]
            c_s = best_shift(pairs, _plain(rows))

            def arm(c: float, rows: Sequence[OwnRow] = rows) -> list[float]:
                return [
                    float(served(_sig(r.offset + c), parts.v0, *parts.units[r.unit])) for r in rows
                ]

            c_m = best_shift(pairs, arm)
            scored.extend(
                Scored(r.unit, r.group, r.closed, _sig(r.offset + c_s), p)
                for r, p in zip(rows, arm(c_m), strict=True)
            )
    gap = (
        100 * (sum(r.arm for r in scored) - sum(r.ref for r in scored)) / len(scored)
        if scored
        else 0.0
    )
    return KyFold(slope.beta, slope.rows, tuple(scored), g1_units, gap)


def ky_gate(
    counts: Mapping[tuple[str, str], int],
    rows_k: Sequence[OwnRow],
    exposure: Mapping[str, float],
    gate_fold: str = "2025-26",
) -> KyFold:
    """G-OWN-YEAR's gate fold: ``beta`` from the year before ``gate_fold``, scored on it."""
    start = int(gate_fold[:4])
    return ky_fold(
        counts, rows_k, exposure, fit_year=f"{start - 1}-{start % 100:02d}", test_year=gate_fold
    )


def ky_cross_fit(
    counts: Mapping[tuple[str, str], int],
    rows_k: Sequence[OwnRow],
    exposure: Mapping[str, float],
) -> KyFold:
    """The 2024-25 cross-fit (lead ruling LR24): ``beta`` from 2025-26's rows K scored on
    2024-25; R-KYY's one later-year read, reported only. No gate, switch or served chance takes
    it (:func:`ky_gate` and :class:`snowlight.predict.lines.Shadow` never call it)."""
    from snowlight.predict.lines import fit_slope, fit_tendency, ky_fit  # noqa: PLC0415

    tendency = fit_tendency({k: v for k, v in counts.items() if k[1] < "2024-25"}, exposure)
    slope = fit_slope([r for r in rows_k if season_of(r.day) == 2025], tendency.units)  # noqa: PLR2004
    parts = ky_fit(tendency, slope)
    test = [r for r in rows_k if season_of(r.day) == 2024 and r.unit in parts.units]  # noqa: PLR2004
    scored = (
        []
        if parts.why is not None
        else [
            Scored(
                r.unit,
                r.group,
                r.closed,
                _sig(r.offset),
                float(served(_sig(r.offset), parts.v0, *parts.units[r.unit])),
            )
            for r in test
        ]
    )
    return KyFold(slope.beta, slope.rows, tuple(scored))


def drop_after(rows: Iterable[OwnRow], served_day: date) -> list[OwnRow]:
    """:func:`snowlight.predict.lines.drop_served` (rows of the served day and later never
    reach a fit or a gate)."""
    return drop_served(rows, served_day)
