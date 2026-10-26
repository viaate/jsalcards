"""S7-L for the night-before outlook (S7-F, spec-f s. 10; piece F3): the live cases, the
held-out swap of ``T`` and the internal report, run by ``predict learn`` while
``PREDICT_OUTLOOK`` is shadow or on.

Each run of the learning step:

1. **Moves the record**: the serving passes' newest days (their private state,
   :mod:`snowlight.predict.outlook_record`) are merged into ``predictions/outlook/record.json``
   on the live host, beside ``learn.json``, which keeps 10 school days.
2. **Counts the live cases** of every day whose 05:00 record is taken and that is over: one
   case per district and sample hour taken, with nothing or an advisory issued (``c0``), its
   heads-up, its forecast bucket and its 05:00 class as the target, kept as counts by state,
   cell and target per day in ``predictions/outlook/cases.json`` (frozen once counted: a rerun
   changes nothing). No list text: counts of NOAA states only.
3. **Swaps ``T``** (:func:`decide`): the candidate is the committed ``T`` counted with the live
   days before the newest :data:`HELD_DAYS` school days, and it is judged on those held-out
   days' cases against every ``T`` that has not counted them and is not the candidate itself
   (:func:`judges`): the committed ``T`` (the archive alone) always, and the served ``T``
   without the held-out days when that differs from both. Its log loss must be no worse than
   each judge's, every calibration bin of 2,000 cases or more in bounds (GF5's rule), and,
   with 300 or more labeled rows of the held-out days with no warning issued by 8 PM (E20),
   its E20 Brier no worse than each judge's; then the refit over every live day is swapped in
   (``predictions/outlook/learned.json``, made over the committed artifact's SHA-256). No judge
   is ever the served ``T`` with the held-out days in it (it would be judged on days it has
   seen) nor the candidate (once ``T`` swaps nightly the served ``T`` without the held-out
   days is the candidate, and a check against itself could never reject). So a run with a new
   day can still swap nightly, while live days that hurt ``T`` on the days after them (a
   record-taking fault, a stretch unlike the archive) keep ``T`` where it is until the
   candidate beats the archive alone again. A run with no new live day changes nothing.
4. **Reports** (``predictions/outlook/report.json``, never on the site): the night-before
   calibration by slot from the labeled live days, the outlook's chance against the v2 rates'
   (the identity under the 21:00 rates), and the recorded 8 PM chances, S7-F's (shadow) against
   the published ones.

Nothing here can change what the passes publish while the outlook is shadow: the record, the
cases, the learned ``T`` and the report are read by the shadow record and by ``on`` only.
"""

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Final, Literal

import numpy as np
import numpy.typing as npt
import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from snowlight.output import dumps_json
from snowlight.predict import outlook as outlook_module
from snowlight.predict.calendar import is_school_day, previous_school_day
from snowlight.predict.outlook import (
    C0_VALUES,
    CELLS,
    CLASSES,
    Outlook,
    OutlookMode,
    cell_index,
    chance,
    membership,
)
from snowlight.predict.outlook_record import (
    NOT_TAKEN8,
    NOT_TAKEN16,
    Record,
    unpack,
)
from snowlight.predict.outlook_serve import OutlookServe, class_matrix
from snowlight.predict.outlook_states import SAMPLES
from snowlight.predict.serve import ServeModel

CASES_PATH: Final = "predictions/outlook/cases.json"
RATES_STORE_PATH: Final = "predictions/outlook/learn.json"
"""The live labels counted under the 05:00 record's class (the v3 rates' own store)."""
RATES_LEARNED_PATH: Final = "predictions/outlook/learned-rates.json"
"""The v3 rates' learned file (made over ``model-f.json.gz``), as S7-L's ``learned.json``."""
LEARNED_PATH: Final = "predictions/outlook/learned.json"
REPORT_PATH: Final = "predictions/outlook/report.json"
HELD_DAYS: Final = 7
"""The newest live school days a candidate ``T`` is judged on (spec-f s. 10)."""
E20_MIN_ROWS: Final = 300
"""With this many labeled E20 rows held out, a swap also needs an E20 Brier no worse."""
GF5_MIN_CASES: Final = 2000
E20_SAMPLE: Final = 12
"""The 20:00 sample hour (08:00 + 12)."""
_STATES: Final = len(outlook_module.STATES)
_TIE: Final = 1e-12
_SLOT_MOMENT: Final = {
    slot: next(k for k, moment in enumerate(SAMPLES) if moment.slot == slot) for slot in range(1, 8)
}
"""A sample hour of each slot (the calibration groups cases by slot)."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


type CaseRow = tuple[
    Annotated[int, Field(ge=0, lt=_STATES)],
    Annotated[int, Field(ge=0, lt=CELLS)],
    Annotated[int, Field(ge=0, lt=CLASSES)],
    Annotated[int, Field(ge=1)],
]
"""(state index, cell, target class, cases)."""


class CaseDay(_Model):
    """One live school day's cases: counts by state, cell and 05:00 class."""

    day: date
    rows: tuple[CaseRow, ...]

    @model_validator(mode="after")
    def _check(self) -> "CaseDay":
        keys = [row[:3] for row in self.rows]
        if keys != sorted(set(keys)):
            raise ValueError(f"{self.day}: rows must be sorted and unique")
        return self


class LiveCases(_Model):
    """``predictions/outlook/cases.json``: every counted live day."""

    schema_version: Literal[1]
    days: tuple[CaseDay, ...]

    @model_validator(mode="after")
    def _check(self) -> "LiveCases":
        found = [item.day for item in self.days]
        if found != sorted(set(found)):
            raise ValueError("days must be sorted and unique")
        return self

    @classmethod
    def empty(cls) -> "LiveCases":
        """No live day counted yet."""
        return cls(schema_version=1, days=())

    def to_bytes(self) -> bytes:
        """Key-sorted JSON."""
        return dumps_json(self.model_dump(mode="json"))

    @classmethod
    def from_bytes(cls, data: bytes) -> "LiveCases":
        """Read a ``cases.json``.

        Raises:
            pydantic.ValidationError: it is not one.
        """
        return cls.model_validate_json(data, strict=False)


class LearnedOutlook(_Model):
    """``predictions/outlook/learned.json``: the live days counted into ``T`` over a committed
    artifact, and the check the swap passed."""

    schema_version: Literal[1]
    artifact_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    through: date
    days: tuple[CaseDay, ...]
    check: dict[str, float | int]
    made_at: datetime

    def to_bytes(self) -> bytes:
        """Key-sorted JSON."""
        return dumps_json(self.model_dump(mode="json"))

    @classmethod
    def from_bytes(cls, data: bytes) -> "LearnedOutlook":
        """Read a ``learned.json``.

        Raises:
            pydantic.ValidationError: it is not one.
        """
        return cls.model_validate_json(data, strict=False)


# --- T with live days ----------------------------------------------------------------------------


def with_live(table: Outlook, days: Sequence[CaseDay]) -> Outlook:
    """``T`` with the live days' cases counted in: each raw cell's cases go to every merged
    cell that holds it (the committed back-off is kept), and each live night adds one night to
    every merged cell it held a case of, at its state, region and the nation."""
    if not days:
        return table
    matrix = membership(table.likes)
    state = table.state.copy()
    nights_state = table.nights_state.copy()
    nights_region = table.nights_region.copy()
    nights_nation = table.nights_nation.copy()
    regions = outlook_module.REGION_OF_STATE
    total = np.zeros((_STATES, CELLS, CLASSES))
    for item in days:
        merged_present = np.zeros((_STATES, matrix.shape[0]), dtype=np.bool_)
        if item.rows:
            held = np.array([row[:3] for row in item.rows], dtype=np.int64)
            np.add.at(total, (held[:, 0], held[:, 1], held[:, 2]), [row[3] for row in item.rows])
            # Only the states and cells the day holds (a day is sparse: a few states' cells).
            states, cells = np.unique(held[:, 0]), np.unique(held[:, 1])
            present = np.zeros((states.size, cells.size))
            present[np.searchsorted(states, held[:, 0]), np.searchsorted(cells, held[:, 1])] = 1.0
            merged_present[states] = (present @ matrix[:, cells].T) > 0
        nights_state += merged_present.astype(np.int64)
        by_region = np.zeros(nights_region.shape, dtype=np.bool_)
        for s in range(_STATES):
            by_region[regions[s]] |= merged_present[s]
        nights_region += by_region.astype(np.int64)
        nights_nation += merged_present.any(axis=0).astype(np.int64)
    # Each merged cell holds its raw cells' cases (whole counts: the sum is exact in any order).
    states = np.flatnonzero(total.any(axis=(1, 2)))
    cells = np.flatnonzero(total.any(axis=(0, 2)))
    state[states] += np.matmul(matrix[:, cells], total[np.ix_(states, cells)])
    region = np.zeros(table.region.shape)
    np.add.at(region, regions, state)
    # The nation's counts are the states' plus the committed counts outside any state.
    nation = table.nation + (state - table.state).sum(axis=0)
    region = table.region + (region - _regions_of(table.state))
    return Outlook(
        table.likes,
        table.m_region,
        table.m_state,
        nation,
        region,
        state,
        nights_nation,
        nights_region,
        nights_state,
        table.trials,
    )


def _regions_of(state: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    found = np.zeros((len(outlook_module.REGION_NAMES), *state.shape[1:]))
    np.add.at(found, outlook_module.REGION_OF_STATE, state)
    return found


def served_outlook(
    table: Outlook, data: bytes | None, artifact_sha256: str
) -> tuple[Outlook, str | None]:
    """The ``T`` the passes use: the committed one with a learned file's live days, when there
    is one made over this artifact that reads; else the committed one and why (``None``: no
    learned file)."""
    if data is None:
        return table, None
    try:
        learned = LearnedOutlook.from_bytes(data)
    except ValueError as error:
        return table, f"the learned outlook does not validate ({type(error).__name__})"
    if learned.artifact_sha256 != artifact_sha256:
        return table, "the learned outlook was made over another artifact"
    return with_live(table, learned.days), None


# --- the live cases ------------------------------------------------------------------------------


def day_cases(
    record: Record, day: date, zones: Sequence[str], states: npt.NDArray[np.int64]
) -> CaseDay | None:
    """The cases of ``day`` from the record (``zones``, ``states``: each district's zone and
    state index, -1 outside the states ``T`` knows), or ``None`` when its 05:00 record is not
    taken in any zone. A sample counts a district only where both it and the 05:00 record were
    taken for its zone (``None`` too when the day holds no case: a later run tries again
    while the record keeps it)."""
    entry = record.days.get(day)
    if entry is None or entry.morning is None or not entry.morning.taken:
        return None
    target = entry.morning.values
    counts: dict[tuple[int, int, int], int] = {}
    zone_of = np.array(zones, dtype=object)
    for k, part in sorted(entry.samples.items()):
        slot = SAMPLES[k].slot
        both = [zone for zone in part.taken if zone in entry.morning.taken]
        if not both:
            continue
        rows = np.flatnonzero(np.isin(zone_of, both))
        codes = part.values[rows]
        known = (codes != NOT_TAKEN16) & (target[rows] != NOT_TAKEN8) & (states[rows] >= 0)
        rows, codes = rows[known], codes[known]
        c0, heads, bucket = unpack(codes)
        keep = c0 < C0_VALUES
        for i, a, h, f in zip(rows[keep], c0[keep], heads[keep], bucket[keep], strict=True):
            key = (int(states[i]), cell_index(slot, int(a), int(h), int(f)), int(target[i]))
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return CaseDay(day=day, rows=tuple((*key, n) for key, n in sorted(counts.items())))


def count_days(
    cases: LiveCases,
    record: Record,
    zones: Sequence[str],
    states: npt.NDArray[np.int64],
    now: datetime,
) -> tuple[LiveCases, list[date]]:
    """``cases`` with every day of the record that is over (before today in UTC, so its 05:00
    record was taken everywhere or never will be) and not yet counted; and the days added."""
    have = {item.day for item in cases.days}
    today = now.astimezone(UTC).date()
    added: list[CaseDay] = []
    for day in sorted(record.days):
        if day in have or day >= today or not is_school_day(day):
            continue
        found = day_cases(record, day, zones, states)
        if found is not None:
            added.append(found)
    if not added:
        return cases, []
    days = tuple(sorted([*cases.days, *added], key=lambda item: item.day))
    return LiveCases(schema_version=1, days=days), [item.day for item in added]


def case_frame(days: Sequence[CaseDay]) -> pl.DataFrame:
    """Live cases as a case frame (:func:`snowlight.predict.outlook_backtest.calibration_rows`'s
    columns: a moment of each slot, ``c0``, heads-up, bucket, target, ``n``, state, night)."""
    rows: list[tuple[int, int, int, int, int, int, str, date]] = []
    for item in days:
        for s, cell, target, n in item.rows:
            slot, c0, heads, f = outlook_module.cell_parts(cell)
            rows.append(
                (_SLOT_MOMENT[slot], c0, heads, f, target, n, outlook_module.STATES[s], item.day)
            )
    return pl.DataFrame(
        rows,
        schema={
            "moment": pl.Int64, "c0": pl.Int64, "h": pl.Int64, "f": pl.Int64,
            "target": pl.Int64, "n": pl.Int64, "state": pl.String, "night": pl.Date,
        },
        orient="row",
    )  # fmt: skip


def log_loss(table: Outlook, days: Sequence[CaseDay]) -> tuple[float, int]:
    """``T``'s log loss per case on the days' cases (each 05:00 class's weight, floored at
    1e-6), and how many cases."""
    t = table.t_state()
    nation = table.t_nation()
    total = 0.0
    count = 0
    for item in days:
        for s, cell, target, n in item.rows:
            row = t[s, cell] if s >= 0 else nation[cell]
            weight = (
                float(row[target])
                if row.sum() > 0
                else float(target == outlook_module.cell_parts(cell)[1])
            )
            total -= n * math.log(max(weight, 1e-6))
            count += n
    return (total / count if count else math.nan), count


def calibration_failing(table: Outlook, days: Sequence[CaseDay]) -> tuple[int, int]:
    """GF5's rule on the days' cases: (bins checked, bins out of bounds)."""
    from snowlight.predict.outlook_backtest import calibration_rows, gf5  # noqa: PLC0415

    frame = case_frame(days)
    if frame.is_empty():
        return 0, 0
    gate = gf5(calibration_rows(frame, table), GF5_MIN_CASES)
    return int(gate.detail["bins_checked"]), int(gate.detail["bins_failing"])


# --- the swap ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TDecision:
    """``swap`` (publish ``learned``), ``keep`` (worse; ``why``), or ``unchanged``."""

    kind: Literal["swap", "keep", "unchanged"]
    why: str
    learned: LearnedOutlook | None = None


type E20Score = Callable[[Outlook, Sequence[date]], tuple[int, float]]
"""The labeled E20 rows of the days and their Brier under a ``T``."""


def judges(
    committed: Outlook,
    served_days: Sequence[CaseDay],
    held: Sequence[CaseDay],
    fit: Sequence[CaseDay],
) -> list[tuple[str, Outlook]]:
    """The tables a candidate (``committed`` plus ``fit``) is judged against on the ``held``
    days: none of them has counted a held-out day, and none is the candidate itself.

    * ``committed``: the archive's ``T`` alone, always.
    * ``served``: the served ``T`` without the held-out days (the days it counted before
      them), only when that is neither the committed ``T`` nor the candidate. Once ``T`` swaps
      nightly the served ``T`` without the held-out days IS the candidate, so a judge built
      from it alone could never reject (it compared a table with itself)."""
    found: list[tuple[str, Outlook]] = [("committed", committed)]
    held_days = {item.day for item in held}
    before = [item for item in served_days if item.day not in held_days]
    if before and [item.day for item in before] != [item.day for item in fit]:
        found.append(("served", with_live(committed, before)))
    return found


def decide(  # noqa: PLR0913, PLR0917 - the tables, the cases, the artifact and the check
    committed: Outlook,
    current: LearnedOutlook | None,
    cases: LiveCases,
    artifact_sha256: str,
    now: datetime,
    e20: E20Score | None = None,
) -> TDecision:
    """Whether to swap in ``T`` refit with the live days (see the module docstring)."""
    days = list(cases.days)
    if len(days) <= HELD_DAYS:
        return TDecision(
            "unchanged",
            f"T: {len(days)} live days counted, more than {HELD_DAYS} are needed; T is unchanged",
        )
    held, fit = days[-HELD_DAYS:], days[:-HELD_DAYS]
    served_days = list(current.days) if current is not None else []
    if {item.day for item in days} <= {item.day for item in served_days}:
        return TDecision("unchanged", "T: no live day the served T lacks; unchanged")
    candidate = with_live(committed, fit)
    baselines = judges(committed, served_days, held, fit)
    mine, cases_held = log_loss(candidate, held)
    checked, failing = calibration_failing(candidate, held)
    check: dict[str, float | int] = {
        "held_cases": cases_held,
        "candidate_log_loss": _number(mine),
        "gf5_bins_checked": checked,
        "gf5_bins_failing": failing,
    }
    theirs: dict[str, float] = {}
    for name, table in baselines:
        theirs[name] = log_loss(table, held)[0]
        check[f"{name}_log_loss"] = _number(theirs[name])
    why: str | None = None
    worse = [
        f"{theirs[name]:.5f} {name}"
        for name, _table in baselines
        if math.isfinite(theirs[name]) and mine > theirs[name] + _TIE
    ]
    if not math.isfinite(mine):
        why = "its log loss is not a number"
    elif worse:
        why = f"its log loss {mine:.5f} is worse than " + " and ".join(worse)
    elif failing:
        why = f"{failing} of {checked} calibration bins out of bounds"
    if why is None and e20 is not None:
        held_days = [item.day for item in held]
        rows, brier_mine = e20(candidate, held_days)
        check["e20_rows"] = rows
        if rows >= E20_MIN_ROWS:
            check["candidate_e20_brier"] = _number(brier_mine)
            for name, table in baselines:
                brier_theirs = e20(table, held_days)[1]
                check[f"{name}_e20_brier"] = _number(brier_theirs)
                if not math.isfinite(brier_mine) or brier_mine > brier_theirs + _TIE:
                    why = f"its E20 Brier {brier_mine:.5f} is worse than {brier_theirs:.5f} {name}"
                    break
    summary = (
        f"{cases_held:,} held-out cases from {held[0].day}: log loss {mine:.5f} candidate, "
        + ", ".join(f"{theirs[name]:.5f} {name}" for name, _table in baselines)
    )
    if why is not None:
        return TDecision("keep", f"T: kept the served T: the candidate is worse ({why}); {summary}")
    learned = LearnedOutlook(
        schema_version=1,
        artifact_sha256=artifact_sha256,
        through=days[-1].day,
        days=tuple(days),
        check=check,
        made_at=now.astimezone(UTC).replace(microsecond=0),
    )
    return TDecision(
        "swap",
        f"T: swapped in the refit with {len(days)} live days through {days[-1].day}; {summary}",
        learned,
    )


def _number(value: float) -> float:
    return round(value, 6) if math.isfinite(value) else -1.0


# --- chances from the record, for the E20 check and the report ----------------------------------


@dataclass(frozen=True, slots=True)
class Labels:
    """The live labels by (district position, day): no school (1.0) or school (0.0)."""

    y: Mapping[tuple[int, date], float]

    def after(self, district: int, day: date) -> bool:
        """Whether the district had no school on the school day before ``day``."""
        return self.y.get((district, previous_school_day(day))) == 1.0


def sample_chances(  # noqa: PLR0913, PLR0917 - the model, T, the record and the labels
    serve: OutlookServe,
    table: Outlook,
    record: Record,
    day: date,
    k: int,
    labels: Labels,
) -> tuple[
    npt.NDArray[np.int64], npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.int64]
]:
    """For sample ``k`` of ``day``: the labeled districts with the sample taken, the outlook's
    chance under ``table`` (as the pass gives it, with the slot of the sample's hour), the v3
    identity (the issued-alerts-only chance), and ``c0``."""
    entry = record.days.get(day)
    part = None if entry is None else entry.samples.get(k)
    empty = np.zeros(0)
    if part is None:
        return np.zeros(0, dtype=np.int64), empty, empty, np.zeros(0, dtype=np.int64)
    rows = np.array(
        [
            i
            for i in range(record.districts)
            if part.values[i] != NOT_TAKEN16 and (i, day) in labels.y
        ],
        dtype=np.int64,
    )
    if not rows.size:
        return rows, empty, empty, rows
    c0, heads, bucket = unpack(part.values[rows])
    after = np.array([labels.after(int(i), day) for i in rows], dtype=np.bool_)
    rates = serve.rates
    p_class = class_matrix((rates.p_rate if rates.p_rate.size else rates.p)[rows], after)
    q_class = class_matrix((rates.q_rate if rates.q_rate.size else rates.q)[rows], after)
    slot = np.full(rows.size, SAMPLES[k].slot, dtype=np.int64)
    usable = (c0 < C0_VALUES) & (bucket != outlook_module.UNKNOWN)
    dist = np.zeros((rows.size, CLASSES))
    if usable.any():
        dist[usable] = table.distribution(
            slot[usable], c0[usable], heads[usable], bucket[usable], serve.state_index[rows][usable]
        )
    settings = rates.artifact.settings
    found = chance(p_class, q_class, c0, dist, usable, mode=OutlookMode.ON,
                   floor=settings.floor, ceiling=settings.ceiling)  # fmt: skip
    identity = chance(p_class, q_class, c0, None, np.zeros(rows.size, dtype=np.bool_),
                      mode=OutlookMode.ON, floor=settings.floor,
                      ceiling=settings.ceiling)  # fmt: skip
    return rows, found.p, identity.p, c0


def e20_score(serve: OutlookServe, record: Record, labels: Labels) -> E20Score:
    """The E20 check's score: the labeled districts with no warning issued by 8 PM, their
    outlook chance at the 8 PM sample under a ``T``, and its Brier."""

    def score(table: Outlook, days: Sequence[date]) -> tuple[int, float]:
        p_all: list[float] = []
        y_all: list[float] = []
        for day in days:
            rows, p, _identity, c0 = sample_chances(serve, table, record, day, E20_SAMPLE, labels)
            keep = c0 < C0_VALUES
            p_all.extend(p[keep].tolist())
            y_all.extend(labels.y[(int(i), day)] for i in rows[keep])
        if not p_all:
            return 0, math.nan
        p_arr, y_arr = np.array(p_all), np.array(y_all)
        return len(p_all), float(((p_arr - y_arr) ** 2).mean())

    return score


def report(  # noqa: PLR0913, PLR0917 - the models, T, the record, the labels and when
    serve: OutlookServe,
    table: Outlook,
    record: Record,
    labels: Labels,
    now: datetime,
    v2_model: ServeModel | None = None,
) -> dict[str, Any]:
    """The internal nightly report (never on the site): per slot, over the labeled live days'
    samples, the outlook's chance against the issued-alerts-only one (both on the v3 rates)
    and, with ``v2_model`` (the v2 rates served), against the v2 rates' chance of the class issued
    then (S7-F vs v2 in shadow); and over the E20 rows of 8 PM the recorded chances, S7-F's
    against the published ones."""
    by_slot: dict[int, dict[str, list[float]]] = {}
    recorded: dict[str, list[float]] = {"f": [], "v2": [], "y": []}
    for day in sorted(record.days):
        for k in sorted(record.days[day].samples):
            rows, p, identity, c0 = sample_chances(serve, table, record, day, k, labels)
            keep = c0 < C0_VALUES
            slot = SAMPLES[k].slot
            mine = by_slot.setdefault(slot, {"f": [], "identity": [], "v2": [], "y": []})
            mine["f"].extend(p[keep].tolist())
            mine["identity"].extend(identity[keep].tolist())
            mine["y"].extend(labels.y[(int(i), day)] for i in rows[keep])
            if v2_model is not None:
                after = np.array([labels.after(int(i), day) for i in rows[keep]], dtype=np.bool_)
                rates = class_matrix(v2_model.p[rows[keep]], after)
                mine["v2"].extend(rates[np.arange(after.size), c0[keep]].tolist())
        entry = record.days[day]
        if entry.chance_v2 is not None and entry.chance_f is not None:
            e20 = record.days[day].samples.get(E20_SAMPLE)
            for i in range(record.districts):
                y = labels.y.get((i, day))
                v2, f = int(entry.chance_v2.values[i]), int(entry.chance_f.values[i])
                if y is None or NOT_TAKEN8 in (v2, f):
                    continue
                if (
                    e20 is None
                    or e20.values[i] == NOT_TAKEN16
                    or unpack(e20.values[i : i + 1])[0][0] >= C0_VALUES
                ):
                    continue
                recorded["f"].append(f / 100)
                recorded["v2"].append(v2 / 100)
                recorded["y"].append(y)

    names = ("f", "identity", "v2") if v2_model is not None else ("f", "identity")

    def scores(found: Mapping[str, list[float]], names: Sequence[str]) -> dict[str, Any]:
        y = np.array(found["y"], dtype=np.float64)
        out: dict[str, Any] = {
            "rows": int(y.size),
            "observed": _number(float(y.mean())) if y.size else None,
        }
        for name in names:
            p = np.array(found[name], dtype=np.float64)
            out[f"brier_{name}"] = _number(float(((p - y) ** 2).mean())) if y.size else None
            out[f"mean_{name}"] = _number(float(p.mean())) if y.size else None
            out[f"bins_{name}"] = _bins(p, y)
        return out

    return {
        "made_at": now.astimezone(UTC).replace(microsecond=0).isoformat(),
        "days": [day.isoformat() for day in sorted(record.days)],
        "labeled_days": sorted({day.isoformat() for (_i, day) in labels.y}),
        "by_slot": {str(slot): scores(found, names) for slot, found in sorted(by_slot.items())},
        "e20_recorded": scores(recorded, ("f", "v2")),
    }


def _bins(
    p: npt.NDArray[np.float64], y: npt.NDArray[np.float64], count: int = 10
) -> list[list[float | int]]:
    """Reliability bins: [rows, mean chance, observed] per tenth."""
    found: list[list[float | int]] = []
    if not p.size:
        return found
    which = np.clip((p * count).astype(np.int64), 0, count - 1)
    for b in range(count):
        mask = which == b
        if mask.any():
            found.append(
                [int(mask.sum()), _number(float(p[mask].mean())), _number(float(y[mask].mean()))]
            )
    return found


def report_changed(stored: bytes | None, made: Mapping[str, Any]) -> bool:
    """Whether the report says anything the stored one does not (its time aside): a run that
    learned nothing new writes no report, so it adds no commit to the live host."""
    if stored is None:
        return True
    try:
        before = json.loads(stored)
    except ValueError:
        return True
    if not isinstance(before, dict):
        return True
    drop = {"made_at"}
    after = json.loads(json.dumps(made, sort_keys=True))
    return {k: v for k, v in before.items() if k not in drop} != {
        k: v for k, v in after.items() if k not in drop
    }


def summary_line(found: Mapping[str, Any]) -> str:
    """The report in one log line: counts and scores only."""
    e20 = found["e20_recorded"]
    slots = found["by_slot"]
    parts = [f"{len(found['days'])} days recorded, {len(found['labeled_days'])} labeled"]
    if e20["rows"]:
        parts.append(
            f"8 PM E20 {e20['rows']:,} rows: Brier S7-F {e20['brier_f']}, "
            f"published {e20['brier_v2']}"
        )
    five = slots.get("5")
    if five and five["rows"]:
        parts.append(
            f"slot 5 {five['rows']:,} rows: Brier S7-F {five['brier_f']}, "
            f"identity {five['brier_identity']}"
        )
    return "outlook report: " + "; ".join(parts)


@dataclass(slots=True)
class Step:
    """What the outlook's learning step writes, and its lines."""

    files: dict[str, bytes] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)


def labels_of(rows: pl.DataFrame, districts: Sequence[str]) -> Labels:
    """The live labels (:meth:`snowlight.predict.learn.LearnStore.rows`) by district position."""
    position = {leaid: i for i, leaid in enumerate(districts)}
    found: dict[tuple[int, date], float] = {}
    for leaid, day, y in zip(
        rows["district"].to_list(), rows["day"].to_list(), rows["y"].to_list(), strict=True
    ):
        if leaid in position:
            found[(position[leaid], day)] = float(y)
    return Labels(found)


def keep_days(now: datetime) -> date:
    """The oldest day a record keeps on the host (about two weeks of calendar days, for the
    10 school days)."""
    return now.astimezone(UTC).date() - timedelta(days=16)


def morning_snapshots(record: Record) -> dict[str, object]:
    """The record's 05:00 classes in the shape of the passes' class snapshots
    (:func:`snowlight.predict.live_labels.record_snapshots`), so S7-L's labeling reads them as
    it reads the 21:00 ones: the v3 rates learn from the class the district woke up to (rule
    D3). A district whose zone took no 05:00 record is unknown, as an unread day is."""
    from snowlight.predict.live_labels import UNKNOWN_CLASS  # noqa: PLC0415

    found: dict[str, object] = {}
    for day, entry in sorted(record.days.items()):
        if entry.morning is None or not entry.morning.taken:
            continue
        chars = "".join(
            UNKNOWN_CLASS if int(value) == NOT_TAKEN8 else str(int(value))
            for value in entry.morning.values
        )
        found[day.isoformat()] = {
            "content": record.content,
            "classes": chars,
            "taken": dict(entry.morning.taken),
        }
    return found
