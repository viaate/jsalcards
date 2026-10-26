"""``snowlight predict candidates``: the pre-registered archive test of the tuning candidates
(tune-v3 lane; ``docs/research/candidates-preregistration.md``). Internal: it writes a report
and its numbers to ``--out`` only, and no pass, terms file or model file reads them.

Order (cumulative): the P2 control; C2a; C3; the C4 stage (the control's terms with C4's
snow levels, judged against the control's own); C1 with C2b. C2c runs beside them on the
05:00 labels. A candidate's baseline is today's model plus every earlier candidate the archive
did not veto. Every fit reads its own fold's labels only (the per-fold rule).
"""

import argparse
import dataclasses
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.predict import backtest_terms, candidates, pool, term_rows, train
from snowlight.predict.backtest import FoldRows, brier
from snowlight.predict.backtest_terms import WEATHER_OF, Base, TermFold, publish
from snowlight.predict.candidates import Bools, Climate, Units
from snowlight.predict.config import ModelSettings, PredictConfig
from snowlight.predict.geography import REGION_OF
from snowlight.predict.pool import Floats, Ints, Rows
from snowlight.predict.situations import WeatherClass
from snowlight.predict.terms import (
    LEVELS,
    TERM_ORDER,
    UNKNOWN,
    Design,
    Model,
    Shape,
    Support,
    Term,
    fit,
    logit,
    predict,
)

SUPPORT: Final = Support()
"""P2: 20 rows on 3 dates for every fitted step and column."""
NAMED_DAYS: Final = (date(2023, 2, 28), date(2023, 3, 14), date(2024, 1, 16))
"""C2's three days, reported apart."""
SENTINEL_GAIN: Final = 0.02
"""T2 (a) as pre-registered: an input shifted by one label night must not gain this much (P1's
bar). This departs from plan T2, which says an input shifted by one day must not help at all
(:data:`SENTINEL_HELPS`); every verdict is reported under both readings (:data:`READINGS`) and
the lead rules which one stands."""
SENTINEL_HELPS: Final = 1e-9
"""T2 (a) as plan T2 states it: a shifted input whose pooled gain is above this (float noise)
helps, and the sentinel fails."""
PREREGISTERED: Final = "pre-registered"
"""The sentinel bar as pre-registered (:data:`SENTINEL_GAIN`)."""
PLAN_T2: Final = "plan T2"
"""The sentinel as plan T2 states it (:data:`SENTINEL_HELPS`)."""
READINGS: Final = (PREREGISTERED, PLAN_T2)
NOT_RUN: Final = (
    "P7 parity not run (it waits for F3, which builds the live inputs)",
    "T2 later-product sentinel not run on the real data (only its unit test and calc-data's "
    "class and start check exist)",
)
"""Veto checks plan T3 names that this run does not do: every verdict is provisional on them."""
GAIN_BAR: Final = 0.02
MOVED: Final = 1e-9
"""A training row's chance moved by more than this counts as moved (P8)."""


# --- inputs per district-day --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Inputs:
    """Each row's candidate inputs (as known at 21:00 the evening before)."""

    temperature: Ints
    """C2's temperature level (:func:`candidates.temperature_level`)."""
    mixed: Bools
    snow: Bools
    """Snow forecast in the window (C2 applies only then)."""
    timing: Ints
    gate: Bools
    """The alert had begun by 21:00 (C3's gate)."""

    def subset(self, keep: npt.NDArray[np.bool_]) -> "Inputs":
        """The rows ``keep`` selects."""
        return Inputs(
            self.temperature[keep], self.mixed[keep], self.snow[keep], self.timing[keep],
            self.gate[keep],
        )  # fmt: skip

    @property
    def kind(self) -> Ints:
        """C2b's kind."""
        return candidates.kind_of(self.temperature, self.mixed)


def _f(value: object) -> float:
    if value is None:
        return math.nan
    return float(value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class InputTable:
    """The inputs of every district on the label dates: the label-night forecast extract's
    values, the alert inputs as of 21:00 and each district's zone."""

    values: Mapping[tuple[str, date], tuple[float, ...]]
    alerts: Mapping[tuple[str, date], tuple[object, ...]]
    zone_of: Mapping[str, str]
    nights: Mapping[str, tuple[date, ...]]
    """Each district's label nights in the extract, in order (the sentinel's shift)."""

    @staticmethod
    def build(values: pl.DataFrame, alerts: pl.DataFrame, table: pl.DataFrame) -> "InputTable":
        """From ``values.parquet``, ``alert-inputs.parquet`` and ``districts.parquet``."""
        columns = (
            "temp_h07", "snow_window", "qpf_e06", "qpf_e12", "qpf_e18", "snow_e06", "snow_e12",
            "snow_e18", "snow_e24",
        )  # fmt: skip
        found: dict[tuple[str, date], tuple[float, ...]] = {}
        nights: dict[str, list[date]] = {}
        for row in values.select("district", "day", "zone", *columns).iter_rows():
            found[(row[0], row[1])] = tuple(_f(v) for v in row[3:])
            nights.setdefault(row[0], []).append(row[1])
        words = candidates.MIX_WORDS
        kept: dict[tuple[str, date], tuple[object, ...]] = {}
        for row in alerts.select("district", "day", "start", "began", "end", *words).iter_rows():
            kept[(row[0], row[1])] = row[2:]
        zone_of = {
            d: z for d, z in table.select("district", "time_zone").iter_rows() if z is not None
        }
        return InputTable(
            found, kept, zone_of, {d: tuple(sorted(set(v))) for d, v in nights.items()}
        )

    def shifted(self, district: str, day: date) -> date:
        """The district's next label night after ``day`` (the last to the first; ``day`` when
        it has none)."""
        mine = self.nights.get(district, ())
        later = [d for d in mine if d > day]
        if later:
            return later[0]
        return mine[0] if mine else day

    def one(
        self, district: str, day: date, read: date | None = None
    ) -> tuple[int, bool, bool, int, bool]:
        """(temperature level, mixed, snow forecast, timing level, gate) of a district-day,
        read from the inputs of ``read`` (default ``day``; the sentinel's shift)."""
        at = day if read is None else read
        zone = self.zone_of.get(district, "America/New_York")
        nan = math.nan
        value = self.values.get((district, at), (nan,) * 9)
        t7, window, q6, q12, q18, s6, s12, s18, s24 = value
        temperature = candidates.temperature_level(t7)
        liquid = _nansum((q6, q12, q18))
        snow_sum = _nansum((s6, s12, s18))
        alert = self.alerts.get((district, at))
        start, began, end = (None, None, None) if alert is None else alert[:3]
        words = alert is not None and any(bool(w) for w in alert[3:])
        mixed = candidates.mixed_by_amounts(liquid, snow_sum) or words
        snow = not math.isnan(window) and window > 0
        shares = candidates.snow_shares(at, zone, (s6, s12, s18, s24))
        end_hours = candidates.local_hours(end, at, zone)  # type: ignore[arg-type]
        timing = candidates.timing_level(end_hours, shares)
        first = began if began is not None else start
        gate = candidates.began_by_snapshot(first, at, zone)  # type: ignore[arg-type]
        return temperature, mixed, snow, timing, gate

    def inputs(self, frame: pl.DataFrame, *, shift: bool = False) -> Inputs:
        """The inputs of every row of ``frame`` (district, day), shifted by one label night
        when ``shift`` (T2 sentinel (a))."""
        found = [
            self.one(d, day, self.shifted(d, day) if shift else None)
            for d, day in frame.select("district", "day").iter_rows()
        ]
        if not found:
            empty = np.zeros(0, dtype=np.int64)
            return Inputs(empty, empty.astype(bool), empty.astype(bool), empty, empty.astype(bool))
        t, m, s, timing, g = zip(*found, strict=True)
        return Inputs(
            np.array(t, dtype=np.int64), np.array(m, dtype=np.bool_), np.array(s, dtype=np.bool_),
            np.array(timing, dtype=np.int64), np.array(g, dtype=np.bool_),
        )  # fmt: skip


def _nansum(values: Sequence[float]) -> float:
    kept = [v for v in values if not math.isnan(v)]
    return float(sum(kept)) if kept else math.nan


def morning_inputs(frame: pl.DataFrame, morning: pl.DataFrame) -> Inputs:
    """C2c's inputs from the 5 AM reports: the observed temperature level and a mixed present
    weather, on every row with a report (snow: True, so C2c needs no snow forecast)."""
    flags = candidates.OBS_MIX
    kept = {
        (row[0], row[1]): row[2:]
        for row in morning.select("district", "day", "tmpf", *flags).iter_rows()
    }
    temperature: list[int] = []
    mixed: list[bool] = []
    for key in frame.select("district", "day").iter_rows():
        row = kept.get(key)
        temperature.append(candidates.temperature_level(None if row is None else _f(row[0])))
        mixed.append(row is not None and any(bool(v) for v in row[1:]))
    n = frame.height
    return Inputs(
        np.array(temperature, dtype=np.int64), np.array(mixed, dtype=np.bool_),
        np.ones(n, dtype=np.bool_), np.full(n, UNKNOWN, dtype=np.int64), np.zeros(n, np.bool_),
    )  # fmt: skip


# --- the rows a stage reads ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RowSet:
    """Rows a fit reads or scores, in the labels' order, with everything a stage needs."""

    frame: pl.DataFrame
    rows: Rows
    base: Base
    q: Floats
    """Today's delay chance (unrounded)."""
    levels: Mapping[Term, Ints]
    inputs: Inputs
    day: Ints
    units: Units

    @property
    def own(self) -> Ints:
        """Each row's own weather class."""
        return WEATHER_OF[self.rows.situation]

    @property
    def has_base(self) -> npt.NDArray[np.bool_]:
        """Rows with a walk-forward base."""
        return np.asarray(~np.isnan(self.base.p) & (self.base.counted >= 0), dtype=np.bool_)

    @property
    def outcome(self) -> tuple[str, ...]:
        """Each row's outcome."""
        return tuple(self.frame["outcome"].to_list())


def _days(frame: pl.DataFrame) -> Ints:
    return np.array([d.toordinal() for d in frame["day"].to_list()], dtype=np.int64)


def _units(rows: Rows, places: pool.Places) -> Units:
    return Units(places.state[rows.district], places.region[rows.district])


@dataclass(frozen=True, slots=True)
class Sources:
    """What the level terms read: the forecast codes, the snapshots, the posts, the
    neighbors (piece 3's :func:`term_rows.term_levels`)."""

    codes: pl.DataFrame
    snapshots: pl.DataFrame
    posts: pl.DataFrame
    neighbors: Mapping[str, Sequence[str]]

    def levels(self, frame: pl.DataFrame) -> dict[Term, Ints]:
        """Every term's level of the rows of ``frame``."""
        return term_rows.term_levels(frame, self.codes, self.snapshots, self.posts, self.neighbors)


@dataclass
class World:
    """The test rows and every fold's training rows, with their bases (one labels rule)."""

    test: RowSet
    training: dict[int, RowSet]
    seasons: tuple[int, ...]
    places: pool.Places
    settings: ModelSettings
    climates: Mapping[int, Climate]
    c1: dict[str, tuple[Floats, Floats, Bools]] = field(default_factory=dict)
    """C1 with C2b's base per row set (``test`` or the fold's season), computed once."""
    c1_detail: dict[str, tuple[Bools, Bools]] = field(default_factory=dict)
    """Per row set: (rows C1a serves a state or region record, rows C2b's split moves)."""
    c1_rules: dict[str, candidates.LevelRule] = field(default_factory=dict)
    """Per row set: the level rule's choice per row (the levels P8 refits without)."""

    def row_set(self, key: str) -> RowSet:
        """``test`` or a fold's training rows by its season."""
        return self.test if key == "test" else self.training[int(key)]

    def c1_source(self, key: str) -> candidates.LevelSource:
        """The rows a row of row set ``key`` counts for its level records, by its season: the
        fold labels of that season (none for a season without a fold)."""
        target = self.row_set(key)

        def source(season: int) -> tuple[Rows, Units, Ints, Ints]:
            found = self.training.get(season)
            if found is None:
                none = np.zeros(0, dtype=np.int64)
                empty = target.rows.subset(np.zeros(len(target.rows), np.bool_))
                return empty, Units(none, none), none, none
            return found.rows, found.units, found.inputs.kind, found.day

        return source

    def c1_rule(self, key: str) -> candidates.LevelRule:
        """C1 with C2b's choice on every row of row set ``key``."""
        self.c1_base(key)
        return self.c1_rules[key]

    def c1_base(self, key: str) -> tuple[Floats, Floats, Bools]:
        """(published, unrounded, moved) of C1 with C2b on a row set."""
        if key not in self.c1:
            target = self.row_set(key)
            rule = candidates.level_rule(
                target.rows, target.units, target.inputs.kind, target.base.p_raw,
                self.c1_source(key), self.settings.floor, self.settings.ceiling,
            )  # fmt: skip
            raw = rule.p
            published = np.where(np.isnan(raw), np.nan, publish(np.nan_to_num(raw), self.settings))
            self.c1[key] = (published, raw, rule.served | rule.moved)
            self.c1_detail[key] = (rule.served, rule.moved)
            self.c1_rules[key] = rule
        return self.c1[key]


def build_world(  # noqa: PLR0913, PLR0917 # pragma: no cover - the real labels' bases
    usable: pl.DataFrame,
    fold: train.FoldSet,
    places: pool.Places,
    settings: ModelSettings,
    seasons: Sequence[int],
    inputs: Callable[[pl.DataFrame], Inputs],
    sources: Sources,
    climates: Mapping[int, Climate],
) -> World:
    """Every row set of one labels rule: the test rows (``usable``) and each fold's labels."""
    rows = pool.rows_from_labels(usable, places, "no_school")
    fits: dict[int, backtest_terms.Predictor] = {}
    delay_fits: dict[int, Callable[[Rows], Floats]] = {}
    training: dict[int, RowSet] = {}

    def bases(found: Rows) -> tuple[Base, Floats]:
        # A row of a season with no fold labels of its own (and not the first) has no base.
        first = min(found.season.tolist(), default=0)
        fitted = np.isin(found.season, np.array(sorted(fold.training))) | (found.season == first)
        part = found.subset(fitted)
        none = part.subset(np.zeros(len(part), dtype=np.bool_))
        inner = backtest_terms.base_by_season(
            part, none, places, settings, training=fold.training, fits=fits
        )
        p = np.full(len(found), np.nan)
        raw = np.full(len(found), np.nan)
        counted = np.full(len(found), -1, dtype=np.int64)
        p[fitted], raw[fitted], counted[fitted] = inner.p, inner.p_raw, inner.counted
        q = backtest_terms.delay_by_season(found, places, settings, fold.training, delay_fits)
        return Base(p, raw, counted), q

    for season, frame in fold.usable.items():
        found = fold.training[season].rows
        base, q = bases(found)
        training[season] = RowSet(
            frame, found, base, q, sources.levels(frame), inputs(frame), _days(frame),
            _units(found, places),
        )  # fmt: skip
    base, q = bases(rows)
    test = RowSet(
        usable, rows, base, q, sources.levels(usable), inputs(usable), _days(usable),
        _units(rows, places),
    )  # fmt: skip
    return World(test, training, tuple(seasons), places, settings, climates)


def with_inputs(world: World, inputs: Callable[[pl.DataFrame], Inputs]) -> World:
    """The same rows and bases with other inputs (the sentinel's shift)."""
    return World(
        replace(world.test, inputs=inputs(world.test.frame)),
        {s: replace(r, inputs=inputs(r.frame)) for s, r in world.training.items()},
        world.seasons, world.places, world.settings, world.climates,
    )  # fmt: skip


def fold_without(fold: train.FoldSet, day: int) -> train.FoldSet:
    """The fold labels with every row of ``day`` (an ordinal) left out (plan P8)."""
    usable: dict[int, pl.DataFrame] = {}
    training: dict[int, FoldRows] = {}
    for season, frame in fold.usable.items():
        days, delay_days = fold.days(season)
        keep = days != day
        usable[season] = frame.filter(pl.Series(keep))
        training[season] = fold.training[season].without(keep, delay_days != day)
    return train.FoldSet(usable, training)


# --- a stage: one model of the stack ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Spec:
    """One model: today's base (or C1 with C2b's) and the terms and columns it adds."""

    name: str
    c2: bool = False
    c3: bool = False
    piece3: bool = False
    c4: bool = False
    gate: bool = False
    c1: bool = False

    @property
    def today(self) -> bool:
        """Today's model: the base alone."""
        return not (self.c2 or self.c3 or self.piece3 or self.c4 or self.c1)

    def columns(self) -> tuple[str, ...]:
        """The extra columns' names."""
        return (candidates.C2_COLUMNS if self.c2 else ()) + (
            candidates.C3_COLUMNS if self.c3 else ()
        )

    def bounds(self) -> tuple[tuple[float | None, float | None], ...]:
        """The extra columns' bounds."""
        return (candidates.C2_BOUNDS if self.c2 else ()) + (candidates.C3_BOUNDS if self.c3 else ())


TODAY: Final = Spec("today's model")


def _c4_levels(row_set: RowSet, climate: Climate, places: pool.Places) -> Ints:
    bucket = row_set.levels[Term.SNOW_ADVISORY]
    found = np.full(bucket.size, UNKNOWN, dtype=np.int64)
    states = places.states
    regions = places.regions
    for i, (district, b) in enumerate(
        zip(row_set.rows.district.tolist(), bucket.tolist(), strict=True)
    ):
        state_index = int(places.state[district])
        region_index = int(places.region[district])
        found[i] = candidates.c4_level(
            int(b),
            climate.of(
                places.districts[district],
                states[state_index] if state_index >= 0 else None,
                regions[region_index] if region_index >= 0 else None,
            ),
        )
    return found


def design(  # noqa: PLR0913 - the stage, the rows, which, the fold and how
    spec: Spec,
    world: World,
    key: str,
    keep: npt.NDArray[np.bool_],
    season: int,
    *,
    unclamped: bool = False,
    delay: bool = False,
) -> Design:
    """The fit's rows ``keep`` of row set ``key`` under ``spec`` for test season ``season``
    (``delay``: the delay fit's rows, C3's delay column, the delay chance as offset)."""
    row_set = world.row_set(key)
    own = row_set.own
    if delay:
        outcome = np.array(row_set.outcome, dtype=object)
        y = np.asarray(outcome == "delayed", dtype=np.float64)
        extra = candidates.c3_delay_columns(own, row_set.inputs.timing) if spec.c3 else None
        return Design(
            offset=logit(row_set.q[keep]), y=y[keep], weather=row_set.base.counted[keep],
            levels={t: np.full(int(keep.sum()), UNKNOWN, np.int64) for t in TERM_ORDER},
            own=own[keep], day=row_set.day[keep],
            extra=None if extra is None else extra[keep],
            extra_bounds=candidates.C3_DELAY_BOUNDS if spec.c3 else (),
        )  # fmt: skip
    if spec.c1:
        published, raw, _moved = world.c1_base(key)
    else:
        published, raw = row_set.base.p, row_set.base.p_raw
    if spec.piece3:
        levels = {t: v.copy() for t, v in row_set.levels.items()}
        if spec.c4:
            c4 = _c4_levels(row_set, world.climates[season], world.places)
            levels[Term.SNOW_ADVISORY] = c4
            levels[Term.SNOW_STORM] = c4.copy()
    else:
        levels = {t: np.full(len(row_set.rows), UNKNOWN, np.int64) for t in TERM_ORDER}
    blocks = []
    if spec.c2:
        inputs = row_set.inputs
        blocks.append(candidates.c2_columns(own, inputs.temperature, inputs.mixed, inputs.snow))
    if spec.c3:
        blocks.append(candidates.c3_columns(own, row_set.inputs.timing))
    extra = np.hstack(blocks)[keep] if blocks else None
    return Design(
        offset=logit((raw if unclamped else published)[keep]),
        y=row_set.rows.y[keep],
        weather=row_set.base.counted[keep],
        levels={t: v[keep] for t, v in levels.items()},
        own=own[keep],
        day=row_set.day[keep],
        extra=extra,
        extra_bounds=spec.bounds() if blocks else (),
        up_only=row_set.inputs.gate[keep] if spec.gate else None,
    )


def shapes_of(spec: Spec) -> dict[Term, Shape] | None:
    """C4's fixed shapes (``None``: each fit's own, as backtest v2)."""
    if not spec.c4:
        return None
    found = {t: Shape(LEVELS[t], 0, 0) for t in TERM_ORDER}
    found.update(candidates.C4_SHAPES)
    return found


@dataclass(frozen=True, slots=True)
class Walk:
    """A stage's walk-forward: its test folds, the models and, per test season, the chance
    it gives its own training rows (for P8's moved rows)."""

    folds: list[TermFold]
    models: dict[int, Model]
    training: dict[int, tuple[Ints, Floats]]
    """Season to (positions of its training rows in the fold's row set, their chance)."""
    delay: Floats | None = None
    """Every test row's delay chance q (C3's when it has it; NaN where none)."""


def walk(spec: Spec, world: World, *, with_delay: bool = False) -> Walk:
    """``spec`` fit for every test season on its fold's rows (with P2) and applied to the
    season's test rows."""
    test = world.test
    folds: list[TermFold] = []
    models: dict[int, Model] = {}
    trained: dict[int, tuple[Ints, Floats]] = {}
    q = np.full(len(test.rows), np.nan)
    for season in world.seasons:
        mask = test.has_base & (test.rows.season == season)
        if not mask.any():
            continue
        source = world.training[season]
        train_mask = source.has_base & (source.rows.season < season)
        key = str(season)
        if spec.today:
            model = Model({}, 0.0)
            p_raw = test.base.p[mask]
            p_train = source.base.p[train_mask]
            unclamped = test.base.p_raw[mask]
        else:
            model = fit(
                design(spec, world, key, train_mask, season),
                source.rows.season[train_mask],
                shapes=shapes_of(spec),
                support=SUPPORT,
            )
            p_raw = predict(model, design(spec, world, "test", mask, season))
            p_train = predict(model, design(spec, world, key, train_mask, season))
            unclamped = predict(model, design(spec, world, "test", mask, season, unclamped=True))
        models[season] = model
        trained[season] = (np.flatnonzero(train_mask), p_train)
        published = p_raw if spec.today else publish(p_raw, world.settings)
        folds.append(
            TermFold(
                season, model, np.flatnonzero(mask), test.base.p[mask], p_raw, published, unclamped
            )
        )
        if with_delay:
            q[mask] = _delay_q(spec, world, season, mask, train_mask)
    return Walk(folds, models, trained, q if with_delay else None)


def _delay_q(
    spec: Spec,
    world: World,
    season: int,
    mask: npt.NDArray[np.bool_],
    train_mask: npt.NDArray[np.bool_],
) -> Floats:
    """The test rows' delay chance: today's, or C3's delay term fit on the fold's delay rows."""
    test = world.test
    if not spec.c3:
        return test.q[mask]
    source = world.training[season]
    delay_rows = np.array([o != "no_school" for o in source.outcome], dtype=np.bool_)
    keep = train_mask & delay_rows & ~np.isnan(source.q)
    model = fit(
        design(spec, world, str(season), keep, season, delay=True),
        source.rows.season[keep],
        support=SUPPORT,
    )
    known = mask & ~np.isnan(test.q)
    found = np.full(int(mask.sum()), np.nan)
    inner = known[mask]
    found[inner] = predict(model, design(spec, world, "test", known, season, delay=True))
    return found


# --- comparing a candidate with its baseline -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Context:
    """What the checks read of every test row."""

    clusters: list[tuple[object, object]]
    day: Ints
    market: list[str]
    code: Ints
    northeast: npt.NDArray[np.bool_]
    region: list[str]
    neighbor: npt.NDArray[np.bool_]


def against(candidate: Walk, baseline: Walk) -> list[TermFold]:
    """The candidate's folds with the baseline's chance as ``p_base``."""
    found = []
    for mine, theirs in zip(candidate.folds, baseline.folds, strict=True):
        if mine.season != theirs.season or not np.array_equal(mine.rows, theirs.rows):
            raise ValueError("the candidate and its baseline score different rows")
        found.append(replace(mine, p_base=theirs.p_terms))
    return found


def moved_dates(candidate: Walk, baseline: Walk, world: World, count: int = 3) -> list[int]:
    """P8: the training dates with the most rows the candidate moves from its baseline in its
    own fold fits (a district-day any fold moves counts once), most first."""
    moved: set[tuple[int, int]] = set()
    for season, (at, p) in candidate.training.items():
        theirs = baseline.training.get(season)
        if theirs is None:
            continue
        hit = np.abs(p - theirs[1]) > MOVED
        source = world.training[season]
        rows = at[hit]
        moved.update(
            zip(source.rows.district[rows].tolist(), source.day[rows].tolist(), strict=True)
        )
    if not moved:
        return []
    numbers = np.array([d for _unit, d in sorted(moved)], dtype=np.int64)
    return backtest_terms.busiest_dates(numbers, np.ones(numbers.size, dtype=np.bool_), count)


def base_dates(world: World, count: int = 3) -> list[int]:
    """P8 for C1 with C2b, a new base: the training dates the levels its scored storm test
    rows rest on count (the busiest ``count`` per level; :func:`candidates.level_dates`). A
    new base moves the test rows through records of the fold labels, so the dates that
    matter are those records' dates, not training rows a term fit moves."""
    test = world.test
    rule = world.c1_rule("test")
    storm = WEATHER_OF[test.rows.situation] > 0
    scored = storm & test.has_base & np.isin(test.rows.season, np.array(world.seasons))
    changed = np.abs(np.nan_to_num(rule.p) - np.nan_to_num(test.base.p_raw)) > MOVED
    return candidates.level_dates(
        rule, test.rows, test.units, test.inputs.kind, world.c1_source("test"),
        scored & changed, count,
    )  # fmt: skip


@dataclass(frozen=True, slots=True)
class Verdict:
    """One candidate's verdict under one reading of T2 (a), and why."""

    name: str
    verdict: str
    harm: tuple[str, ...]
    support: tuple[str, ...]
    """What archive support would still need (empty: it has it)."""
    reading: str = PREREGISTERED
    """The reading of T2 sentinel (a) it was judged under (:data:`READINGS`)."""
    not_run: tuple[str, ...] = NOT_RUN
    """Veto checks not run: the verdict is provisional on them."""

    @property
    def label(self) -> str:
        """The verdict as reported: provisional while a veto check is not run."""
        return f"{self.verdict} (provisional)" if self.not_run else self.verdict


@dataclass(frozen=True, slots=True)
class AgainstToday:
    """A candidate against today's model (preregistration sec. 4 reports every candidate
    against its baseline and against today's model; plan T3 judges harm against today's
    model)."""

    gain: float
    gain_without_apart: float
    passed: bool
    """P1 against today's model."""
    interval: tuple[float, float, float]
    """P5: the Brier difference and its 90% interval."""
    harm: tuple[str, ...]
    """The veto reasons seen against today's model (pooled Brier, P5, P3, P6)."""


def sentinel_fails(sentinel: float | None, reading: str) -> bool:
    """T2 (a) under ``reading``: as pre-registered, the shifted inputs' pooled gain reaches 2%;
    as plan T2 states it, the shifted inputs help at all."""
    if sentinel is None:
        return False
    if reading == PREREGISTERED:
        return sentinel >= SENTINEL_GAIN
    if reading == PLAN_T2:
        return sentinel > SENTINEL_HELPS
    raise ValueError(f"unknown reading {reading!r}")


def gain_without_raises(scored: backtest_terms.Scored) -> float:
    """P9: the pooled storm gain with every raised row put back to the baseline's chance."""
    held = np.where(scored.p_new > scored.p_base, scored.p_base, scored.p_new)
    return backtest_terms.storm_gain(replace(scored, p_new=held))


def no_alert_changed(folds: Sequence[TermFold], rows: Rows) -> int:
    """P6: rows of a day with no alert whose chance the candidate moves."""
    count = 0
    for fold in folds:
        quiet = WEATHER_OF[rows.situation[fold.rows]] == 0
        count += int((fold.p_terms[quiet] != fold.p_base[quiet]).sum())
    return count


def judge_verdict(  # noqa: PLR0913, PLR0917 - the candidate's checks
    name: str,
    gates: backtest_terms.TermGates,
    checks: backtest_terms.Checks,
    scored: backtest_terms.Scored,
    quiet_moved: int,
    sentinel: float | None,
    extra_harm: Sequence[str] = (),
    *,
    reading: str = PREREGISTERED,
    today: AgainstToday | None = None,
) -> Verdict:
    """The verdict (preregistration sec. 4) under one reading of T2 sentinel (a); harm is
    judged against the baseline and, when ``today`` is given, against today's model too
    (plan T3)."""
    harm = list(checks.harm)
    if quiet_moved:
        harm.append(f"P6: {quiet_moved} no-alert rows moved")
    if sentinel_fails(sentinel, reading):
        assert sentinel is not None  # noqa: S101 - sentinel_fails is False on None
        harm.append(f"T2 sentinel (a), {reading}: shifted inputs gain {100 * sentinel:+.3f}%")
    harm += list(extra_harm)
    if today is not None:
        harm += [f"against today's model: {reason}" for reason in today.harm]
    missing: list[str] = []
    if not gates.passed:
        missing.append("P1 fails")
    if not checks.drop_one.holds:
        missing.append("P4 does not hold")
    if not checks.bootstrap.better:
        missing.append("P5 upper bound not below 0")
    dropped = checks.drop_training
    if dropped is None or any(c >= b for _d, b, c in dropped.by_date):
        missing.append("P8: not better with each date left out" if dropped else "P8 not run")
    lowered = next((s for s in checks.splits if s.name == "lowered"), None)
    if lowered is None or lowered.gain <= 0:
        missing.append("P9: no gain on lowered rows")
    if gain_without_raises(scored) < GAIN_BAR:
        missing.append("P9: under 2% with raises undone")
    if harm:
        verdict = "harm (veto)"
    elif missing:
        verdict = "no archive evidence"
    else:
        verdict = "archive support"
    return Verdict(name, verdict, tuple(harm), tuple(missing), reading)


@dataclass(frozen=True, slots=True)
class Comparison:
    """A candidate against its baseline: the gate, the checks, the verdict and its extras."""

    name: str
    baseline: str
    gates: backtest_terms.TermGates
    checks: backtest_terms.Checks
    verdict: Verdict
    """Under the pre-registered sentinel bar."""
    quiet_moved: int
    sentinel: float | None
    extras: dict[str, object]
    g2_bins: list[object]
    plan_verdict: Verdict | None = None
    """Under plan T2's sentinel ("must not help")."""
    today: AgainstToday | None = None
    """Against today's model (``None``: the baseline is today's model)."""

    def verdict_of(self, reading: str) -> Verdict:
        """The verdict under ``reading``."""
        if reading == PLAN_T2 and self.plan_verdict is not None:
            return self.plan_verdict
        return self.verdict


def compare(  # noqa: PLR0913, PLR0917 - the two walks, the world, the context and the extras
    name: str,
    candidate: Walk,
    baseline: Walk,
    baseline_name: str,
    world: World,
    context: Context,
    config: PredictConfig,
    *,
    drop_training: backtest_terms.DropTraining | None = None,
    sentinel: float | None = None,
    extra_harm: Sequence[str] = (),
    extras: dict[str, object] | None = None,
    today: Walk | None = None,
) -> Comparison:
    """Every check of ``candidate`` against ``baseline`` on the storm test rows, and, when
    ``today`` (today's model's walk) is given, P1, P5 and harm against today's model too."""
    folds = against(candidate, baseline)
    rows = world.test.rows
    gates, bins = _gates(folds, world, context, config)
    scored = backtest_terms.scored_from_folds(
        folds, rows, context.day, context.market, context.code, context.northeast
    )
    checks = backtest_terms.run_checks(
        scored, apart=backtest_terms.split_market_days(), drop_training=drop_training
    )
    quiet = no_alert_changed(folds, rows)
    versus = None if today is None else against_today(candidate, today, world, context, config)
    verdicts = [
        judge_verdict(
            name, gates, checks, scored, quiet, sentinel, extra_harm, reading=r, today=versus
        )
        for r in READINGS
    ]
    return Comparison(
        name, baseline_name, gates, checks, verdicts[0], quiet, sentinel, extras or {},
        list(bins), verdicts[1], versus,
    )  # fmt: skip


def _gates(
    folds: list[TermFold], world: World, context: Context, config: PredictConfig
) -> tuple[backtest_terms.TermGates, Sequence[object]]:
    gates, bins = backtest_terms.judge(
        folds, world.test.rows, context.clusters, context.neighbor,
        bins=config.backtest.reliability_bins, min_rows=config.backtest.reliability_min_rows,
        apart=config.backtest.apart, min_storm_rows=config.backtest.g1_min_storm_rows,
        test_seasons=config.backtest.test_seasons,
    )  # fmt: skip
    return gates, list(bins)


def against_today(
    candidate: Walk, today: Walk, world: World, context: Context, config: PredictConfig
) -> AgainstToday:
    """P1, P5 and the harm checks of ``candidate`` against today's model."""
    folds = against(candidate, today)
    gates, _bins = _gates(folds, world, context, config)
    scored = backtest_terms.scored_from_folds(
        folds, world.test.rows, context.day, context.market, context.code, context.northeast
    )
    checks = backtest_terms.run_checks(scored, apart=backtest_terms.split_market_days())
    harm = list(checks.harm)
    quiet = no_alert_changed(folds, world.test.rows)
    if quiet:
        harm.append(f"P6: {quiet} no-alert rows moved")
    boot = checks.bootstrap
    return AgainstToday(
        gates.gain, gates.gain_without_apart, gates.passed,
        (boot.difference, boot.low, boot.high), tuple(harm),
    )  # fmt: skip


def shifted_gain(candidate: Walk, baseline: Walk, world: World, context: Context) -> float:
    """T2 (a): the shifted candidate's pooled storm gain over its baseline."""
    folds = against(candidate, baseline)
    scored = backtest_terms.scored_from_folds(
        folds, world.test.rows, context.day, context.market, context.code, context.northeast
    )
    return backtest_terms.storm_gain(scored)


def per_date(
    folds: Sequence[TermFold], rows: Rows, day: Ints, dates: Sequence[date]
) -> list[tuple[str, int, float, float, float]]:
    """Each named date's storm rows: (date, rows, closed, baseline Brier, candidate Brier)."""
    found = []
    positions = np.concatenate([f.rows for f in folds])
    base = np.concatenate([f.p_base for f in folds])
    new = np.concatenate([f.p_terms for f in folds])
    storm = WEATHER_OF[rows.situation[positions]] > 0
    for when in dates:
        mine = storm & (day[positions] == when.toordinal())
        y = rows.y[positions][mine]
        found.append(
            (
                when.isoformat(), int(mine.sum()), float(y.mean()) if y.size else math.nan,
                brier(base[mine], y), brier(new[mine], y),
            )
        )  # fmt: skip
    return found


def delay_scores(
    p: Floats, q: Floats, world: World, rows_mask: npt.NDArray[np.bool_], settings: ModelSettings
) -> tuple[int, float, float]:
    """On the advisory test rows ``rows_mask`` (with a delay chance): (rows, delay Brier,
    three-way log score), the published chances p and p_delay = (1 - p) q."""
    keep = rows_mask & ~np.isnan(q) & ~np.isnan(p)
    no_school, delay = pool.publish_rates(p[keep], q[keep], settings.floor, settings.ceiling)
    outcome = np.array(world.test.outcome, dtype=object)[keep]
    y_delay = np.asarray(outcome == "delayed", dtype=np.float64)
    opened = np.clip(1.0 - no_school - delay, 1e-6, 1.0)
    chance = np.where(
        outcome == "no_school", no_school, np.where(outcome == "delayed", delay, opened)
    )
    log = float(-np.mean(np.log(np.clip(chance, 1e-6, 1.0)))) if keep.any() else math.nan
    return int(keep.sum()), brier(delay, y_delay), log


def chance_of(walk_: Walk, size: int) -> Floats:
    """Every test row's published chance under a walk (NaN where none)."""
    found = np.full(size, np.nan)
    for fold in walk_.folds:
        found[fold.rows] = fold.p_terms
    return found


# --- the owner table ----------------------------------------------------------------------------


def owner_table(
    names: Sequence[str], chances: Sequence[Floats], world: World, context: Context
) -> list[str]:
    """Mean chance before and after by class, region and 9 PM snow bucket on the storm test
    rows every model scores."""
    rows = world.test.rows
    weather = WEATHER_OF[rows.situation]
    keep = (weather > 0) & np.all([~np.isnan(c) for c in chances], axis=0)
    strata = [
        backtest_terms.forecast_stratum(int(w), int(c), False).split(" | ")[1]
        for w, c in zip(weather.tolist(), context.code.tolist(), strict=True)
    ]
    labels = {
        int(WeatherClass.ADVISORY): "advisory",
        int(WeatherClass.SNOW_WARNING): "winter storm warning",
        int(WeatherClass.BLIZZARD): "blizzard warning", int(WeatherClass.COLD): "cold",
        int(WeatherClass.ICE): "ice storm warning",
    }  # fmt: skip
    lines: list[str] = []
    changed: list[str] = []
    for title, key in (
        ("class", [labels.get(int(w), f"class {w}") for w in weather.tolist()]),
        ("region", context.region),
        ("class and 9 PM snow bucket", [
            f"{labels.get(int(w), f'class {w}')}, {b}"
            for w, b in zip(weather.tolist(), strata, strict=True)
        ]),
    ):  # fmt: skip
        lines += [
            f"### By {title}",
            "",
            "| " + title + " | rows | dates | closed | " + " | ".join(names) + " |",
            "|---|---|---|---|" + "---|" * len(names),
        ]
        groups = np.array(key, dtype=object)
        for group in sorted(set(groups[keep].tolist())):
            mine = keep & (groups == group)
            y = rows.y[mine]
            shown = [f"{float(np.mean(c[mine])):.2f}" for c in chances]
            lines.append(
                f"| {group} | {int(mine.sum())} | {np.unique(context.day[mine]).size} "
                f"| {float(y.mean()):.2f} | {' | '.join(shown)} |"
            )
            changed += [
                f"- {title} {group} ({int(mine.sum())} rows, {float(y.mean()):.2f} closed): "
                f"{name} {shown[0]} to {value}"
                for name, value in zip(names[1:], shown[1:], strict=True)
                if value != shown[0]
            ]
        lines.append("")
    lines += [
        f"### Every cell whose mean chance differs from {names[0]}'s (at two places)",
        "",
        *(changed or ["- none"]),
        "",
    ]
    return lines


# --- the report -----------------------------------------------------------------------------------


def _fold_columns(walk_: Walk, spec: Spec) -> list[str]:
    names = spec.columns()
    if not names:
        return []
    lines = [
        "| test season | penalty | " + " | ".join(names) + " |",
        "|---|---|" + "---|" * len(names),
    ]
    for season, model in sorted(walk_.models.items()):
        values = " | ".join(f"{v:+.3f}" for v in model.extra) if model.extra else ""
        lines.append(f"| {season}-{(season + 1) % 100:02d} | {model.penalty:g} | {values} |")
    return lines


def comparison_markdown(found: Comparison, spec: Spec | None, walk_: Walk | None) -> list[str]:
    """One candidate's section of the report."""
    gates = found.gates
    lines = [f"## {found.name}", "", f"Baseline: {found.baseline}.", ""]
    for reading in READINGS:
        v = found.verdict_of(reading)
        lines += [
            f"**Verdict, T2 sentinel (a) {_reading_words(reading)}: {v.label}.**",
            "Veto reasons: " + ("; ".join(v.harm) if v.harm else "none") + ".",
            "What archive support would need: "
            + ("; ".join(v.support) if v.support else "nothing") + ".",
            "",
        ]  # fmt: skip
    lines += [
        "Not run, so every verdict here is provisional: " + "; ".join(NOT_RUN) + ".",
        "",
        *_today_lines(found),
        "",
        f"P1: storm Brier {gates.brier_base:.5f} (baseline) to {gates.brier_terms:.5f}, "
        f"{100 * gates.gain:+.2f}% ({gates.storm_rows} storm rows); without 2020-21 "
        f"{100 * gates.gain_without_apart:+.2f}%; worse in {gates.worse_seasons} of "
        f"{len(gates.gated_seasons)} gated seasons; G2 "
        + ("pass" if not gates.g2_failing else "fails " + ", ".join(gates.g2_failing))
        + f"; signs {'hold' if gates.signs else 'fail'}; "
        + f"P1 {'passes' if gates.passed else 'fails'}.",
        f"P6: {found.quiet_moved} no-alert rows moved.",
        _sentinel_line(found),
        "",
        "| test season | storm rows | baseline Brier | candidate Brier |",
        "|---|---|---|---|",
    ]  # fmt: skip
    lines += [
        f"| {s}-{(s + 1) % 100:02d} | {n} | {b:.5f} | {t:.5f} |" for s, n, b, t in gates.by_season
    ]
    lines.append("")
    for key, value in found.extras.items():
        if isinstance(value, list) and value and isinstance(value[0], str):
            lines += [f"**{key}**", "", *value, ""]
        else:
            lines += [f"**{key}**: {value}", ""]
    if spec is not None and walk_ is not None and spec.columns():
        lines += ["Fitted columns by fold (0: fixed by P2 or fit to 0):", ""]
        lines += _fold_columns(walk_, spec)
        lines.append("")
    body = backtest_terms.checks_markdown(found.checks, found.name).splitlines()[2:]
    lines += [line.replace("## ", "### ") for line in body]
    return lines


def _reading_words(reading: str) -> str:
    if reading == PREREGISTERED:
        return "as pre-registered (shifted gain under 2%)"
    return "as plan T2 states it (a shifted input must not help)"


def _sentinel_line(found: Comparison) -> str:
    if found.sentinel is None:
        return "T2 sentinel (a), shifted inputs' pooled gain: not applicable."
    gain = found.gates.gain
    words = [
        f"{reading}: {'fails' if sentinel_fails(found.sentinel, reading) else 'holds'}"
        for reading in READINGS
    ]
    return (
        f"T2 sentinel (a), shifted inputs' pooled gain: {100 * found.sentinel:+.3f}% against "
        f"the candidate's own {100 * gain:+.3f}% ({'; '.join(words)}). The pre-registered 2% "
        'bar departs from plan T2\'s "an input shifted by one day must not help"; both are '
        "shown and the lead rules."
    )


def _today_lines(found: Comparison) -> list[str]:
    today = found.today
    if today is None:
        return ["Against today's model: the baseline is today's model (the numbers above)."]
    difference, low, high = today.interval
    return [
        f"Against today's model: P1 {100 * today.gain:+.2f}% (without 2020-21 "
        f"{100 * today.gain_without_apart:+.2f}%), P1 {'passes' if today.passed else 'fails'}; "
        f"P5 difference {difference:+.5f}, 90% interval {low:+.5f} to {high:+.5f}; harm: "
        + ("; ".join(today.harm) if today.harm else "none")
        + "."
    ]


def comparison_json(found: Comparison) -> dict[str, object]:
    """One candidate's numbers."""
    return {
        "name": found.name,
        "baseline": found.baseline,
        "verdict": dataclasses.asdict(found.verdict),
        "verdict_plan_t2": None
        if found.plan_verdict is None
        else dataclasses.asdict(found.plan_verdict),
        "sentinel_readings": {r: sentinel_fails(found.sentinel, r) for r in READINGS}
        if found.sentinel is not None
        else None,
        "against_today": None if found.today is None else dataclasses.asdict(found.today),
        "not_run": list(NOT_RUN),
        "gates": dataclasses.asdict(found.gates)
        | {"gain": found.gates.gain, "passed": found.gates.passed},
        "checks": dataclasses.asdict(found.checks) | {"harm": found.checks.harm},
        "quiet_moved": found.quiet_moved,
        "sentinel": found.sentinel,
        "extras": dict(found.extras),
    }


# --- the command --------------------------------------------------------------------------------


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``predict candidates``."""
    parser = actions.add_parser(
        "candidates", help="the tuning candidates' pre-registered archive test (internal)"
    )
    parser.add_argument("--work", type=Path, default=train.DEFAULT_OUT, help="labels folder")
    parser.add_argument("--folds", type=Path, default=None, help="fold labels (default work/folds)")
    parser.add_argument("--directory", type=Path, default=train.TrainPaths().directory)
    parser.add_argument("--codes", type=Path, required=True, help="forecast history code files")
    parser.add_argument("--extract", type=Path, required=True, help="label-night extract folder")
    parser.add_argument("--alerts", type=Path, required=True, help="alert-inputs.parquet")
    parser.add_argument("--morning", type=Path, required=True, help="morning-obs.parquet")
    parser.add_argument("--labels-0500", type=Path, required=True, help="05:00 labels folder")
    parser.add_argument("--folds-0500", type=Path, required=True, help="05:00 fold labels")
    parser.add_argument("--out", type=Path, required=True, help="report folder (internal)")
    parser.add_argument("--no-p8", action="store_true", help="skip P8's refits")
    parser.set_defaults(handler=run_candidates)


def _context(world: World, table: pl.DataFrame, codes: pl.DataFrame) -> Context:
    usable = world.test.frame
    code_of = {
        (d, n): int(c) for d, n, c in codes.select("district", "day", "code").iter_rows()
        if c is not None
    }  # fmt: skip
    state_of = dict(zip(table["district"], table["state"], strict=True))
    region = [REGION_OF.get(state_of.get(d) or "", "unknown") for d in usable["district"]]
    return Context(
        clusters=list(zip(usable["day"].to_list(), usable["cluster"].to_list(), strict=True)),
        day=world.test.day,
        market=[str(c) for c in usable["cluster"].to_list()],
        code=np.array(
            [code_of.get(k, -1) for k in usable.select("district", "day").iter_rows()],
            dtype=np.int64,
        ),
        northeast=np.array([r == "northeast" for r in region], dtype=np.bool_),
        region=region,
        neighbor=backtest_terms.neighbor_mask(dict(world.test.levels)),
    )


def read_fold_0500(folder: Path, seasons: Sequence[int], places: pool.Places) -> train.FoldSet:
    """Lane F2's 05:00 fold labels (``labels-<season>.parquet``)."""
    usable: dict[int, pl.DataFrame] = {}
    training: dict[int, FoldRows] = {}
    for season in seasons:
        path = folder / f"labels-{season}.parquet"
        if not path.is_file():
            continue
        frame = pool.usable_labels(pl.read_parquet(path), places)
        usable[season] = frame
        training[season] = FoldRows(
            pool.rows_from_labels(frame, places, "no_school"),
            pool.rows_from_labels(frame, places, "delay"),
        )
    return train.FoldSet(usable, training)


def run_candidates(args: argparse.Namespace) -> int:  # pragma: no cover - the real labels
    """Run ``predict candidates``."""
    from snowlight.predict.candidates_run import run  # noqa: PLC0415

    return run(args)


__all__ = [
    "TODAY",
    "Comparison",
    "Context",
    "InputTable",
    "Inputs",
    "RowSet",
    "Spec",
    "Walk",
    "World",
    "against",
    "against_today",
    "base_dates",
    "build_world",
    "compare",
    "design",
    "judge_verdict",
    "morning_inputs",
    "owner_table",
    "sentinel_fails",
    "walk",
]
