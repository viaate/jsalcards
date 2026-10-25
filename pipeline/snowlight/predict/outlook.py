"""The outlook of S7-F (spec-f s. 6, decisions D5 and D6): which class a night like this ends in.

``T(c* | slot, c0, heads-up, f)`` is the share of cases whose 05:00 record was class ``c*``
(:mod:`snowlight.predict.outlook_states`), from the weather history alone, over seven
three-hour slots, each trained on the three sample hours spread across it. Cells: slot (7) x
``c0`` in {none, advisory} x heads-up (6) x forecast bucket ``f`` (14), each a distribution
over the 8 classes. Places: the nation, 9 climate regions, 48 states and DC.

* Back-off (decided on the nation's cell): a cell with fewer than 20 distinct nights merges
  ``f`` with the next bucket of its ladder (snow 1-5, ice 6-8, feels 9-12), the nearer side
  first (the larger amounts on a tie), until 20 nights or the whole ladder; then any ``f``;
  then any heads-up too. The nation always answers. The merged cell is the cell counted at
  every place (``like``: the bucket range, inclusive, and the heads-up, 6 for any).
* Shrinkage as c.1: ``T_region = (n_R + m_R T_nation) / (N_R + m_R)``, the state's toward its
  region's the same way, ``m`` from :data:`GRID` by leave-one-season-out log loss over the
  training seasons' cases.
* The scope a sentence may name (says_true): the most specific place whose merged cell holds
  20 or more nights, else the nation; its share is the raw count of that cell.

:func:`chance` is the one function the serving pass, the backtest and S7-L's score use: the
identity (the class's own rate, exactly today's path) when ``c0`` is a warning class, from
05:00 D, or when the outlook is not on; else ``p = sum_c T(c) p_d(c)`` and ``p_delay =
sum_c T(c) (1 - p_d(c)) q_d(c)`` over the classes ``T`` weighs, then the shipped clamp and
rounding. A row whose ``T`` is all zero (no forecast for it) or weighs a class with no rate
gets the identity too.
"""

import gzip
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.predict.config import PIPELINE_ROOT
from snowlight.predict.geography import REGION_OF, REGIONS, STATE_BY_FIPS
from snowlight.predict.pool import publish_rates
from snowlight.predict.situations import HeadsUp, WeatherClass

if TYPE_CHECKING:
    from snowlight.predict.artifact import ModelArtifact

type Floats = npt.NDArray[np.float64]
type Ints = npt.NDArray[np.int64]

CLASSES: Final = len(WeatherClass)
SLOTS: Final = 7
C0_VALUES: Final = 2
"""``c0`` in {none, advisory}: a warning issued ends the outlook (identity)."""
HEADS: Final = len(HeadsUp)
ANY_HEADS: Final = HEADS
"""``like``'s heads-up for "with or without one"."""
BUCKETS: Final = 14
QUIET: Final = 0
UNKNOWN: Final = 13
LADDERS: Final[tuple[tuple[int, ...], ...]] = ((1, 2, 3, 4, 5), (6, 7, 8), (9, 10, 11, 12))
"""Snow 0.5-2, 2-4, 4-6, 6-9, 9+ in; ice 0.01-0.10, 0.10-0.25, 0.25+ in; feels 10 to 0, 0 to
-10, -10 to -20, -20 F or colder (spec-f s. 4)."""
CELLS: Final = SLOTS * C0_VALUES * HEADS * BUCKETS
MIN_NIGHTS: Final = 20
GRID: Final[tuple[float, ...]] = (8.0, 32.0, 128.0, 512.0, 2048.0)
START_M: Final = 128.0
"""The strength kept when the training seasons leave none out (one season)."""
STATES: Final[tuple[str, ...]] = tuple(sorted(STATE_BY_FIPS.values()))
REGION_NAMES: Final[tuple[str, ...]] = tuple(sorted(REGIONS))
REGION_OF_STATE: Final[Ints] = np.array(
    [REGION_NAMES.index(REGION_OF[state]) for state in STATES], dtype=np.int64
)
SCOPES: Final[tuple[str, ...]] = ("state", "region", "nation")
ARTIFACT_PATH: Final = PIPELINE_ROOT / "data" / "predict" / "model-f.json.gz"
VERSION: Final = 3
_EPSILON: Final = 1e-6


class OutlookMode(StrEnum):
    """``PREDICT_OUTLOOK`` (spec-f D7): off (the default, S7-L's pass byte for byte), shadow
    (publish as off, record the outlook privately), on (publish the outlook)."""

    OFF = "off"
    SHADOW = "shadow"
    ON = "on"


def cell_of(slot: Ints, c0: Ints, heads: Ints, f: Ints) -> Ints:
    """The cell index of (slot 1-7, ``c0`` 0-1, heads-up 0-5, bucket 0-13)."""
    return (
        ((np.asarray(slot) - 1) * C0_VALUES + np.asarray(c0)) * HEADS * BUCKETS
        + np.asarray(heads) * BUCKETS
        + np.asarray(f)
    )


def cell_index(slot: int, c0: int, heads: int, f: int) -> int:
    """:func:`cell_of` of one cell."""
    return ((slot - 1) * C0_VALUES + c0) * HEADS * BUCKETS + heads * BUCKETS + f


def cell_parts(cell: int) -> tuple[int, int, int, int]:
    """(slot, c0, heads-up, bucket) of a cell index."""
    f = cell % BUCKETS
    heads = (cell // BUCKETS) % HEADS
    c0 = (cell // (BUCKETS * HEADS)) % C0_VALUES
    slot = cell // (BUCKETS * HEADS * C0_VALUES) + 1
    return slot, c0, heads, f


def ladder_of(f: int) -> tuple[int, ...] | None:
    """The ladder holding bucket ``f`` (none for quiet and unknown)."""
    for ladder in LADDERS:
        if f in ladder:
            return ladder
    return None


@dataclass(frozen=True, slots=True, order=True)
class Like:
    """The cell counted (spec-f s. 8 ``like``): the bucket range, inclusive, and the heads-up
    (6: any)."""

    low: int
    high: int
    heads: int

    def as_json(self) -> list[int]:
        """``[lo, hi, h]``."""
        return [self.low, self.high, self.heads]


def _members(slot: int, c0: int, like: Like) -> list[int]:
    heads = range(HEADS) if like.heads == ANY_HEADS else (like.heads,)
    return [cell_index(slot, c0, h, f) for h in heads for f in range(like.low, like.high + 1)]


def backoff(nights: npt.NDArray[np.bool_], minimum: int = MIN_NIGHTS) -> list[Like]:
    """Each cell's ``like`` from the nation's presence (``nights[night, cell]``: the cell held a
    case that night): see the module docstring."""
    found: list[Like] = []

    def count(slot: int, c0: int, like: Like) -> int:
        return int(nights[:, _members(slot, c0, like)].any(axis=1).sum())

    for cell in range(CELLS):
        slot, c0, heads, f = cell_parts(cell)
        like = Like(f, f, heads)
        ladder = ladder_of(f)
        if ladder is not None:
            while count(slot, c0, like) < minimum and (like.low, like.high) != (
                ladder[0],
                ladder[-1],
            ):
                down = like.low - 1 if like.low > ladder[0] else None
                up = like.high + 1 if like.high < ladder[-1] else None
                if up is not None and (down is None or up - f <= f - down):
                    like = Like(like.low, up, heads)
                else:
                    assert down is not None  # noqa: S101 - the range is not the whole ladder
                    like = Like(down, like.high, heads)
        if count(slot, c0, like) < minimum:
            like = Like(0, BUCKETS - 1, heads)
        if count(slot, c0, like) < minimum:
            like = Like(0, BUCKETS - 1, ANY_HEADS)
        found.append(like)
    return found


def membership(likes: Sequence[Like]) -> npt.NDArray[np.float64]:
    """``M[cell, member]`` = 1 when ``member`` is in the cell's merged cell."""
    matrix = np.zeros((CELLS, CELLS), dtype=np.float64)
    for cell, like in enumerate(likes):
        slot, c0, _heads, _f = cell_parts(cell)
        matrix[cell, _members(slot, c0, like)] = 1.0
    return matrix


@dataclass(frozen=True, slots=True)
class CaseCounts:
    """Training cases by state, cell and target class, and where each cell held cases."""

    state: Floats
    """Shape (states, cells, classes)."""
    nation_nights: npt.NDArray[np.bool_]
    """Shape (nights, cells)."""
    state_nights: npt.NDArray[np.bool_]
    """Shape (states, nights, cells)."""
    nights: tuple[object, ...] = ()

    @property
    def region(self) -> Floats:
        """Shape (regions, cells, classes)."""
        out = np.zeros((len(REGION_NAMES), CELLS, CLASSES))
        np.add.at(out, REGION_OF_STATE, self.state)
        return out


def training_cases(cases: pl.DataFrame) -> pl.DataFrame:
    """The rows of a case frame (:func:`~snowlight.predict.outlook_states.season_cases`) that
    train ``T``: sample hours (slots 1-7) with ``c0`` none or advisory and a known state, with
    ``slot``, ``cell`` and ``state_index``."""
    from snowlight.predict.outlook_states import SAMPLES  # noqa: PLC0415

    slot_of = {k: moment.slot for k, moment in enumerate(SAMPLES)}
    index = {state: i for i, state in enumerate(STATES)}
    return (
        cases.filter(
            (pl.col("moment") < len(SAMPLES))
            & (pl.col("c0") < C0_VALUES)
            & pl.col("state").is_in(list(STATES))
        )
        .with_columns(
            pl.col("moment").replace_strict(slot_of, return_dtype=pl.Int64).alias("slot"),
            pl.col("state").replace_strict(index, return_dtype=pl.Int64).alias("state_index"),
        )
        .with_columns(
            (
                ((pl.col("slot") - 1) * C0_VALUES + pl.col("c0").cast(pl.Int64)) * (HEADS * BUCKETS)
                + pl.col("h").cast(pl.Int64) * BUCKETS
                + pl.col("f").cast(pl.Int64)
            ).alias("cell")
        )
    )


def case_counts(train: pl.DataFrame, *, places: bool = False) -> CaseCounts:
    """Counts and presence from :func:`training_cases` rows (``places``: also where each state
    held each cell, for the scope of a sentence)."""
    nights = tuple(sorted(set(train["night"].to_list())))
    night_index = {night: i for i, night in enumerate(nights)}
    state = np.zeros((len(STATES), CELLS, CLASSES))
    s = train["state_index"].to_numpy().astype(np.int64)
    c = train["cell"].to_numpy().astype(np.int64)
    t = train["target"].to_numpy().astype(np.int64)
    n = train["n"].to_numpy().astype(np.float64)
    np.add.at(state, (s, c, t), n)
    night = np.array([night_index[x] for x in train["night"].to_list()], dtype=np.int64)
    nation_nights = np.zeros((len(nights), CELLS), dtype=np.bool_)
    nation_nights[night, c] = True
    state_nights = np.zeros((len(STATES) if places else 0, len(nights), CELLS), dtype=np.bool_)
    if places:
        state_nights[s, night, c] = True
    return CaseCounts(state, nation_nights, state_nights, nights)


@dataclass(frozen=True, slots=True)
class Outlook:
    """``T`` at every place, the merged cells and what a sentence may say of them."""

    likes: tuple[Like, ...]
    m_region: float
    m_state: float
    nation: Floats
    """Merged raw counts, shape (cells, classes)."""
    region: Floats
    """Shape (regions, cells, classes)."""
    state: Floats
    """Shape (states, cells, classes)."""
    nights_nation: Ints
    """Distinct nights of each merged cell, shape (cells,)."""
    nights_region: Ints
    """Shape (regions, cells)."""
    nights_state: Ints
    """Shape (states, cells)."""
    trials: tuple[tuple[float, float, float], ...] = field(default=())
    """(m_region, m_state, leave-one-season-out log loss) of each try."""

    def t_nation(self) -> Floats:
        """``T`` at the nation, shape (cells, classes): its raw shares (identity-free: a cell
        with no case at all keeps a zero row, which :meth:`distribution` reads as the
        identity)."""
        total = self.nation.sum(axis=1, keepdims=True)
        return np.divide(self.nation, total, out=np.zeros_like(self.nation), where=total > 0)

    def t_region(self) -> Floats:
        """``T`` at each region, shape (regions, cells, classes)."""
        nation = self.t_nation()[None, :, :]
        total = self.region.sum(axis=2, keepdims=True)
        return (self.region + self.m_region * nation) / (total + self.m_region)

    def t_state(self) -> Floats:
        """``T`` at each state, shape (states, cells, classes)."""
        region = self.t_region()[REGION_OF_STATE]
        total = self.state.sum(axis=2, keepdims=True)
        return (self.state + self.m_state * region) / (total + self.m_state)

    def distribution(  # noqa: PLR0913 - a case's four parts, its place and the table
        self,
        slot: Ints,
        c0: Ints,
        heads: Ints,
        f: Ints,
        state: Ints,
        *,
        table: Floats | None = None,
    ) -> Floats:
        """``T`` for each case (``state``: index into :data:`STATES`, -1 for the nation's),
        shape (cases, classes). A cell with no case anywhere reads as the identity (all its
        weight on ``c0``)."""
        values = self.t_state() if table is None else table
        cells = cell_of(slot, c0, heads, f)
        state_array = np.asarray(state, dtype=np.int64)
        out = np.where(
            (state_array >= 0)[:, None],
            values[np.maximum(state_array, 0), cells],
            self.t_nation()[cells],
        )
        empty = out.sum(axis=1) <= 0
        if empty.any():
            out[empty] = 0.0
            out[empty, np.asarray(c0, dtype=np.int64)[empty]] = 1.0
        return np.asarray(out, dtype=np.float64)

    def says(self, cell: int, state: int, to: int) -> tuple[str, float, int, int]:
        """What a sentence may say of the cell ``state`` counts for class ``to``: the scope
        (the most specific place whose merged cell holds 20 or more nights, else the nation),
        the raw share there, and its count and total (``share`` true of them)."""
        region = int(REGION_OF_STATE[state])
        options = (
            ("state", self.nights_state[state, cell], self.state[state, cell]),
            ("region", self.nights_region[region, cell], self.region[region, cell]),
            ("nation", self.nights_nation[cell], self.nation[cell]),
        )
        for scope, nights, counts in options:
            if scope == "nation" or nights >= MIN_NIGHTS:
                total = float(counts.sum())
                hit = float(counts[to])
                return scope, (hit / total if total else 0.0), int(hit), int(total)
        raise AssertionError("the nation always answers")  # pragma: no cover

    def as_json(self) -> dict[str, object]:
        """The outlook's counts, sparse: each merged cell once per place that holds cases of
        it, with its nights (``T`` is rebuilt from these and the strengths)."""
        keys: dict[tuple[int, int, int, int, int], int] = {}
        cells: list[int] = []
        for cell, like in enumerate(self.likes):
            slot, c0, _h, _f = cell_parts(cell)
            key = (slot, c0, like.low, like.high, like.heads)
            cells.append(keys.setdefault(key, len(keys)))
        first = {index: cells.index(index) for index in range(len(keys))}

        def entries(counts: Floats, nights: Ints) -> list[list[int]]:
            found: list[list[int]] = []
            for index in range(len(keys)):
                cell = first[index]
                row = counts[cell]
                if row.sum() > 0:
                    found.append([index, int(nights[cell]), *[int(x) for x in row]])
            return found

        return {
            "version": VERSION,
            "m_region": self.m_region,
            "m_state": self.m_state,
            "merged": [list(key) for key in keys],
            "cells": cells,
            "nation": entries(self.nation, self.nights_nation),
            "regions": {
                name: entries(self.region[i], self.nights_region[i])
                for i, name in enumerate(REGION_NAMES)
                if self.region[i].sum() > 0
            },
            "states": {
                name: entries(self.state[i], self.nights_state[i])
                for i, name in enumerate(STATES)
                if self.state[i].sum() > 0
            },
        }

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> "Outlook":
        """The outlook :meth:`as_json` wrote.

        Raises:
            ValueError: the data is not an outlook of this version.
        """
        if data.get("version") != VERSION:
            raise ValueError(f"not an outlook v{VERSION}: {data.get('version')!r}")
        merged = [tuple(int(x) for x in key) for key in data["merged"]]  # type: ignore[attr-defined]
        cells = [int(x) for x in data["cells"]]  # type: ignore[attr-defined]
        if len(cells) != CELLS:
            raise ValueError("the outlook's cells are not whole")
        likes = tuple(Like(key[2], key[3], key[4]) for key in (merged[i] for i in cells))

        def spread(items: object) -> tuple[Floats, Ints]:
            counts = np.zeros((CELLS, CLASSES))
            nights = np.zeros(CELLS, dtype=np.int64)
            by_key = {int(item[0]): item for item in items}  # type: ignore[attr-defined]
            for cell, index in enumerate(cells):
                item = by_key.get(index)
                if item is not None:
                    nights[cell] = int(item[1])
                    counts[cell] = np.array(item[2:], dtype=np.float64)
            return counts, nights

        nation, nights_nation = spread(data["nation"])
        region = np.zeros((len(REGION_NAMES), CELLS, CLASSES))
        nights_region = np.zeros((len(REGION_NAMES), CELLS), dtype=np.int64)
        for name, items in dict(data["regions"]).items():  # type: ignore[call-overload]
            i = REGION_NAMES.index(name)
            region[i], nights_region[i] = spread(items)
        state = np.zeros((len(STATES), CELLS, CLASSES))
        nights_state = np.zeros((len(STATES), CELLS), dtype=np.int64)
        for name, items in dict(data["states"]).items():  # type: ignore[call-overload]
            i = STATES.index(name)
            state[i], nights_state[i] = spread(items)
        return cls(
            likes,
            float(data["m_region"]),  # type: ignore[arg-type]
            float(data["m_state"]),  # type: ignore[arg-type]
            nation,
            region,
            state,
            nights_nation,
            nights_region,
            nights_state,
        )


def merged_nights(counts: CaseCounts, likes: Sequence[Like]) -> tuple[Ints, Ints, Ints]:
    """Distinct nights of each cell's merged cell at the nation, each region and each state
    (``counts`` made with ``places``)."""
    nation = np.zeros(CELLS, dtype=np.int64)
    region = np.zeros((len(REGION_NAMES), CELLS), dtype=np.int64)
    state = np.zeros((len(STATES), CELLS), dtype=np.int64)
    done: dict[tuple[int, ...], tuple[int, Ints, Ints]] = {}
    for cell, like in enumerate(likes):
        slot, c0, _h, _f = cell_parts(cell)
        members = tuple(_members(slot, c0, like))
        known = done.get(members)
        if known is None:
            present = counts.state_nights[:, :, list(members)].any(axis=2)
            by_region = np.zeros((len(REGION_NAMES), present.shape[1]), dtype=np.bool_)
            for s, r in enumerate(REGION_OF_STATE.tolist()):
                by_region[r] |= present[s]
            known = (
                int(counts.nation_nights[:, list(members)].any(axis=1).sum()),
                by_region.sum(axis=1).astype(np.int64),
                present.sum(axis=1).astype(np.int64),
            )
            done[members] = known
        nation[cell], region[:, cell], state[:, cell] = known
    return nation, region, state


def _merged(counts: CaseCounts, likes: Sequence[Like]) -> tuple[Floats, Floats, Floats]:
    matrix = membership(likes)
    state = np.einsum("mc,scx->smx", matrix, counts.state)
    region = np.zeros((len(REGION_NAMES), CELLS, CLASSES))
    np.add.at(region, REGION_OF_STATE, state)
    return state.sum(axis=0), region, state


def _shrunk(
    nation: Floats, region: Floats, state: Floats, m_region: float, m_state: float
) -> Floats:
    total = nation.sum(axis=1, keepdims=True)
    t_nation = np.divide(nation, total, out=np.zeros_like(nation), where=total > 0)
    t_region = (region + m_region * t_nation[None]) / (region.sum(axis=2, keepdims=True) + m_region)
    return (state + m_state * t_region[REGION_OF_STATE]) / (
        state.sum(axis=2, keepdims=True) + m_state
    )


def fit(cases: pl.DataFrame, seasons: Sequence[int], grid: Sequence[float] = GRID) -> Outlook:
    """``T`` from the cases of ``seasons`` (a frame with ``season`` beside the
    :func:`training_cases` columns), ``m`` by leave-one-season-out log loss."""
    inside = cases.filter(pl.col("season").is_in(list(seasons)))
    counts = case_counts(inside, places=True)
    likes = backoff(counts.nation_nights)
    trials: list[tuple[float, float, float]] = []
    m_region = m_state = START_M
    if len(seasons) >= 2:  # noqa: PLR2004 - one season leaves none out
        losses: dict[tuple[float, float], float] = {}
        for season in seasons:
            rest = case_counts(inside.filter(pl.col("season") != season))
            held = case_counts(inside.filter(pl.col("season") == season)).state
            rest_likes = backoff(rest.nation_nights)
            nation, region, state = _merged(rest, rest_likes)
            for m_r in grid:
                for m_s in grid:
                    t = np.clip(_shrunk(nation, region, state, m_r, m_s), _EPSILON, 1.0)
                    loss = -float((held * np.log(t)).sum())
                    losses[(m_r, m_s)] = losses.get((m_r, m_s), 0.0) + loss
        total = float(inside["n"].sum())
        for (m_r, m_s), loss in sorted(losses.items()):
            trials.append((m_r, m_s, loss / total))
        m_region, m_state = min(losses, key=lambda key: (losses[key], key))
    nation, region, state = _merged(counts, likes)
    nights_nation, nights_region, nights_state = merged_nights(counts, likes)
    return Outlook(
        tuple(likes),
        float(m_region),
        float(m_state),
        nation,
        region,
        state,
        nights_nation.astype(np.int64),
        nights_region.astype(np.int64),
        nights_state.astype(np.int64),
        tuple(trials),
    )


# --- the chance ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Chance:
    """The chances :func:`chance` gives: published no school and delay, and the raw no school."""

    p: Floats
    delay: Floats
    p_raw: Floats
    outlook: npt.NDArray[np.bool_]
    """Whether the outlook moved each chance's terms (else it is the class's own rate)."""
    fell_back: npt.NDArray[np.bool_]
    """Rows the outlook applied to that got the identity instead: no ``T`` for the row (an all
    zero row), or ``T`` puts weight on a class with no rate (NaN: nothing may be published
    under it), so the mixture cannot be published whole."""


ROW_SUM_TOLERANCE: Final = 1e-6
"""How far a ``T`` row may sum from 1 (float error only)."""


def chance(  # noqa: PLR0913 - the rates, the state and the switch
    p_class: Floats,
    q_class: Floats,
    c0: Ints,
    distribution: Floats | None,
    before_record: npt.NDArray[np.bool_],
    *,
    mode: OutlookMode,
    floor: float,
    ceiling: float,
) -> Chance:
    """The chance of no school and of a delay for each row (spec-f s. 6).

    ``p_class`` and ``q_class`` (rows, classes): the district's no-school rate and delay rate
    under each class, the day after a closing already chosen (``p_d(c, after)``), NaN under a
    class with no rate; ``c0`` the class issued; ``distribution`` ``T`` (rows, classes) or
    ``None``; ``before_record`` whether the pass is before 05:00 D. The identity (``p_d(c0)``,
    exactly today's path) when ``c0`` is a warning class, from 05:00 D, when ``mode`` is not on
    or there is no ``T``; else the mixture over the classes ``T`` weighs (a class of weight 0
    adds nothing, even with no rate). A row the outlook applies to also gets the identity
    (``fell_back``) when its ``T`` row is all zero, or when ``T`` weighs a class with no rate:
    never a NaN chance from a class with no rate, and never a mixture with a term dropped.
    Then the shipped clamp and rounding (:func:`~snowlight.predict.pool.publish_rates`).

    F3 passes ``distribution=None`` when the forecast is stale (lead decision
    ``Dark.FORECAST``: today's issued-alerts-only chance), and an all-zero row for a district
    whose forecast bucket is unknown.

    Raises:
        ValueError: ``distribution`` does not match ``p_class``, or a row it is used for is not
            finite, has a negative weight, or sums to neither 0 nor 1.
    """
    rows = np.arange(c0.size)
    own_p = p_class[rows, c0]
    own_q = q_class[rows, c0]
    wanted = (
        np.asarray(before_record, dtype=np.bool_)
        & (c0 < C0_VALUES)
        & (mode is OutlookMode.ON)
        & (distribution is not None)
    )
    use = wanted.copy()
    fell_back = np.zeros(c0.size, dtype=np.bool_)
    p_raw = own_p.copy()
    q = own_q.copy()
    if distribution is not None and wanted.any():
        table = np.asarray(distribution, dtype=np.float64)
        if table.shape != p_class.shape:
            raise ValueError(f"T is {table.shape}, the rates {p_class.shape}")
        t = table[wanted]
        if not np.isfinite(t).all() or (t < 0).any():
            raise ValueError("a T row is not finite or has a negative weight")
        sums = t.sum(axis=1)
        empty = sums == 0
        if (np.abs(sums[~empty] - 1.0) > ROW_SUM_TOLERANCE).any():
            raise ValueError("a T row sums to neither 0 nor 1")
        weighted = t > 0
        p_rates = p_class[wanted]
        q_rates = q_class[wanted]
        rated = np.isfinite(p_rates) & np.isfinite(q_rates)
        whole = ~empty & ~(weighted & ~rated).any(axis=1)
        mix_p = np.where(weighted & rated, t * p_rates, 0.0).sum(axis=1)
        mix_delay = np.where(weighted & rated, t * (1.0 - p_rates) * q_rates, 0.0).sum(axis=1)
        where = np.flatnonzero(wanted)
        use[where[~whole]] = False
        fell_back[where[~whole]] = True
        kept = where[whole]
        p_raw[kept] = mix_p[whole]
        q[kept] = np.divide(
            mix_delay[whole],
            1.0 - mix_p[whole],
            out=np.zeros(int(whole.sum())),
            where=(1.0 - mix_p[whole]) > 0,
        )
    p, delay = publish_rates(p_raw, q, floor, ceiling)
    return Chance(p, delay, p_raw, use, fell_back)


def class_rates(matrix: Floats, district: Ints, after: npt.NDArray[np.bool_]) -> Floats:
    """``p_d(c, after)`` for each row and class, from a chain over every (district, situation)
    (:func:`~snowlight.predict.pool.chain` with no cells): the day after a closing counts for
    none and advisory only."""
    from snowlight.predict.pool import SITUATION_INDEX  # noqa: PLC0415
    from snowlight.predict.situations import Situation  # noqa: PLC0415

    plain = np.array(
        [SITUATION_INDEX[Situation.of(WeatherClass(c), after=False).key] for c in range(CLASSES)]
    )
    later = np.array(
        [SITUATION_INDEX[Situation.of(WeatherClass(c), after=True).key] for c in range(CLASSES)]
    )
    columns = np.where(np.asarray(after, dtype=np.bool_)[:, None], later[None], plain[None])
    return np.asarray(matrix[np.asarray(district)[:, None], columns], dtype=np.float64)


# --- the artifact (v3) --------------------------------------------------------------------------


def write_artifact(path: Path, rates: Mapping[str, object], outlook: Outlook) -> int:
    """Write ``model-f.json.gz``: the 05:00 rates (a v2 model's JSON) and the outlook's counts.
    Returns its size in bytes."""
    body = json.dumps(
        {"version": VERSION, "snapshot_at": "05:00", "rates": rates, "outlook": outlook.as_json()},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    data = gzip.compress(body, compresslevel=9, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)


def read_artifact(path: Path) -> tuple[dict[str, object], Outlook]:
    """The rates' JSON and the outlook of a ``model-f.json.gz``.

    Raises:
        ValueError: the file is not a v3 artifact.
    """
    data = json.loads(gzip.decompress(path.read_bytes()))
    if data.get("version") != VERSION or data.get("snapshot_at") != "05:00":
        raise ValueError(f"{path}: not a model v{VERSION} with the 05:00 record")
    return dict(data["rates"]), Outlook.from_json(data["outlook"])


def read_rates(path: Path = ARTIFACT_PATH) -> "ModelArtifact":
    """The 05:00 rates of a ``model-f.json.gz`` as a v2 model (checked as ``model.json.gz``
    is).

    Raises:
        ValueError: the file is not a v3 artifact.
        pydantic.ValidationError: its rates are not a model.
    """
    from snowlight.predict.artifact import ModelArtifact  # noqa: PLC0415

    rates, _outlook = read_artifact(path)
    return ModelArtifact.model_validate_json(json.dumps(rates), strict=False)
