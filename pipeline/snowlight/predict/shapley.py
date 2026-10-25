"""Whole points for the reasons: exact Shapley values of the terms on the chance (S7 spec c.2).

The chance with the terms is ``p = sigmoid(logit(p_base) + sum_j f_j)``. The value of a set
``S`` of terms is ``100 * sigmoid(logit(p_base) + sum_{j in S} f_j)``; each term's Shapley
value is its average marginal value over every order the terms can come in (exact: at most
2^5 sets). They add up to ``100 * (p - p_base)``.

The base keeps its own whole points (``round(100 * p_base)``, the number its sentence is true
of: never re-rounded), and the terms share what is left, ``round(100 * p_shown) - base``, by
the largest remainder (:func:`whole_points`), so the base and the lines add up to the chance
shown exactly. A term's points never take the other side of its value (an adding term never
takes away), and a term that rounds to 0 is dropped.
"""

import math
from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Final

MAX_TERMS: Final = 5


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def _logit(p: float) -> float:
    q = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(q / (1 - q))


def shapley[K](p_base: float, terms: Mapping[K, float]) -> dict[K, float]:
    """Each term's exact Shapley value on ``100 * p`` (see the module docstring).

    Raises:
        ValueError: more than :data:`MAX_TERMS` terms.
    """
    keys = list(terms)
    if len(keys) > MAX_TERMS:
        raise ValueError(f"at most {MAX_TERMS} terms, not {len(keys)}")
    start = _logit(p_base)
    n = len(keys)

    def value(members: Sequence[K]) -> float:
        return 100.0 * _sigmoid(start + sum(terms[k] for k in members))

    found: dict[K, float] = {}
    for key in keys:
        others = [k for k in keys if k != key]
        total = 0.0
        for size in range(n):
            weight = math.factorial(size) * math.factorial(n - size - 1) / math.factorial(n)
            for members in combinations(others, size):
                total += weight * (value([*members, key]) - value(members))
        found[key] = total
    return found


def whole_points[K](values: Mapping[K, float], total: int) -> dict[K, int]:
    """Whole points for each value adding up to ``total``: each value's floor, then one more
    to the largest remainders (ties to the larger value, then the earlier key). When the floors
    cannot reach ``total`` that way (a clamp at the floor or ceiling moved it), the values are
    first scaled to ``total``. A value's points never take its other side.

    Raises:
        ValueError: ``total`` and the values point opposite ways (no such split exists).
    """
    keys = list(values)
    if not keys:
        if total:
            raise ValueError("points to share but no term")
        return {}
    raw = dict(values)
    for _ in range(2):
        floors = {k: math.floor(raw[k]) for k in keys}
        extra = total - sum(floors.values())
        if 0 <= extra <= len(keys):
            order = sorted(
                range(len(keys)),
                key=lambda i: (-(raw[keys[i]] - floors[keys[i]]), -raw[keys[i]], i),
            )
            found = dict(floors)
            for i in order[:extra]:
                found[keys[i]] += 1
            if all(found[k] * values[k] >= 0 for k in keys):
                return found
        whole = sum(raw.values())
        if whole == 0 or whole * total < 0:
            break
        raw = {k: raw[k] * total / whole for k in keys}
    # Last resort: the whole total on the largest value on the total's side.
    side = [k for k in keys if values[k] * total > 0] if total else []
    if total and not side:
        raise ValueError(f"{total} points to share over values of the other side")
    found = dict.fromkeys(keys, 0)
    if total:
        found[max(side, key=lambda k: abs(values[k]))] = total
    return found
