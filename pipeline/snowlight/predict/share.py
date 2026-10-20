"""The share a base sentence says for a whole percent, and whether it is true of a count.

The website words a base of ``points`` percent (``web/src/copy-chance.ts``, ``shareOf`` and
``baseReason``):

* 1 or less: "almost never"; 99 or more: "almost always";
* an exact share when one rounds to the percent ("3 in 4", "1 in 6");
* else "more than" the largest easy share under it ("more than 3 in 5").

:func:`share_of` is that rule, ported; ``tests/predict/golden/shares.json`` holds its
answer for every percent and the web's unit test checks ``shareOf`` against the same file,
so the two never drift. :func:`says_true` is the test the chain names a level by (the lead's
addendum d, item 4): the sentence for the published points must be true of the level's
recorded days ``y`` of ``n``:

* "almost never": ``y / n`` under ``almost``; "almost always": over ``1 - almost``;
* an exact share: ``y / n`` rounds to the same whole percent (half up);
* "more than s in o": ``y / n`` above ``s / o``.
"""

import math
from dataclasses import dataclass
from functools import cache
from typing import Final

import numpy as np
import numpy.typing as npt

SHARES: Final[tuple[tuple[int, int], ...]] = (
    (1, 2),
    (1, 3),
    (2, 3),
    (1, 4),
    (3, 4),
    (1, 5),
    (2, 5),
    (3, 5),
    (4, 5),
    (1, 10),
    (3, 10),
    (7, 10),
    (9, 10),
    (19, 20),
    (49, 50),
    (99, 100),
)
"""The shares a rate is said as, besides "1 in N" (the web's ``SHARES``, in its order)."""

NEVER: Final = 1
"""At or under this percent the sentence says "almost never"."""
ALWAYS: Final = 99
"""At or over this percent the sentence says "almost always"."""


@dataclass(frozen=True, slots=True)
class Share:
    """``some`` in ``of``, or more than that when ``more``."""

    some: int
    of: int
    more: bool


def _js_round(value: float) -> int:
    """JavaScript's ``Math.round``: half up."""
    return math.floor(value + 0.5)


@cache
def share_of(percent: int) -> Share:
    """The share the website says for ``percent`` (1 to 99), as ``shareOf`` does.

    Raises:
        ValueError: ``percent`` is not 1 to 99.
    """
    if not 1 <= percent <= 99:  # noqa: PLR2004 - a share is 1 to 99 percent
        raise ValueError(f"a share is 1 to 99 percent, not {percent}")
    one = _js_round(100 / percent)
    for some, of in (*SHARES, (1, one)):
        if _js_round(some * 100 / of) == percent:
            return Share(some, of, more=False)
    below = (1, 100)
    for some, of in (*SHARES, *((1, n + 2) for n in range(99))):
        if some * 100 / of <= percent - 0.5 and some / of > below[0] / below[1]:
            below = (some, of)
    return Share(below[0], below[1], more=True)


def _table() -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64], npt.NDArray[np.bool_]]:
    some = np.zeros(101, dtype=np.int64)
    of = np.ones(101, dtype=np.int64)
    more = np.zeros(101, dtype=np.bool_)
    for percent in range(NEVER + 1, ALWAYS):
        found = share_of(percent)
        some[percent], of[percent], more[percent] = found.some, found.of, found.more
    return some, of, more


_SOME, _OF, _MORE = _table()


def points_of(published: npt.NDArray[np.float64]) -> npt.NDArray[np.int64]:
    """The whole percent shown for a published chance (``round(100 * p)``, as the why's
    base points are)."""
    return np.clip(np.round(published * 100.0), 0, 100).astype(np.int64)


def says_true(
    points: npt.NDArray[np.int64],
    y: npt.NDArray[np.float64],
    n: npt.NDArray[np.float64],
    almost: float,
) -> npt.NDArray[np.bool_]:
    """Whether the base sentence for ``points`` is true of ``y`` closings of ``n`` recorded
    days, cell by cell (never true of no days)."""
    whole_y = np.rint(y).astype(np.int64)
    whole_n = np.rint(n).astype(np.int64)
    some_n = np.maximum(whole_n, 1)
    raw = whole_y / some_n
    # Half up, in whole numbers: floor((200 y + n) / (2 n)).
    rounded = (200 * whole_y + some_n) // (2 * some_n)
    at = np.clip(points, 0, 100)
    some, of, more = _SOME[at], _OF[at], _MORE[at]
    exact = rounded == at
    above = whole_y * of > some * some_n
    true = np.where(more, above, exact)
    true = np.where(at <= NEVER, raw < almost, true)
    true = np.where(at >= ALWAYS, raw > 1.0 - almost, true)
    return np.asarray(true & (whole_n > 0), dtype=np.bool_)


def say(points: int) -> str:
    """The share as the sentence words it, for reports and tests: "almost never",
    "3 in 4", "more than 3 in 5", "almost always"."""
    if points <= NEVER:
        return "almost never"
    if points >= ALWAYS:
        return "almost always"
    found = share_of(points)
    return f"{'more than ' if found.more else ''}{found.some} in {found.of}"
