"""Each airport's own record in bad weather (D8), the habit box of Flights, by the lead's rulings
LR-F1 (the test counts days, not flights or blocks) and LR-F5 (the test holds under its own null).

For each weather kind (:class:`snowlight.flights.obs.Kind`), the airport's blocks of that kind
(from the hourly reports) and the share of their departures cancelled. The record holds the
airport to its same-day peers: on each day of the kind, the other airports that had the same
weather kind that day, their blocks of it pooled by departures. Days the cancels had nothing to
do with weather (:data:`snowlight.flights.spans.NOT_WEATHER`) are never counted, and days with
no peer in that weather are not the airport's matched days.

A matched day counts toward the test only when the airport's departures times the peers' share
that day are at least :data:`MIN_EXPECTED` (on fewer, one cancel or none decides the day by luck);
every matched day still counts in the plain numbers. On each counted day the airport's cancelled
share is set against the peers': WORSE when it is at least :data:`DAY_POINTS` above and at least
:data:`DAY_RATIO` times theirs, BETTER the other way round, else a tie (dropped). A verdict needs,
all the same way (:func:`line_test`):

- at least :data:`MIN_UNTIED` untied counted days,
- the number of BETTER among them far from its exact law had the airport cancelled at its peers'
  share each day (each day's own chance of BETTER given untied, never 1 in 2), two-sided under the
  habit box's luck (``HABIT_LUCK``, as in ``web/src/app/steps.ts``),
- its cancels over all matched days far from its peers' same-day shares at its departures, with
  the day-to-day spread (:func:`clustered_p`), under the same luck, and
- the pooled shares over the matched days (the airport's, and the peers' at its departures each
  day) at least :data:`POOLED_RATIO` times apart, both as computed and as published (per mille).

WORSE: it cancels sooner than most; BETTER: it holds out longer than most. Otherwise there is no
verdict and the box states the numbers alone (no words for a record like the others'). Few
verdicts is the right answer when the counts are small.

Each carrier at the airport is held the same way to the other carriers at the same airport in the
same weather blocks on the same day.
"""

import math
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import polars as pl
from scipy import stats  # type: ignore[import-untyped]

from snowlight.flights.obs import KINDS, Kind
from snowlight.flights.spans import weather_days, weather_rows

HABIT_LUCK: Final = 0.05
DAY_POINTS: Final = 0.02
"""A day is WORSE (BETTER) only when the shares are at least this far apart (2 points)."""
DAY_RATIO: Final = 1.5
"""... and the higher at least this many times the lower."""
MIN_UNTIED: Final = 8
"""Untied counted days a verdict needs."""
MIN_EXPECTED: Final = 1
"""A day counts toward the test only when its expected cancels at the peers' share that day
(departures times the peers' share) are at least this many (LR-F5): on fewer departures one
cancel, or none, crosses the WORSE and BETTER lines by luck alone."""
POOLED_RATIO: Final = 1.25
"""The pooled shares over the matched days must be this many times apart the verdict's way."""
MIN_SPREAD_LINES: Final = 5
"""The day clustering of a weather kind is read from its own lines when at least this many give
one (:func:`day_clustering`), else from all the group's lines."""
MAX_CLUSTERING: Final = 0.99
_DAY_COLUMNS: Final = ("ns", "cancs", "pns", "pcs")
MIN_BLOCK_FLIGHTS: Final = 3
BAD_SHARE: Final = 0.10
MIN_CARRIER_FLIGHTS: Final = 2


class Verdict(IntEnum):
    """What an airport's (or carrier's) record says (the habit box's words). Value 1 (the
    retired middle verdict) is never given."""

    NONE = 0
    """No verdict: the box gives the numbers alone."""
    SOONER = 2
    """Cancels sooner than most."""
    LONGER = 3
    """Holds out longer than most."""


def per_mille(share: float) -> int:
    """A share as published (per mille, 0 to 1000)."""
    return max(0, min(1000, round(1000 * share)))


def _marks(
    k: npt.NDArray[np.int64],
    n: npt.NDArray[np.int64],
    pn: npt.NDArray[np.int64],
    pc: npt.NDArray[np.int64],
) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
    """WORSE and BETTER for ``k`` cancels of ``n`` departures beside the peers' ``pc`` of
    ``pn``, exact in integers: ``k/n - pc/pn >= 1/50`` and ``k/n >= 1.5 pc/pn`` (BETTER the
    other way round)."""
    mine, theirs, both = k * pn, pc * n, n * pn
    points = round(1 / DAY_POINTS)
    twice = round(2 * DAY_RATIO)
    worse = (points * (mine - theirs) >= both) & (2 * mine >= twice * theirs)
    better = (points * (theirs - mine) >= both) & (2 * theirs >= twice * mine)
    return worse, better


def day_chances(
    n: npt.NDArray[np.int64],
    pn: npt.NDArray[np.int64],
    pc: npt.NDArray[np.int64],
    rho: float = 0.0,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Each day's chance of WORSE and of BETTER had the line cancelled at its peers' share
    that day, by the same lines as :func:`_marks`: ``Binomial(n, pc/pn)`` when ``rho`` is 0,
    else the beta-binomial of that mean whose day-to-day clustering is ``rho`` (the share of a
    day's spread shared by its departures, :func:`day_clustering`), so that the many quiet days
    and few lost banks of clustered cancels never read as a line that holds out longer."""
    points = round(1 / DAY_POINTS)
    # WORSE from the fewest cancels k with points (k pn - pc n) >= n pn and 2 k pn >= 3 pc n.
    first = np.maximum(-(-(n * (pn + points * pc)) // (points * pn)), -(-(3 * pc * n) // (2 * pn)))
    # BETTER up to the most cancels k with points (pc n - k pn) >= n pn and 2 pc n >= 3 k pn.
    last = np.minimum((n * (points * pc - pn)) // (points * pn), (2 * pc * n) // (3 * pn))
    share = pc / pn
    if rho > 0:
        size = (1 - rho) / rho
        mean = np.clip(share, 1e-9, 1 - 1e-9)
        law = stats.betabinom(n, mean * size, (1 - mean) * size)
    else:
        law = stats.binom(n, share)
    worse = np.where(first <= n, law.sf(np.maximum(first - 1, 0)), 0.0)
    better = np.where(last >= 0, law.cdf(np.maximum(last, 0)), 0.0)
    return worse.astype(np.float64), better.astype(np.float64)


def line_clustering(
    n: npt.NDArray[np.int64], canc: npt.NDArray[np.int64], share: npt.NDArray[np.float64]
) -> tuple[float, float] | None:
    """One line's day clustering by moments against its peers' same-day shares, as its two
    sums: the excess of its squared day gaps over the binomial spread, and
    ``sum n (n - 1) s (1 - s)`` (their ratio is the line's estimate); ``None`` when its days
    hold no spread to read."""
    usable = (share > 0) & (share < 1) & (n > 1)
    if not usable.any():
        return None
    nu, cu, su = n[usable].astype(np.float64), canc[usable].astype(np.float64), share[usable]
    den = float((nu * (nu - 1) * su * (1 - su)).sum())
    if den <= 0:
        return None
    return float(((cu - nu * su) ** 2 - nu * su * (1 - su)).sum()), den


def day_clustering(each: list[tuple[float, float]]) -> float:
    """The day clustering the own-record test assumes for a set of lines (R6-S1): the larger of
    the median of the lines' own estimates (so a few big lines never lower it for the many
    small ones) and the pooled estimate over all their days (where the big lines, whose banks
    go together on a storm day, weigh most), between 0 and :data:`MAX_CLUSTERING`. Both
    include the lines' own true differences, so it errs toward more spread (fewer verdicts),
    never less."""
    if not each:
        return 0.0
    median = float(np.median([num / den for num, den in each]))
    pooled = sum(num for num, _ in each) / sum(den for _, den in each)
    return float(min(MAX_CLUSTERING, max(0.0, median, pooled)))


def poisson_binomial_p(q: npt.NDArray[np.float64], hits: int) -> tuple[float, float]:
    """The exact chances of at most and of at least ``hits`` successes among independent days
    with chances ``q`` (the Poisson-binomial tails)."""
    dist = np.ones(1)
    for chance in q:
        grown = np.zeros(len(dist) + 1)
        grown[:-1] += dist * (1 - chance)
        grown[1:] += dist * chance
        dist = grown
    return float(min(1.0, dist[: hits + 1].sum())), float(min(1.0, dist[hits:].sum()))


def clustered_p(
    canc: npt.NDArray[np.int64],
    expected: npt.NDArray[np.float64],
    share: npt.NDArray[np.float64],
    rho: float = 0.0,
    n: npt.NDArray[np.int64] | None = None,
) -> float:
    """The two-sided chance of the line's cancels over its days standing this far from what its
    peers' same-day shares give, by luck alone. The spread is the larger of the line's own
    day-to-day spread (so a few days of whole banks gone never look sure) and the beta-binomial
    spread at the peers' share with the day clustering ``rho`` of the line's departures ``n``
    (so a sample that missed the rare big days, low in both its gap and its own spread, never
    looks sure; at ``rho`` 0 the binomial spread, so a run of no-cancel days on few departures
    never looks sure either)."""
    gap = float((canc - expected).sum())
    grow = 1 + (n - 1) * rho if n is not None and rho > 0 else 1.0
    spread = max(
        float(((canc - expected) ** 2).sum()), float((expected * (1 - share) * grow).sum())
    )
    if spread <= 0:
        return 1.0
    return float(math.erfc(abs(gap) / math.sqrt(2 * spread)))


def _apart(high: float, low: float) -> bool:
    """The pooled guard: ``high`` at least :data:`POOLED_RATIO` times ``low``, as computed and
    as published (per mille), and above none as published."""
    shown_high, shown_low = per_mille(high), per_mille(low)
    return high >= POOLED_RATIO * low and shown_high > 0 and 4 * shown_high >= 5 * shown_low


@dataclass(frozen=True, slots=True)
class Test:
    """The own-record test of one line over its matched days (LR-F1 as amended by LR-F5)."""

    verdict: Verdict
    worse: int
    """WORSE days among the days the test counts."""
    better: int
    """BETTER days among the days the test counts."""
    share: float
    """The line's pooled share over all its matched days."""
    others: float
    """Its peers' share over the same days, each day's at the line's own departures."""


def line_test(
    n: npt.NDArray[np.int64],
    canc: npt.NDArray[np.int64],
    pn: npt.NDArray[np.int64],
    pc: npt.NDArray[np.int64],
    rho: float = 0.0,
) -> Test:
    """The verdict of a line from its matched days: its departures ``n`` and cancels ``canc``
    each day, beside its peers' ``pn`` and ``pc`` that day.

    A day counts toward the test only when its expected cancels at the peers' share are at least
    one (:data:`MIN_EXPECTED`); others still count in the plain numbers. On the counted days
    WORSE and BETTER are marked, and the number of BETTER among the untied days is held to its
    exact Poisson-binomial law under the peers' same-day shares (each day's chance of BETTER
    given untied, not 1 in 2), each day's chance read with the day clustering ``rho`` of the
    line's weather kind (:func:`day_clustering`; 0 is the binomial). A verdict needs at least
    :data:`MIN_UNTIED` untied days, that test, the day-clustered test of the pooled cancels
    (:func:`clustered_p`) and the pooled shares :data:`POOLED_RATIO` times apart (as computed
    and as published), all the same way."""
    flights = int(n.sum())
    share_each = pc / pn
    expected = n * share_each
    share = float(canc.sum()) / flights if flights else 0.0
    others = float(expected.sum()) / flights if flights else 0.0
    counted = n * pc >= MIN_EXPECTED * pn
    worse_days, better_days = _marks(canc, n, pn, pc)
    worse_days &= counted
    better_days &= counted
    worse, better = int(worse_days.sum()), int(better_days.sum())
    verdict = Verdict.NONE
    if worse + better >= MIN_UNTIED and flights > 0:
        untied = worse_days | better_days
        chance_worse, chance_better = day_chances(n[untied], pn[untied], pc[untied], rho)
        both = chance_worse + chance_better
        q = np.where(both > 0, chance_better / np.where(both > 0, both, 1.0), 0.5)
        few, many = poisson_binomial_p(q, better)
        lucky = clustered_p(canc, expected, share_each, rho, n) >= HABIT_LUCK
        gap = float(canc.sum()) - float(expected.sum())
        if not lucky and 2 * few < HABIT_LUCK and gap > 0 and worse > better:
            verdict = Verdict.SOONER if _apart(share, others) else Verdict.NONE
        if not lucky and 2 * many < HABIT_LUCK and gap < 0 and better > worse:
            verdict = Verdict.LONGER if _apart(others, share) else Verdict.NONE
    return Test(verdict, worse, better, share, others)


@dataclass(frozen=True, slots=True)
class Line:
    """One airport's (or carrier's) record in one weather kind, over its matched days."""

    kind: Kind
    blocks: int
    bad: int
    days: int
    """Matched days: days with a block of this weather and a peer in it."""
    bad_days: int
    share: float
    """The share of its departures cancelled in those blocks."""
    others_share: float
    """The same-day peers' share on those days, each day's at the line's own departures that
    day (so a line of only storm days is held to its peers' storm days, never to their mild
    ones)."""
    worse: int
    """Days the test counts on which it cancelled clearly more than its peers that day."""
    better: int
    """Days the test counts on which it cancelled clearly fewer."""
    verdict: Verdict


def _bad(frame: pl.LazyFrame) -> pl.LazyFrame:
    return frame.filter(pl.col("n") >= MIN_BLOCK_FLIGHTS).with_columns(
        (pl.col("canc") >= BAD_SHARE * pl.col("n")).alias("bad")
    )


def _lines(
    marked: pl.LazyFrame, keys: list[str], within: list[str]
) -> list[tuple[dict[str, object], Line]]:
    """Each line's record (``keys``: the line, such as airport and kind), held on each day to
    the others in ``within`` that day (such as the kind, or the airport and kind)."""
    per_day = marked.group_by(*keys, "day").agg(
        pl.len().alias("blocks"),
        pl.col("bad").sum().alias("bad"),
        pl.col("n").cast(pl.Int64).sum(),
        pl.col("canc").cast(pl.Int64).sum(),
    )
    totals = per_day.group_by(*within, "day").agg(pl.col("n", "canc").sum().name.suffix("_all"))
    days = (
        per_day.join(totals, on=[*within, "day"])
        .with_columns(
            (pl.col("n_all") - pl.col("n")).alias("pn"),
            (pl.col("canc_all") - pl.col("canc")).alias("pc"),
        )
        .filter(pl.col("pn") > 0)
        .sort(*keys, "day")
    )
    per = (
        days.group_by(*keys, maintain_order=True)
        .agg(
            pl.col("blocks").sum(),
            pl.col("bad").sum(),
            pl.len().alias("days"),
            (pl.col("bad") > 0).sum().alias("bad_days"),
            pl.col("n").alias("ns"),
            pl.col("canc").alias("cancs"),
            pl.col("pn").alias("pns"),
            pl.col("pc").alias("pcs"),
        )
        .sort(*keys)
        .collect()
    )
    type Days = npt.NDArray[np.int64]
    rows: list[tuple[dict[str, Any], Days, Days, Days, Days]] = []
    for row in per.iter_rows(named=True):
        n, canc, pn, pc = (np.asarray(row[name], dtype=np.int64) for name in _DAY_COLUMNS)
        rows.append((row, n, canc, pn, pc))
    own: dict[int, list[tuple[float, float]]] = {}
    for row, n, canc, pn, pc in rows:
        found = line_clustering(n, canc, pc / pn)
        if found is not None:
            own.setdefault(int(row["kind"]), []).append(found)
    every = day_clustering([value for values in own.values() for value in values])
    rho = {
        kind: day_clustering(values) if len(values) >= MIN_SPREAD_LINES else every
        for kind, values in own.items()
    }
    out: list[tuple[dict[str, object], Line]] = []
    for row, n, canc, pn, pc in rows:
        test = line_test(n, canc, pn, pc, rho.get(int(row["kind"]), every))
        line = Line(
            kind=Kind(int(row["kind"])),
            blocks=int(row["blocks"]),
            bad=int(row["bad"]),
            days=int(row["days"]),
            bad_days=int(row["bad_days"]),
            share=test.share,
            others_share=test.others,
            worse=test.worse,
            better=test.better,
            verdict=test.verdict,
        )
        out.append((row, line))
    return out


def airport_lines(dep_blocks: pl.LazyFrame, kinds: pl.LazyFrame) -> dict[str, list[Line]]:
    """Each airport's record per weather kind.

    ``dep_blocks``: departures per airport, day and block (summed over carriers); ``kinds``:
    ``apt``, ``day``, ``block``, ``kind`` (:func:`snowlight.flights.obs.block_kinds`).
    """
    joined = _bad(
        dep_blocks.filter(weather_days()).join(
            kinds.select("apt", "day", "block", "kind"), on=["apt", "day", "block"]
        )
    ).filter(pl.col("kind") > 0)
    out: dict[str, list[Line]] = {}
    for row, line in _lines(joined, ["apt", "kind"], ["kind"]):
        out.setdefault(str(row["apt"]), []).append(line)
    for lines in out.values():
        lines.sort(key=lambda line: KINDS.index(line.kind))
    return out


def carrier_lines(
    dep_carriers: pl.LazyFrame, kinds: pl.LazyFrame
) -> dict[tuple[str, str], list[Line]]:
    """Each carrier's record at each airport per weather kind, against the other carriers in
    the same weather at the same airport on the same day.

    ``dep_carriers``: the ``dep`` table (per carrier; codes current).
    """
    blocks = (
        dep_carriers.filter(weather_rows())
        .join(
            kinds.filter(pl.col("kind") > 0).select("apt", "day", "block", "kind"),
            on=["apt", "day", "block"],
        )
        .filter(pl.col("n") >= MIN_CARRIER_FLIGHTS)
    )
    marked = blocks.with_columns((pl.col("canc") >= BAD_SHARE * pl.col("n")).alias("bad"))
    out: dict[tuple[str, str], list[Line]] = {}
    for row, line in _lines(marked, ["apt", "carrier", "kind"], ["apt", "kind"]):
        out.setdefault((str(row["apt"]), str(row["carrier"])), []).append(line)
    return out
