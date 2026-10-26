"""Backtest v2: the reasons' terms walk-forward against piece 1's base alone (S7 spec c.3,
piece 3; addendum 2026-10-24 g). Internal only.

Every labeled district-day of a season ``s`` gets piece 1's published chance fit on the seasons
before ``s`` only (:func:`base_by_season`): the base a pass would have published that day,
and the term fit's offset ("out of fold in training"). For each test season ``S`` the terms
are fit on the rows of the seasons before ``S`` only, each with its own walk-forward base, so
nothing of ``S`` or later reaches the fit (:func:`walk_forward`). A row of the first season has
no earlier season to fit its base on and is left out of every term fit.

Gates (spec, piece 3), computed as piece 1's backtest computes its own
(:func:`snowlight.predict.backtest.gates`): storm district-day Brier at least 2% better than
piece 1's base pooled over the test seasons, and again pooled without the season reported
apart (2020-21); not worse in more than 2 of the seasons with enough storm rows to gate
(``g1_min_storm_rows``, 300; a season with fewer is reported, not gated, and a test season
with no storm rows is named); G2 (reliability within ``max(0.05, 2 clustered SE)`` in every
bin of 300 rows or more) on the unclamped chance, the terms on piece 1's unclamped base; each
term's sign (held by the fit's bounds, checked again); the neighbors term judged only on rows
with a capture before the district posted. Reported for the owner: the advisory class's
Brier with and without the terms on the same rows, its chance by forecast snow bucket, and
what that rests on (:func:`advisory_evidence`).

A row's storm class and its terms follow the day's own weather (:mod:`snowlight.predict.
terms`, ``TERMS_OF``); its base's counted weather only decides whether a snow term may apply.
"""

import math
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
import numpy.typing as npt

from snowlight.predict.backtest import (
    Bin,
    FoldTraining,
    brier,
    clustered_se,
    reliability,
    training_of,
)
from snowlight.predict.config import ModelSettings
from snowlight.predict.pool import (
    Floats,
    Places,
    Rows,
    chain,
    delay_rules,
    effective_situations,
    level_counts,
    publish_rates,
    rules_of,
    tables_from_rows,
    tune,
)
from snowlight.predict.situations import SITUATIONS
from snowlight.predict.terms import (
    ADD_ONLY,
    ADD_ONLY_SNOW,
    LEVELS,
    PENALTIES,
    TERM_ORDER,
    UNKNOWN,
    Design,
    Model,
    Term,
    applies,
    contributions,
    fit,
    logit,
    predict,
)

WEATHER_OF: Final = np.array([int(item.weather) for item in SITUATIONS], dtype=np.int64)
BRIER_GAIN: Final = 0.02
"""Storm Brier at least this share better than piece 1's, pooled."""
WORSE_SEASONS: Final = 2
"""Seasons the terms may be worse in."""


@dataclass(frozen=True, slots=True)
class Base:
    """Piece 1's walk-forward base for every row (NaN where no earlier season fits it)."""

    p: Floats
    """Published chance of no school."""
    p_raw: Floats
    """Before rounding and the clamp."""
    counted: npt.NDArray[np.int64]
    """The weather class whose days the base counts (its situation, or the fallback's)."""


type Predictor = Callable[[Rows], tuple[Floats, Floats, npt.NDArray[np.int64]]]
"""A fold's fitted base: (published chance, unrounded chance, counted weather) of any rows."""


def _fit(  # noqa: PLR0913, PLR0917 - as backtest.fit_predict
    rows: Rows,
    delay_rows: Rows,
    places: Places,
    seasons: Sequence[int],
    settings: ModelSettings,
    exclude: tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]] | None = None,
) -> Predictor:
    keep = np.isin(rows.season, np.array(list(seasons)))
    keep_delay = np.isin(delay_rows.season, np.array(list(seasons)))
    if exclude is not None:
        keep, keep_delay = keep & ~exclude[0], keep_delay & ~exclude[1]
    train, train_delay = rows.subset(keep), delay_rows.subset(keep_delay)
    tables = tables_from_rows(train, places, sorted(seasons))
    tables_delay = tables_from_rows(train_delay, places, sorted(seasons))
    rules = rules_of(settings)
    later = delay_rules(rules)
    strengths = tune(train, places, tables, sorted(seasons), settings.m_grid, rules=rules).strengths
    strengths_delay = tune(
        train_delay, places, tables_delay, sorted(seasons), settings.m_grid, rules=later
    ).strengths
    counts = level_counts(places, *tables.total())
    counts_delay = level_counts(places, *tables_delay.total())
    total_y, total_n = tables.total()
    mapping = effective_situations(total_y.sum(axis=0), total_n.sum(axis=0), rules)

    def predict_rows(test: Rows) -> tuple[Floats, Floats, npt.NDArray[np.int64]]:
        cells = (test.district, test.situation)
        found = chain(counts, strengths, rules=rules, cells=cells)
        q = chain(counts_delay, strengths_delay, rules=later, cells=cells, effective=mapping).p
        p, _delay = publish_rates(found.p, q, settings.floor, settings.ceiling)
        unmodeled = found.situation < 0
        counted = np.where(unmodeled, -1, WEATHER_OF[np.maximum(found.situation, 0)])
        return np.where(unmodeled, np.nan, p), np.where(unmodeled, np.nan, found.p), counted

    return predict_rows


def base_by_season(  # noqa: PLR0913 - the rows, the places, the settings and the folds
    rows: Rows,
    delay_rows: Rows,
    places: Places,
    settings: ModelSettings,
    *,
    exclude: tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]] | None = None,
    training: FoldTraining | None = None,
    fits: MutableMapping[int, Predictor] | None = None,
) -> Base:
    """Every row's piece 1 chance, fit on the seasons before its own only (``exclude``: the
    rows and delay rows left out of every fit, plan P8).

    ``training``: the per-fold rule. A row of season ``s`` gets the chance fit on
    ``training``'s labels of ``s`` (built from the listings and reads before ``s`` only), so
    ``rows`` may be any labels (a fold's own training rows too); ``exclude`` is then not
    taken (leave a date out of ``training`` instead). ``fits`` keeps each season's fit for
    the next call over the same ``training``.

    Raises:
        ValueError: ``exclude`` with ``training``, or ``training`` lacks a season of ``rows``
            that has an earlier one.
    """
    if training is not None and exclude is not None:
        raise ValueError("leave a date out of the fold labels, not out of the rows")
    p = np.full(len(rows), np.nan)
    raw = np.full(len(rows), np.nan)
    counted = np.full(len(rows), -1, dtype=np.int64)
    seasons = sorted(set(rows.season.tolist()))
    kept = {} if fits is None else fits
    for season in seasons:
        mask = rows.season == season
        first = not any(s < season for s in seasons)
        if not mask.any() or (first and (training is None or season not in training)):
            continue
        predictor = kept.get(season) if training is not None else None
        if predictor is None:
            source, source_delay = training_of(season, rows, delay_rows, training)
            before = sorted(s for s in set(source.season.tolist()) if s < season)
            if not before:
                continue
            predictor = _fit(source, source_delay, places, before, settings, exclude)
            if training is not None:
                kept[season] = predictor
        p[mask], raw[mask], counted[mask] = predictor(rows.subset(mask))
    return Base(p, raw, counted)


def _fit_delay(
    rows: Rows, delay_rows: Rows, places: Places, seasons: Sequence[int], settings: ModelSettings
) -> Callable[[Rows], Floats]:
    """A fold's delay chance ``q`` (unrounded) of any rows, fit as :func:`_fit` fits it."""
    keep = np.isin(rows.season, np.array(list(seasons)))
    keep_delay = np.isin(delay_rows.season, np.array(list(seasons)))
    train, train_delay = rows.subset(keep), delay_rows.subset(keep_delay)
    tables = tables_from_rows(train, places, sorted(seasons))
    tables_delay = tables_from_rows(train_delay, places, sorted(seasons))
    later = delay_rules(rules_of(settings))
    strengths_delay = tune(
        train_delay, places, tables_delay, sorted(seasons), settings.m_grid, rules=later
    ).strengths
    counts_delay = level_counts(places, *tables_delay.total())
    total_y, total_n = tables.total()
    mapping = effective_situations(total_y.sum(axis=0), total_n.sum(axis=0), rules_of(settings))

    def predict_q(test: Rows) -> Floats:
        cells = (test.district, test.situation)
        found = chain(counts_delay, strengths_delay, rules=later, cells=cells, effective=mapping)
        return np.asarray(np.where(found.situation < 0, np.nan, found.p), dtype=np.float64)

    return predict_q


def delay_by_season(
    rows: Rows,
    places: Places,
    settings: ModelSettings,
    training: FoldTraining,
    fits: MutableMapping[int, Callable[[Rows], Floats]] | None = None,
) -> Floats:
    """Every row's piece 1 delay chance ``q`` (unrounded; NaN where no earlier season fits it),
    fit as :func:`base_by_season` fits the chance of no school under the per-fold rule: a row
    of season ``s`` gets the ``q`` fit on ``training``'s labels of ``s``. ``fits`` keeps each
    season's fit for the next call over the same ``training``."""
    q = np.full(len(rows), np.nan)
    kept = {} if fits is None else fits
    for season in sorted(set(rows.season.tolist())):
        if season not in training:
            continue
        mask = rows.season == season
        predictor = kept.get(season)
        if predictor is None:
            source, source_delay = training_of(season, rows, rows, training)
            before = sorted(s for s in set(source.season.tolist()) if s < season)
            if not before:
                continue
            predictor = _fit_delay(source, source_delay, places, before, settings)
            kept[season] = predictor
        q[mask] = predictor(rows.subset(mask))
    return q


@dataclass(frozen=True, slots=True)
class TermFold:
    """One test season: the terms fit on the seasons before it, and its rows' chances."""

    season: int
    model: Model
    rows: npt.NDArray[np.int64]
    """Positions of the test rows scored."""
    p_base: Floats
    p_terms_raw: Floats
    """The terms on the published base, before rounding and the clamp (what serving shows,
    rounded and clamped)."""
    p_terms: Floats
    p_terms_unclamped: Floats = field(default_factory=lambda: np.zeros(0))
    """The terms on piece 1's unclamped base (the chance G2 bins, as piece 1 bins its own)."""


def publish(p: Floats, settings: ModelSettings) -> Floats:
    """A chance as published: hundredths within the floor and ceiling."""
    return np.asarray(np.clip(np.round(p, 2), settings.floor, settings.ceiling), dtype=np.float64)


def design_of(  # noqa: PLR0913 - the base, the rows, their levels and which
    base: Base,
    rows: Rows,
    levels: Mapping[Term, npt.NDArray[np.int64]],
    keep: npt.NDArray[np.bool_],
    weight: Floats | None = None,
    *,
    unclamped: bool = False,
) -> Design:
    """The term fit's rows ``keep``: the base's log odds (the published chance, as serving
    starts from it; ``unclamped``: piece 1's chance before rounding and the clamp), the
    outcome, the counted weather, the day's own weather and the levels."""
    return Design(
        offset=logit((base.p_raw if unclamped else base.p)[keep]),
        y=rows.y[keep],
        weather=base.counted[keep],
        levels={term: level[keep] for term, level in levels.items()},
        weight=None if weight is None else weight[keep],
        own=WEATHER_OF[rows.situation[keep]],
    )


def cluster_weights(clusters: Sequence[object]) -> Floats:
    """Each row's weight: one over the rows of its cluster (a day and a market), so a storm
    day counts once however many districts its lists named."""
    counts: dict[object, int] = {}
    for key in clusters:
        counts[key] = counts.get(key, 0) + 1
    return np.array([1.0 / counts[key] for key in clusters], dtype=np.float64)


@dataclass(frozen=True, slots=True)
class TermTraining:
    """A test season's term-fit rows under the per-fold rule: its fold labels' rows (the
    seasons before it, built from the listings and reads before it only), each with its own
    walk-forward base (:func:`base_by_season` over the same fold labels) and its levels."""

    rows: Rows
    base: Base
    levels: Mapping[Term, npt.NDArray[np.int64]]
    weight: Floats | None = None


def term_training(  # noqa: PLR0913 - the folds, their levels, the places, the settings
    training: FoldTraining,
    levels: Mapping[int, Mapping[Term, npt.NDArray[np.int64]]],
    places: Places,
    settings: ModelSettings,
    test_seasons: Sequence[int],
    *,
    fits: MutableMapping[int, Predictor] | None = None,
    weight: Mapping[int, Floats] | None = None,
) -> dict[int, TermTraining]:
    """Each test season's :class:`TermTraining` from its fold labels (``training``) and
    their levels (``levels``, in the rows' order), every base fit on ``training`` too."""
    kept = {} if fits is None else fits
    found: dict[int, TermTraining] = {}
    for season in test_seasons:
        fold = training.get(season)
        if fold is None:
            continue
        base = base_by_season(
            fold.rows, fold.delay_rows, places, settings, training=training, fits=kept
        )
        found[season] = TermTraining(
            fold.rows, base, levels[season], None if weight is None else weight[season]
        )
    return found


def walk_forward(  # noqa: PLR0913, PLR0917 - the rows, their bases and levels, and the seasons
    rows: Rows,
    base: Base,
    levels: Mapping[Term, npt.NDArray[np.int64]],
    test_seasons: Sequence[int],
    settings: ModelSettings,
    weight: Floats | None = None,
    *,
    exclude: npt.NDArray[np.bool_] | None = None,
    training: Mapping[int, TermTraining] | None = None,
) -> list[TermFold]:
    """Every test season's terms, fit on the earlier seasons' rows only (each weighted by
    ``weight``, default 1; ``exclude``: rows left out of every fit, plan P8).

    ``training``: the per-fold rule. A test season's terms are fit on its
    :class:`TermTraining` (its fold labels, their bases and levels) instead of the earlier
    seasons of ``rows``; ``rows``, ``base`` and ``levels`` give the test rows only, and
    ``weight`` and ``exclude`` are not taken (they belong to the training).

    Raises:
        ValueError: ``weight`` or ``exclude`` with ``training``, or a test season with rows
            and no training, or training that holds a row of its test season or later.
    """
    if training is not None and (weight is not None or exclude is not None):
        raise ValueError("weight and leave out the fold labels' rows, not the test rows")
    has_base = ~np.isnan(base.p) & (base.counted >= 0)
    folds: list[TermFold] = []
    for season in test_seasons:
        test = has_base & (rows.season == season)
        if not test.any():
            continue
        if training is None:
            train = has_base & (rows.season < season)
            if exclude is not None:
                train &= ~exclude
            source = TermTraining(rows, base, levels, weight)
        else:
            if season not in training:
                raise ValueError(f"no fold labels for test season {season}")
            source = training[season]
            if len(source.rows) and int(source.rows.season.max()) >= season:
                raise ValueError(f"the fold labels of test season {season} hold a later row")
            train = (
                ~np.isnan(source.base.p)
                & (source.base.counted >= 0)
                & (source.rows.season < season)
            )
        model = fit(
            design_of(source.base, source.rows, source.levels, train, source.weight),
            source.rows.season[train],
        )
        found = predict(model, design_of(base, rows, levels, test))
        folds.append(
            TermFold(
                season=season,
                model=model,
                rows=np.flatnonzero(test),
                p_base=base.p[test],
                p_terms_raw=found,
                p_terms=publish(found, settings),
                p_terms_unclamped=predict(
                    model, design_of(base, rows, levels, test, unclamped=True)
                ),
            )
        )
    return folds


def _gain(base: float, terms: float) -> float:
    return (base - terms) / base if base and not math.isnan(base) else 0.0


@dataclass(frozen=True, slots=True)
class TermGates:
    """Piece 3's gates and what they found."""

    storm_rows: int
    brier_base: float
    brier_terms: float
    by_season: tuple[tuple[int, int, float, float], ...]
    """(season, storm rows, base Brier, terms Brier), every test season with storm rows."""
    worse_seasons: int
    """Gated seasons (:attr:`gated_seasons`) the terms are worse in."""
    g2_failing: tuple[str, ...]
    signs: bool
    neighbor_rows: int
    neighbor_brier_base: float
    neighbor_brier_terms: float
    notes: tuple[str, ...] = field(default=())
    apart: tuple[int, ...] = ()
    """The seasons reported apart (2020-21)."""
    brier_base_without_apart: float = math.nan
    brier_terms_without_apart: float = math.nan
    gated_seasons: tuple[int, ...] = ()
    """Test seasons with enough storm rows to gate."""
    no_storm_seasons: tuple[int, ...] = ()
    """Test seasons with no storm rows at all."""

    @property
    def gain(self) -> float:
        """The pooled storm Brier's improvement as a share of the base's."""
        return _gain(self.brier_base, self.brier_terms)

    @property
    def gain_without_apart(self) -> float:
        """The same, pooled without the seasons reported apart."""
        return _gain(self.brier_base_without_apart, self.brier_terms_without_apart)

    @property
    def passed(self) -> bool:
        """Every gate of piece 3."""
        return (
            self.gain >= BRIER_GAIN
            and (math.isnan(self.brier_base_without_apart) or self.gain_without_apart >= BRIER_GAIN)
            and self.worse_seasons <= WORSE_SEASONS
            and not self.g2_failing
            and self.signs
        )


def signs_hold(model: Model) -> bool:
    """Every add-only term never takes away, and a snow term takes away only below its band
    and adds only above it."""
    for term, found in model.fits.items():
        if any(step < 0 for step in (*found.up, *found.down)):
            return False
        if (term in ADD_ONLY or term in ADD_ONLY_SNOW) and (found.down or found.value(0) != 0.0):
            return False
        for level in range(found.shape.levels):
            value = found.value(level)
            if level > found.shape.high and value < 0:
                return False
            if level < found.shape.low and value > 0:
                return False
            if found.shape.low <= level <= found.shape.high and value != 0:
                return False
    return True


def judge(  # noqa: PLR0913 - the folds, the rows, their clusters and the settings
    folds: Sequence[TermFold],
    rows: Rows,
    clusters: Sequence[object],
    snapshot: npt.NDArray[np.bool_],
    *,
    bins: int,
    min_rows: int,
    apart: Sequence[int] = (),
    min_storm_rows: int = 0,
    test_seasons: Sequence[int] = (),
) -> tuple[TermGates, list[Bin]]:
    """The gates over every fold's test rows (storm rows: the day's own weather above none),
    as piece 1's (:func:`snowlight.predict.backtest.gates`): ``apart`` the seasons pooled
    apart too, ``min_storm_rows`` the storm rows a season needs to be gated; ``test_seasons``
    names the ones with no storm rows."""
    positions = np.concatenate([fold.rows for fold in folds]) if folds else np.zeros(0, np.int64)
    p_base = np.concatenate([fold.p_base for fold in folds]) if folds else np.zeros(0)
    p_terms = np.concatenate([fold.p_terms for fold in folds]) if folds else np.zeros(0)
    unclamped = np.concatenate([_unclamped(fold) for fold in folds]) if folds else np.zeros(0)
    y = rows.y[positions]
    weather = WEATHER_OF[rows.situation[positions]]
    storm = weather > 0
    season_of = rows.season[positions]
    by_season: list[tuple[int, int, float, float]] = []
    gated: list[int] = []
    worse = 0
    for fold in folds:
        mine = np.isin(positions, fold.rows) & storm
        if not mine.any():
            continue
        b, t = brier(p_base[mine], y[mine]), brier(p_terms[mine], y[mine])
        by_season.append((fold.season, int(mine.sum()), b, t))
        if int(mine.sum()) >= min_storm_rows:
            gated.append(fold.season)
            worse += int(t > b)
    with_rows = {season for season, *_rest in by_season}
    kept = storm & ~np.isin(season_of, np.array(list(apart), dtype=np.int64))
    found_bins = reliability(unclamped, y, [clusters[i] for i in positions.tolist()], bins)
    failing = tuple(
        f"[{item.low:.1f}, {item.high:.1f})"
        for item in found_bins
        if item.rows >= min_rows and not item.within()
    )
    near = snapshot[positions]
    return (
        TermGates(
            storm_rows=int(storm.sum()),
            brier_base=brier(p_base[storm], y[storm]),
            brier_terms=brier(p_terms[storm], y[storm]),
            by_season=tuple(by_season),
            worse_seasons=worse,
            g2_failing=failing,
            signs=all(signs_hold(fold.model) for fold in folds),
            neighbor_rows=int(near.sum()),
            neighbor_brier_base=brier(p_base[near], y[near]) if near.any() else math.nan,
            neighbor_brier_terms=brier(p_terms[near], y[near]) if near.any() else math.nan,
            apart=tuple(apart),
            brier_base_without_apart=brier(p_base[kept], y[kept]) if kept.any() else math.nan,
            brier_terms_without_apart=brier(p_terms[kept], y[kept]) if kept.any() else math.nan,
            gated_seasons=tuple(gated),
            no_storm_seasons=tuple(s for s in test_seasons if s not in with_rows),
        ),
        found_bins,
    )


def _unclamped(fold: TermFold) -> Floats:
    return fold.p_terms_unclamped if fold.p_terms_unclamped.size else fold.p_terms_raw


SNOW_BUCKETS: Final = ("under 0.5 in", "0.5 to 2 in", "2 to 4 in", "4 to 6 in", "6 in or more")
"""The owner's buckets as the forecast history keeps them: its snow buckets are 0.5, 2, 4, 6
and 9 inches, so 0 to 1 and 1 to 2 inches cannot be told apart (one bucket, 0.5 to 2), and
under 0.5 inch is the history's quiet bucket."""


def snow_bucket(level: int) -> int:
    """The report's bucket of a snow level (6 to 9 and 9 or more together)."""
    return min(level, 4)


def advisory_table(
    folds: Sequence[TermFold],
    rows: Rows,
    base: Base,
    snow: npt.NDArray[np.int64],
    weather_value: int = 1,
) -> list[dict[str, object]]:
    """Per snow bucket, the advisory rows' chance before (base) and after (terms): mean,
    median, closings, Brier; one row for the rows whose snow is unknown, one for all. An
    advisory row is a day of advisory weather (its own class, whatever its base counts)."""
    del base  # the rows' own weather decides
    found: list[dict[str, object]] = []
    positions = np.concatenate([fold.rows for fold in folds]) if folds else np.zeros(0, np.int64)
    p_base = np.concatenate([fold.p_base for fold in folds]) if folds else np.zeros(0)
    p_terms = np.concatenate([fold.p_terms for fold in folds]) if folds else np.zeros(0)
    mine = WEATHER_OF[rows.situation[positions]] == weather_value
    y = rows.y[positions]
    levels = snow[positions]
    groups = [
        (name, mine & (levels >= 0) & (np.minimum(levels, 4) == b))
        for b, name in enumerate(SNOW_BUCKETS)
    ]
    groups.append(("unknown (no forecast, or ice hides the snow)", mine & (levels < 0)))
    groups.append(("all advisory rows", mine))
    for name, keep in groups:
        count = int(keep.sum())
        found.append(
            {
                "bucket": name,
                "rows": count,
                "closed": float(y[keep].mean()) if count else math.nan,
                "base_mean": float(p_base[keep].mean()) if count else math.nan,
                "terms_mean": float(p_terms[keep].mean()) if count else math.nan,
                "base_median": float(np.median(p_base[keep])) if count else math.nan,
                "terms_median": float(np.median(p_terms[keep])) if count else math.nan,
                "brier_base": brier(p_base[keep], y[keep]) if count else math.nan,
                "brier_terms": brier(p_terms[keep], y[keep]) if count else math.nan,
            }
        )
    return found


@dataclass(frozen=True, slots=True)
class AdvisoryEvidence:
    """What the advisory rows' change rests on, walk-forward and in the served fit."""

    by_fold: tuple[tuple[int, int, int, int, tuple[int, ...]], ...]
    """(season, advisory test rows, rows the snow term moved, rows the ice term moved, the
    rows' known snow levels counted by level)."""
    brier_snow_moved: tuple[float, float, int]
    """(base, terms, rows) Brier of the advisory test rows only the snow term moved."""
    brier_ice_moved: tuple[float, float, int]
    """The same for the rows the ice term moved."""
    served_counts: tuple[int, ...]
    """The served fit's advisory rows by snow level (its band's counts)."""
    served_values: tuple[float, ...]
    """The served advisory snow term by level (log odds)."""
    served_ice: tuple[float, ...]
    """The served ice term by level (log odds)."""
    typical_base: float
    """The advisory rows' median base in the served fit's rows."""


def _sigmoid1(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _logit1(p: float) -> float:
    q = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(q / (1 - q))


def advisory_evidence(  # noqa: PLR0913, PLR0917 - the folds, the rows, their base and levels, the fit
    folds: Sequence[TermFold],
    rows: Rows,
    base: Base,
    levels: Mapping[Term, npt.NDArray[np.int64]],
    final: Model,
    weather_value: int = 1,
) -> AdvisoryEvidence:
    """Which term moved the advisory test rows in each fold (S3 of the piece 3 review: the
    advisory snow lever's held-out evidence), and the served fit's counts behind each step."""
    by_fold: list[tuple[int, int, int, int, tuple[int, ...]]] = []
    snow_rows: list[int] = []
    ice_rows: list[int] = []
    p_terms_of: dict[int, float] = {}
    for fold in folds:
        keep = np.zeros(len(rows), dtype=np.bool_)
        keep[fold.rows] = True
        values = contributions(fold.model, design_of(base, rows, levels, keep))
        own = WEATHER_OF[rows.situation[fold.rows]] == weather_value
        snow = values.get(Term.SNOW_ADVISORY, np.zeros(fold.rows.size)) != 0
        ice = values.get(Term.ICE, np.zeros(fold.rows.size)) != 0
        known = levels[Term.SNOW_ADVISORY][fold.rows][own]
        counts = np.bincount(known[known >= 0], minlength=LEVELS[Term.SNOW_ADVISORY])
        by_fold.append(
            (
                fold.season,
                int(own.sum()),
                int((own & snow).sum()),
                int((own & ice).sum()),
                tuple(int(c) for c in counts),
            )
        )
        snow_rows.extend(fold.rows[own & snow & ~ice].tolist())
        ice_rows.extend(fold.rows[own & ice].tolist())
        p_terms_of.update(zip(fold.rows.tolist(), fold.p_terms.tolist(), strict=True))

    def _moved(found: list[int]) -> tuple[float, float, int]:
        if not found:
            return math.nan, math.nan, 0
        at = np.array(found, dtype=np.int64)
        terms_p = np.array([p_terms_of[i] for i in found])
        return brier(base.p[at], rows.y[at]), brier(terms_p, rows.y[at]), len(found)

    fit_snow = final.fits.get(Term.SNOW_ADVISORY)
    fit_ice = final.fits.get(Term.ICE)
    has_base = ~np.isnan(base.p) & (base.counted >= 0)
    advisory = has_base & (WEATHER_OF[rows.situation] == weather_value)
    return AdvisoryEvidence(
        by_fold=tuple(by_fold),
        brier_snow_moved=_moved(snow_rows),
        brier_ice_moved=_moved(ice_rows),
        served_counts=() if fit_snow is None else fit_snow.counts,
        served_values=()
        if fit_snow is None
        else tuple(fit_snow.value(level) for level in range(fit_snow.shape.levels)),
        served_ice=()
        if fit_ice is None
        else tuple(fit_ice.value(level) for level in range(fit_ice.shape.levels)),
        typical_base=float(np.median(base.p[advisory])) if advisory.any() else math.nan,
    )


def evidence_markdown(found: AdvisoryEvidence) -> list[str]:
    """The owner's notes on the advisory rows: what moved them and what each step rests on."""
    lines = ["", "## What the advisory change rests on", ""]
    lines.append(
        "| test season | advisory rows | moved by the snow term | moved by the ice term "
        "| known snow levels 0-5 |"
    )
    lines.append("|---|---|---|---|---|")
    for season, count, snow, ice, levels in found.by_fold:
        label = f"{season}-{(season + 1) % 100:02d}"
        lines.append(f"| {label} | {count} | {snow} | {ice} | {list(levels)} |")
    sb, st, sn = found.brier_snow_moved
    ib, it, inn = found.brier_ice_moved
    lines.append("")
    lines.append(
        f"Walk-forward, {sn} advisory test rows were moved by the snow term alone (Brier "
        f"{_f(sb)} base, {_f(st)} terms) and {inn} by the ice term (Brier {_f(ib)} base, "
        f"{_f(it)} terms)."
    )
    if found.served_values and found.served_counts:
        base = found.typical_base
        lines.append("")
        lines.append(
            f"The served advisory snow term, on the advisory days' median base of "
            f"{_f(base)} (in-sample: fit on these rows, not tested on held-out rows):"
        )
        lines.extend(
            ["", "| forecast snow | training rows | log odds | chance |", "|---|---|---|---|"]
        )
        names = (*SNOW_BUCKETS[:4], "6 to 9 in", "9 in or more")
        for level, value in enumerate(found.served_values):
            rows_at = found.served_counts[level] if level < len(found.served_counts) else 0
            chance = _sigmoid1(_logit1(base) + value) if not math.isnan(base) else math.nan
            lines.append(f"| {names[level]} | {rows_at} | {value:+.2f} | {_f(chance)} |")
    if found.served_ice:
        base = found.typical_base
        ice_names = ("under 0.10 in", "0.10 to 0.25 in", "0.25 in or more")
        lines.extend(["", "The served ice term on the same base:", ""])
        lines.extend(["| forecast ice | log odds | chance (clamped at 0.99) |", "|---|---|---|"])
        for level, value in enumerate(found.served_ice):
            chance = _sigmoid1(_logit1(base) + value) if not math.isnan(base) else math.nan
            lines.append(f"| {ice_names[level]} | {value:+.2f} | {_f(min(chance, 0.99))} |")
    return lines


def term_table(model: Model) -> list[str]:
    """A fitted model's steps, for the report: each term's value at every level (log odds)."""
    lines = ["| term | band | values by level (log odds) |", "|---|---|---|"]
    for term in TERM_ORDER:
        found = model.fits.get(term)
        if found is None:
            continue
        values = ", ".join(f"{found.value(level):+.2f}" for level in range(found.shape.levels))
        lines.append(f"| {term.value} | {found.shape.low}-{found.shape.high} | {values} |")
    return lines


def neighbor_mask(levels: Mapping[Term, npt.NDArray[np.int64]]) -> npt.NDArray[np.bool_]:
    """Rows with a snapshot (a capture before the district posted): a known neighbors level."""
    return np.asarray(levels[Term.NEIGHBORS] != UNKNOWN, dtype=np.bool_)


def _f(value: object, places: int = 3) -> str:
    """``value`` to ``places`` decimals, ``-`` for NaN (no rows)."""
    if isinstance(value, float):
        return "-" if math.isnan(value) else f"{value:.{places}f}"
    return str(value)


def _signed(value: float, places: int = 5) -> str:
    """``value`` signed to ``places`` decimals, ``-`` for NaN (no rows)."""
    return "-" if math.isnan(value) else f"{value:+.{places}f}"


def _season(season: int) -> str:
    return f"{season}-{(season + 1) % 100:02d}"


def report_markdown(  # noqa: PLR0913, PLR0917 - the gates, the folds, the owner's tables and the fit
    judged: TermGates,
    folds: Sequence[TermFold],
    advisory: Sequence[Mapping[str, object]],
    final: Model,
    announced: int,
    evidence: AdvisoryEvidence | None = None,
) -> str:
    """The internal backtest v2 report."""
    lines = ["# Backtest v2: the reasons' terms against piece 1's base (internal)", ""]
    g2 = "pass" if not judged.g2_failing else "FAIL " + ", ".join(judged.g2_failing)
    apart = ", ".join(_season(s) for s in judged.apart) or "none"
    lines.append(
        f"Piece 3 gate: {'PASS' if judged.passed else 'FAIL'}: pooled storm Brier "
        f"{judged.brier_base:.5f} (base) to {judged.brier_terms:.5f} (terms), "
        f"{100 * judged.gain:+.1f}% (gate: at least {100 * BRIER_GAIN:.0f}% better); without "
        f"{apart}: {_f(judged.brier_base_without_apart)} to "
        f"{_f(judged.brier_terms_without_apart)}, {100 * judged.gain_without_apart:+.1f}%; "
        f"worse in {judged.worse_seasons} of {len(judged.gated_seasons)} gated seasons (gate: "
        f"at most {WORSE_SEASONS}); G2 {g2}; signs {'hold' if judged.signs else 'FAIL'}."
    )
    ungated = [s for s, *_rest in judged.by_season if s not in judged.gated_seasons]
    notes = []
    if ungated:
        notes.append(
            "reported, not gated (under the gated storm rows): "
            + ", ".join(_season(s) for s in ungated)
        )
    if judged.no_storm_seasons:
        notes.append("no storm rows: " + ", ".join(_season(s) for s in judged.no_storm_seasons))
    edges = [fold for fold in folds if fold.model.penalty in {PENALTIES[0], PENALTIES[-1]}]
    if edges:
        notes.append(
            "penalty at the grid's edge "
            f"({PENALTIES[0]:g} or {PENALTIES[-1]:g}): "
            + ", ".join(f"{_season(f.season)} ({f.model.penalty:g})" for f in edges)
        )
    if notes:
        lines.extend(["", "Seasons: " + "; ".join(notes) + "."])
    gated = ", ".join(_season(s) for s in judged.gated_seasons) or "none"
    worse = [
        f"{_season(s)} ({count} rows, {base_brier:.3f} to {terms_brier:.3f})"
        for s, count, base_brier, terms_brier in judged.by_season
        if s not in judged.gated_seasons and terms_brier > base_brier
    ]
    lines.extend(
        [
            "",
            f"The season gate covers {len(judged.gated_seasons)} of {len(judged.by_season)} "
            f"seasons with storm rows ({gated}); the pooled gate decides. Reported seasons the "
            "terms are worse in: " + (", ".join(worse) or "none") + ".",
        ]
    )
    lines.append("")
    lines.append(
        f"Neighbors term, judged only on rows with a capture before the district posted: "
        f"{judged.neighbor_rows} rows, Brier {_f(judged.neighbor_brier_base)} (base) to "
        f"{_f(judged.neighbor_brier_terms)} (terms)."
    )
    lines.extend(["", "## Storm rows by season", "", "| season | rows | base | terms |"])
    lines.append("|---|---|---|---|")
    for season, count, base_brier, terms_brier in judged.by_season:
        label = _season(season) + ("" if season in judged.gated_seasons else " (reported)")
        lines.append(f"| {label} | {count} | {base_brier:.5f} | {terms_brier:.5f} |")
    lines.extend(["", "## Advisory rows by forecast snow (walk-forward test seasons)", ""])
    lines.append(
        "| forecast snow | rows | closed | base mean | terms mean | base median | terms median "
        "| base Brier | terms Brier |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for row in advisory:
        lines.append(
            "| "
            + " | ".join(
                _f(row[key])
                for key in (
                    "bucket",
                    "rows",
                    "closed",
                    "base_mean",
                    "terms_mean",
                    "base_median",
                    "terms_median",
                    "brier_base",
                    "brier_terms",
                )
            )
            + " |"
        )
    if evidence is not None:
        lines.extend(evidence_markdown(evidence))
    lines.extend(["", "## Terms by test season (fit on the seasons before it)", ""])
    for fold in folds:
        lines.extend(
            [
                "",
                f"### {fold.season}-{(fold.season + 1) % 100:02d} (penalty {fold.model.penalty:g})",
                "",
            ]
        )
        lines.extend(term_table(fold.model))
    lines.extend(["", f"## The served fit (every season, penalty {final.penalty:g})", ""])
    lines.extend(term_table(final))
    lines.extend(["", f"Usual posting times: {announced} districts (3 or more posted stamps).", ""])
    return "\n".join(lines) + "\n"


# --- report-only checks of a candidate against today's model (calc-research plan T1, T4) --------

STRATUM_MIN_ROWS: Final = 30
STRATUM_MIN_DATES: Final = 2
STRATUM_TOLERANCE: Final = 0.01
"""P3: a stratum of 30 or more rows on 2 or more dates may be no worse by more than this."""
BOOTSTRAP_DRAWS: Final = 2000
BOOTSTRAP_LEVEL: Final = 0.90
SHIFT_GRID: Final = np.round(np.arange(-6.0, 6.0001, 0.01), 2)
"""The level-free check's logit shifts."""
ADVISORY_BUCKETS: Final = ("under 0.5 in", "0.5 to 2 in", "2 to 4 in", "4 to 6 in", "6 in or more")
WARNING_BUCKETS: Final = (
    "under 2 in",
    "under 2 in",
    "2 to 6 in",
    "2 to 6 in",
    "6 to 9 in",
    "9 in or more",
)
"""By the forecast history's snow code (0 quiet, 1 to 5 the snow buckets from 0.5, 2, 4, 6 and 9
inches); codes 6 to 8 are its ice codes, 9 to 12 cold, 13 unknown."""


def forecast_stratum(weather: int, code: int, northeast: bool) -> str:
    """A row's P3 stratum: its own class, its 9 PM forecast bucket and its region (the Northeast
    or the rest). Advisory buckets: under 0.5, 0.5 to 2, 2 to 4, 4 to 6 inches (and 6 or more),
    and the NDFD ice code; warning buckets: under 2, 2 to 6, 6 to 9, 9 or more inches."""
    place = "northeast" if northeast else "rest"
    if 6 <= code <= 8:  # noqa: PLR2004 - the history's ice codes
        bucket = "ice"
    elif code < 0 or code >= 13:  # noqa: PLR2004 - no forecast
        bucket = "unknown"
    elif code >= 9:  # noqa: PLR2004 - a cold code: no snow or ice outranks it
        bucket = ADVISORY_BUCKETS[0] if weather <= 1 else WARNING_BUCKETS[0]
    elif weather <= 1:
        bucket = ADVISORY_BUCKETS[min(code, 4)]
    else:
        bucket = WARNING_BUCKETS[code]
    names = {0: "none", 1: "advisory"}
    return f"{names.get(weather, f'class {weather}')} | {bucket} | {place}"


@dataclass(frozen=True, slots=True)
class Scored:
    """Test rows scored by today's model (``p_base``) and by a candidate (``p_new``)."""

    y: Floats
    p_base: Floats
    p_new: Floats
    day: npt.NDArray[np.int64]
    """Each row's date as a day number (``date.toordinal``)."""
    market: tuple[str, ...]
    """Each row's market (the cluster its storm day counts in)."""
    weather: npt.NDArray[np.int64]
    """Each row's own weather class (above 0: a storm row)."""
    stratum: tuple[str, ...] = ()
    """Each row's P3 stratum (:func:`forecast_stratum`; empty: no strata)."""

    @property
    def storm(self) -> npt.NDArray[np.bool_]:
        """The storm rows."""
        return np.asarray(self.weather > 0, dtype=np.bool_)

    def subset(self, keep: npt.NDArray[np.bool_]) -> "Scored":
        """The rows ``keep`` names."""
        at = np.flatnonzero(keep).tolist()
        return Scored(
            self.y[keep], self.p_base[keep], self.p_new[keep], self.day[keep],
            tuple(self.market[i] for i in at), self.weather[keep],
            tuple(self.stratum[i] for i in at) if self.stratum else (),
        )  # fmt: skip


@dataclass(frozen=True, slots=True)
class StratumCheck:
    """P3: one stratum's rows, dates and Briers."""

    stratum: str
    rows: int
    dates: int
    brier_base: float
    brier_new: float

    @property
    def checked(self) -> bool:
        """Whether it holds enough rows and dates to be checked."""
        return self.rows >= STRATUM_MIN_ROWS and self.dates >= STRATUM_MIN_DATES

    @property
    def worse(self) -> bool:
        """Checked, and worse than today's model by more than the tolerance."""
        return self.checked and self.brier_new - self.brier_base > STRATUM_TOLERANCE


def strata_check(scored: Scored) -> list[StratumCheck]:
    """P3 over every stratum of the scored rows (a stratum with fewer rows or dates is
    reported, not checked)."""
    found: list[StratumCheck] = []
    labels = np.array(scored.stratum, dtype=object)
    for name in sorted(set(scored.stratum)):
        keep = labels == name
        found.append(
            StratumCheck(
                str(name),
                int(keep.sum()),
                int(np.unique(scored.day[keep]).size),
                brier(scored.p_base[keep], scored.y[keep]),
                brier(scored.p_new[keep], scored.y[keep]),
            )
        )
    return found


def storm_gain(scored: Scored) -> float:
    """The candidate's pooled storm Brier gain over today's model, as a share of today's."""
    storm = scored.storm
    return _gain(
        brier(scored.p_base[storm], scored.y[storm]), brier(scored.p_new[storm], scored.y[storm])
    )


@dataclass(frozen=True, slots=True)
class DropOneDate:
    """P4: the pooled storm gain, and again with each test date left out."""

    gain: float
    by_date: tuple[tuple[int, int, float], ...]
    """(day number, its storm rows, the pooled gain without it)."""

    @property
    def lowest(self) -> float:
        """The lowest gain with one date left out (the pooled gain when there is one date)."""
        return min((gain for _d, _n, gain in self.by_date), default=self.gain)

    @property
    def holds(self) -> bool:
        """The gain stays above 0 with any one date left out."""
        return self.gain > 0 and self.lowest > 0


def drop_one_date(scored: Scored) -> DropOneDate:
    """P4 over the storm rows."""
    storm = scored.subset(scored.storm)
    found: list[tuple[int, int, float]] = []
    for day in np.unique(storm.day).tolist():
        mine = storm.day == day
        found.append((int(day), int(mine.sum()), storm_gain(storm.subset(~mine))))
    return DropOneDate(storm_gain(storm), tuple(found))


@dataclass(frozen=True, slots=True)
class Interval:
    """P5: the storm Brier difference (candidate less today's model) and its date-bootstrap
    interval."""

    difference: float
    low: float
    high: float
    dates: int
    draws: int

    @property
    def worse(self) -> bool:
        """The whole interval lies on the worse side."""
        return self.low > 0

    @property
    def better(self) -> bool:
        """The whole interval lies on the better side (upper bound below 0)."""
        return self.high < 0


def date_bootstrap(
    scored: Scored, draws: int = BOOTSTRAP_DRAWS, seed: int = 7, level: float = BOOTSTRAP_LEVEL
) -> Interval:
    """P5: resample the storm test dates (not date x market clusters: a date's weather is
    shared by its markets) with replacement, ``draws`` times; the ``level`` interval of the
    pooled storm Brier difference."""
    storm = scored.subset(scored.storm)
    days, inverse = np.unique(storm.day, return_inverse=True)
    if not days.size:
        return Interval(math.nan, math.nan, math.nan, 0, draws)
    errors_base = np.bincount(inverse, weights=(storm.p_base - storm.y) ** 2, minlength=days.size)
    errors_new = np.bincount(inverse, weights=(storm.p_new - storm.y) ** 2, minlength=days.size)
    counts = np.bincount(inverse, minlength=days.size).astype(np.float64)
    random = np.random.default_rng(seed)
    picks = random.integers(0, days.size, size=(draws, days.size))
    rows = counts[picks].sum(axis=1)
    diffs = (errors_new[picks].sum(axis=1) - errors_base[picks].sum(axis=1)) / rows
    tail = (1 - level) / 2
    difference = float((errors_new.sum() - errors_base.sum()) / counts.sum())
    low, high = np.quantile(diffs, [tail, 1 - tail])
    return Interval(difference, float(low), float(high), int(days.size), draws)


@dataclass(frozen=True, slots=True)
class Split:
    """P9 (T4): the storm rows a candidate raises, lowers and leaves, and their squared
    errors before and after (a positive ``gain`` is fewer errors)."""

    name: str
    rows: int
    closed: float
    sse_base: float
    sse_new: float

    @property
    def gain(self) -> float:
        """Squared error taken away."""
        return self.sse_base - self.sse_new


def raised_lowered(scored: Scored) -> list[Split]:
    """P9 over the storm rows: a gain from raised chances on alert days is no evidence until
    live labels (the captured storms reward any raise)."""
    storm = scored.subset(scored.storm)
    found: list[Split] = []
    for name, keep in (
        ("raised", storm.p_new > storm.p_base),
        ("lowered", storm.p_new < storm.p_base),
        ("unchanged", storm.p_new == storm.p_base),
    ):
        y = storm.y[keep]
        found.append(
            Split(
                name,
                int(keep.sum()),
                float(y.mean()) if y.size else math.nan,
                float(((storm.p_base[keep] - y) ** 2).sum()),
                float(((storm.p_new[keep] - y) ** 2).sum()),
            )
        )
    return found


def _sigmoid(x: Floats) -> Floats:
    return np.asarray(1.0 / (1.0 + np.exp(-x)), dtype=np.float64)


def best_shift(p: Floats, y: Floats) -> tuple[float, float]:
    """The single logit shift (on :data:`SHIFT_GRID`) that gives ``p`` its lowest Brier on
    ``y``, and that Brier."""
    if not p.size:
        return 0.0, math.nan
    base = logit(np.clip(p, 1e-6, 1 - 1e-6))
    scores = [float(np.mean((_sigmoid(base + shift) - y) ** 2)) for shift in SHIFT_GRID]
    best = int(np.argmin(scores))
    return float(SHIFT_GRID[best]), scores[best]


@dataclass(frozen=True, slots=True)
class LevelFree:
    """The level-free check of one class: each model's Brier after its own best shift."""

    weather: int
    rows: int
    shift_base: float
    brier_base: float
    shift_new: float
    brier_new: float


def level_free(scored: Scored) -> list[LevelFree]:
    """T4's diagnostic: per storm class, today's model and the candidate each get their own
    best single logit shift on the test rows, which takes away the national class level (not
    state by state capture differences, so it says nothing of a level rule)."""
    found: list[LevelFree] = []
    for weather in sorted(set(scored.weather[scored.storm].tolist())):
        keep = scored.weather == weather
        y = scored.y[keep]
        shift_base, brier_base = best_shift(scored.p_base[keep], y)
        shift_new, brier_new = best_shift(scored.p_new[keep], y)
        found.append(
            LevelFree(int(weather), int(keep.sum()), shift_base, brier_base, shift_new, brier_new)
        )
    return found


@dataclass(frozen=True, slots=True)
class Ranking:
    """Within-day ranking: over market-days with both outcomes, the share of (closed, not
    closed) pairs each model ranks the right way (a tie counts half)."""

    market_days: int
    pairs: int
    share_base: float
    share_new: float
    apart_market_days: int = 0
    apart_pairs: int = 0
    apart_share_base: float = math.nan
    apart_share_new: float = math.nan
    """The market-days reported apart (chosen by outcome, so in sample)."""
    all_market_days: int = 0
    all_pairs: int = 0
    all_share_base: float = math.nan
    all_share_new: float = math.nan
    """Every market-day with both outcomes, those reported apart too (the pre-registered
    figure, plan T4)."""


def _pair_share(p: Floats, y: Floats) -> tuple[int, float]:
    closed, open_ = p[y == 1], p[y == 0]
    pairs = int(closed.size * open_.size)
    if not pairs:
        return 0, 0.0
    above = (closed[:, None] > open_[None, :]).sum() + 0.5 * (
        closed[:, None] == open_[None, :]
    ).sum()
    return pairs, float(above)


def within_day_ranking(scored: Scored, apart: frozenset[tuple[int, str]] = frozenset()) -> Ranking:
    """The pre-registered ranking over every market-day with both outcomes (``all_*``), and
    apart from it ``apart`` (day number, market) alone (``apart_*``) and every market-day but
    those (the pooled share)."""
    keys = list(zip(scored.day.tolist(), scored.market, strict=True))
    groups: dict[tuple[int, str], list[int]] = {}
    for position, key in enumerate(keys):
        groups.setdefault(key, []).append(position)
    totals = {"pooled": [0, 0, 0.0, 0.0], "apart": [0, 0, 0.0, 0.0]}
    for key, members in groups.items():
        at = np.array(members, dtype=np.int64)
        y = scored.y[at]
        if not (y == 1).any() or not (y == 0).any():
            continue
        pairs, right_base = _pair_share(scored.p_base[at], y)
        _pairs, right_new = _pair_share(scored.p_new[at], y)
        bucket = totals["apart" if key in apart else "pooled"]
        bucket[0] += 1
        bucket[1] += pairs
        bucket[2] += right_base
        bucket[3] += right_new
    pooled, aside = totals["pooled"], totals["apart"]
    every = [a + b for a, b in zip(pooled, aside, strict=True)]

    def share(found: list[float], index: int) -> float:
        return found[index] / found[1] if found[1] else math.nan

    return Ranking(
        int(pooled[0]), int(pooled[1]), share(pooled, 2), share(pooled, 3),
        int(aside[0]), int(aside[1]), share(aside, 2), share(aside, 3),
        int(every[0]), int(every[1]), share(every, 2), share(every, 3),
    )  # fmt: skip


def busiest_dates(
    day: npt.NDArray[np.int64], used: npt.NDArray[np.bool_], count: int = 3
) -> list[int]:
    """P8: the ``count`` training dates with the most rows ``used`` marks (rows in the steps or
    levels a candidate uses), most first (ties to the earlier date)."""
    days, rows = np.unique(day[used], return_counts=True)
    order = sorted(
        zip(days.tolist(), rows.tolist(), strict=True), key=lambda item: (-item[1], item[0])
    )
    return [int(d) for d, _n in order[:count]]


def fold_moved_dates(
    folds: Sequence[TermFold],
    training: Mapping[int, TermTraining],
    days: Mapping[int, npt.NDArray[np.int64]],
    count: int = 3,
) -> list[int]:
    """P8 under the per-fold rule: the ``count`` training dates with the most rows the
    candidate's own fits move, most first (ties to the earlier date). A fold's fit moves a row
    of its training (``training``, its fold labels' rows with their own bases; ``days`` the
    day numbers of those rows) where a term's contribution is not 0; a (district, day) any
    fold moves counts once."""
    moved: set[tuple[int, int]] = set()
    for fold in folds:
        source = training[fold.season]
        keep = (
            ~np.isnan(source.base.p)
            & (source.base.counted >= 0)
            & (source.rows.season < fold.season)
        )
        hit = np.zeros(int(keep.sum()), dtype=np.bool_)
        for value in contributions(
            fold.model, design_of(source.base, source.rows, source.levels, keep)
        ).values():
            hit |= value != 0
        at = np.flatnonzero(keep)[hit]
        day = days[fold.season]
        moved.update(zip(source.rows.district[at].tolist(), day[at].tolist(), strict=True))
    if not moved:
        return []
    numbers = np.array([d for _unit, d in sorted(moved)], dtype=np.int64)
    return busiest_dates(numbers, np.ones(numbers.size, dtype=np.bool_), count)


@dataclass(frozen=True, slots=True)
class DropTraining:
    """P8: the pooled storm Brier of today's model and of the candidate with each training
    date left out of every fit."""

    brier: tuple[float, float]
    """(today's model, candidate) with every training date."""
    by_date: tuple[tuple[int, float, float], ...]
    """(day number, today's model, candidate) refit without it."""


def drop_training_dates(
    score: Callable[[npt.NDArray[np.bool_] | None], tuple[float, float]],
    day: npt.NDArray[np.int64],
    dates: Sequence[int],
) -> DropTraining:
    """P8: ``score(exclude)`` refits today's model and the candidate leaving out the rows
    ``exclude`` marks from every fit and returns both pooled storm Briers; each of ``dates``
    is left out in turn."""
    found = []
    for number in dates:
        base, new = score(np.asarray(day == number, dtype=np.bool_))
        found.append((int(number), base, new))
    return DropTraining(score(None), tuple(found))


def storm_briers(scored: Scored) -> tuple[float, float]:
    """Today's model's and the candidate's pooled storm Brier."""
    storm = scored.storm
    y = scored.y[storm]
    return brier(scored.p_base[storm], y), brier(scored.p_new[storm], y)


@dataclass(frozen=True, slots=True)
class Checks:
    """Every report-only check of one candidate against today's model."""

    strata: tuple[StratumCheck, ...]
    drop_one: DropOneDate
    bootstrap: Interval
    splits: tuple[Split, ...]
    level_free: tuple[LevelFree, ...]
    ranking: Ranking
    drop_training: DropTraining | None = None

    @property
    def harm(self) -> list[str]:
        """The veto reasons this report sees (plan T3: pooled storm Brier 2% or more worse,
        the bootstrap interval wholly worse, a stratum worse by more than 0.01); P6, P7 and
        the T2 sentinels are checked elsewhere."""
        found: list[str] = []
        if self.drop_one.gain <= -BRIER_GAIN:
            found.append(f"pooled storm Brier {100 * -self.drop_one.gain:.1f}% worse")
        if self.bootstrap.worse:
            found.append("date-bootstrap interval wholly worse")
        found += [f"stratum {s.stratum} worse" for s in self.strata if s.worse]
        return found


def run_checks(
    scored: Scored,
    *,
    apart: frozenset[tuple[int, str]] = frozenset(),
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = 7,
    drop_training: DropTraining | None = None,
) -> Checks:
    """P3, P4, P5, P9 (raised vs lowered), the level-free check and the within-day ranking."""
    return Checks(
        strata=tuple(strata_check(scored)) if scored.stratum else (),
        drop_one=drop_one_date(scored),
        bootstrap=date_bootstrap(scored, draws, seed),
        splits=tuple(raised_lowered(scored)),
        level_free=tuple(level_free(scored)),
        ranking=within_day_ranking(scored, apart),
        drop_training=drop_training,
    )


SPLIT_MARKET_DAYS: Final = (
    ("2023-02-28", "New York, NY - CT - NJ - PA DMA"),
    ("2023-03-14", "New York, NY - CT - NJ - PA DMA"),
    ("2023-03-14", "Hartford & New Haven, CT DMA"),
    ("2025-02-21", "Colorado Springs - Pueblo, CO DMA"),
)
"""The split market-days (10-90% closed) the ranking reports apart: chosen by outcome, and
where height was found, so in sample (plan T4)."""


def split_market_days() -> frozenset[tuple[int, str]]:
    """:data:`SPLIT_MARKET_DAYS` as (day number, market)."""
    from datetime import date as day_type  # noqa: PLC0415

    return frozenset((day_type.fromisoformat(d).toordinal(), m) for d, m in SPLIT_MARKET_DAYS)


def scored_from_folds(  # noqa: PLR0913, PLR0917 - the folds and each row's day, market, code, region
    folds: Sequence[TermFold],
    rows: Rows,
    day: npt.NDArray[np.int64],
    market: Sequence[str],
    code: npt.NDArray[np.int64],
    northeast: npt.NDArray[np.bool_],
) -> Scored:
    """The folds' test rows scored by the base (today's model) and the terms (the candidate),
    with each row's day number, market and P3 stratum (``code``: the 9 PM forecast code, -1
    unknown)."""
    positions = np.concatenate([fold.rows for fold in folds]) if folds else np.zeros(0, np.int64)
    weather = WEATHER_OF[rows.situation[positions]]
    return Scored(
        y=rows.y[positions],
        p_base=np.concatenate([fold.p_base for fold in folds]) if folds else np.zeros(0),
        p_new=np.concatenate([fold.p_terms for fold in folds]) if folds else np.zeros(0),
        day=day[positions],
        market=tuple(market[i] for i in positions.tolist()),
        weather=weather,
        stratum=tuple(
            forecast_stratum(int(w), int(code[i]), bool(northeast[i]))
            for w, i in zip(weather.tolist(), positions.tolist(), strict=True)
        ),
    )


def _day(number: int) -> str:
    from datetime import date as day_type  # noqa: PLC0415

    return day_type.fromordinal(number).isoformat()


def checks_markdown(found: Checks, title: str) -> str:
    """The checks as an internal report (report only: no gate reads it)."""
    lines = [f"# {title} (internal, report only)", ""]
    harm = found.harm
    lines.append("Veto reasons seen here: " + ("; ".join(harm) if harm else "none") + ".")
    drop = found.drop_one
    lines += [
        "",
        "## P4: one test date left out",
        "",
        f"Pooled storm gain {100 * drop.gain:+.2f}%; lowest with one date left out "
        f"{100 * drop.lowest:+.2f}% ({'holds' if drop.holds else 'does not hold'}).",
        "",
        "| date left out | its storm rows | pooled gain without it |",
        "|---|---|---|",
    ]
    lines += [f"| {_day(d)} | {n} | {100 * g:+.2f}% |" for d, n, g in drop.by_date]
    boot = found.bootstrap
    lines += [
        "",
        "## P5: storm test dates resampled",
        "",
        f"Storm Brier difference (candidate less today's model) {_f(boot.difference)}; "
        f"{100 * BOOTSTRAP_LEVEL:.0f}% interval {_f(boot.low)} to {_f(boot.high)} over "
        f"{boot.dates} dates, {boot.draws} draws.",
        "",
        "## P9: raised vs lowered (storm rows)",
        "",
        "| rows | count | closed | squared error before | after | taken away |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {s.name} | {s.rows} | {_f(s.closed)} | {s.sse_base:.2f} | {s.sse_new:.2f} "
        f"| {s.gain:+.2f} |"
        for s in found.splits
    ]
    lines += [
        "",
        "A gain from raised chances on alert days counts as no evidence until live labels.",
        "",
    ]
    if found.strata:
        lines += [
            "## P3: strata (class, 9 PM forecast bucket, region)",
            "",
            "| stratum | rows | dates | today | candidate | checked | worse by over 0.01 |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {s.stratum} | {s.rows} | {s.dates} | {_f(s.brier_base)} | {_f(s.brier_new)} "
            f"| {'yes' if s.checked else 'no'} | {'YES' if s.worse else 'no'} |"
            for s in found.strata
        ]
        lines.append("")
    lines += [
        "## Level-free check (each model's own best logit shift per class)",
        "",
        "| class | rows | today's shift | today's Brier | candidate's shift | candidate's Brier |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {item.weather} | {item.rows} | {item.shift_base:+.2f} | {_f(item.brier_base)} "
        f"| {item.shift_new:+.2f} | {_f(item.brier_new)} |"
        for item in found.level_free
    ]
    rank = found.ranking
    lines += [
        "",
        "## Within-day ranking (closed vs not closed pairs ranked the right way)",
        "",
        f"Every market-day with both outcomes (pre-registered): {rank.all_market_days} "
        f"market-days, {rank.all_pairs} pairs: today's model {_f(rank.all_share_base)}, the "
        f"candidate {_f(rank.all_share_new)}.",
        f"Every market-day with both outcomes but those reported apart: {rank.market_days} "
        f"market-days, {rank.pairs} pairs: today's model {_f(rank.share_base)}, the candidate "
        f"{_f(rank.share_new)}.",
        f"The split market-days alone (chosen by outcome, in sample): {rank.apart_market_days} "
        "market-days, "
        f"{rank.apart_pairs} pairs: today's model {_f(rank.apart_share_base)}, the candidate "
        f"{_f(rank.apart_share_new)}.",
    ]
    if found.drop_training is not None:
        base, new = found.drop_training.brier
        lines += [
            "",
            "## P8: one training date left out of every fit",
            "",
            f"Pooled storm Brier with every training date: today's model {_f(base, 5)}, the "
            f"candidate {_f(new, 5)}, candidate less today's model {_signed(new - base)}. Each "
            "refit scores the rows that keep a base without the date, so its own two Briers "
            "are compared.",
            "",
            "| training date left out | today's model | candidate | candidate less today's model |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {_day(d)} | {_f(b, 5)} | {_f(c, 5)} | {_signed(c - b)} |"
            for d, b, c in found.drop_training.by_date
        ]
    return "\n".join(lines) + "\n"


__all__ = [
    "AdvisoryEvidence",
    "Base",
    "Checks",
    "Scored",
    "TermFold",
    "TermGates",
    "advisory_evidence",
    "advisory_table",
    "applies",
    "base_by_season",
    "checks_markdown",
    "clustered_se",
    "design_of",
    "fit",
    "judge",
    "neighbor_mask",
    "publish",
    "report_markdown",
    "run_checks",
    "scored_from_folds",
    "signs_hold",
    "term_table",
    "walk_forward",
]
