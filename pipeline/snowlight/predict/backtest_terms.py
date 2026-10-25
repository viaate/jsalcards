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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
import numpy.typing as npt

from snowlight.predict.backtest import Bin, brier, clustered_se, reliability
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


def _fold(  # noqa: PLR0913, PLR0917 - as backtest.fit_predict
    rows: Rows,
    delay_rows: Rows,
    test: Rows,
    places: Places,
    seasons: Sequence[int],
    settings: ModelSettings,
) -> tuple[Floats, Floats, npt.NDArray[np.int64]]:
    keep = np.isin(rows.season, np.array(list(seasons)))
    keep_delay = np.isin(delay_rows.season, np.array(list(seasons)))
    train, train_delay = rows.subset(keep), delay_rows.subset(keep_delay)
    tables = tables_from_rows(train, places, sorted(seasons))
    tables_delay = tables_from_rows(train_delay, places, sorted(seasons))
    rules = rules_of(settings)
    later = delay_rules(rules)
    strengths = tune(train, places, tables, sorted(seasons), settings.m_grid, rules=rules).strengths
    strengths_delay = tune(
        train_delay, places, tables_delay, sorted(seasons), settings.m_grid, rules=later
    ).strengths
    cells = (test.district, test.situation)
    found = chain(level_counts(places, *tables.total()), strengths, rules=rules, cells=cells)
    total_y, total_n = tables.total()
    mapping = effective_situations(total_y.sum(axis=0), total_n.sum(axis=0), rules)
    q = chain(
        level_counts(places, *tables_delay.total()),
        strengths_delay,
        rules=later,
        cells=cells,
        effective=mapping,
    ).p
    p, _delay = publish_rates(found.p, q, settings.floor, settings.ceiling)
    unmodeled = found.situation < 0
    counted = np.where(unmodeled, -1, WEATHER_OF[np.maximum(found.situation, 0)])
    return np.where(unmodeled, np.nan, p), np.where(unmodeled, np.nan, found.p), counted


def base_by_season(rows: Rows, delay_rows: Rows, places: Places, settings: ModelSettings) -> Base:
    """Every row's piece 1 chance, fit on the seasons before its own only."""
    p = np.full(len(rows), np.nan)
    raw = np.full(len(rows), np.nan)
    counted = np.full(len(rows), -1, dtype=np.int64)
    seasons = sorted(set(rows.season.tolist()))
    for season in seasons:
        before = [s for s in seasons if s < season]
        mask = rows.season == season
        if not before or not mask.any():
            continue
        found, found_raw, found_counted = _fold(
            rows, delay_rows, rows.subset(mask), places, before, settings
        )
        p[mask], raw[mask], counted[mask] = found, found_raw, found_counted
    return Base(p, raw, counted)


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


def walk_forward(  # noqa: PLR0913, PLR0917 - the rows, their bases and levels, and the seasons
    rows: Rows,
    base: Base,
    levels: Mapping[Term, npt.NDArray[np.int64]],
    test_seasons: Sequence[int],
    settings: ModelSettings,
    weight: Floats | None = None,
) -> list[TermFold]:
    """Every test season's terms, fit on the earlier seasons' rows only (each weighted by
    ``weight``, default 1)."""
    has_base = ~np.isnan(base.p) & (base.counted >= 0)
    folds: list[TermFold] = []
    for season in test_seasons:
        train = has_base & (rows.season < season)
        test = has_base & (rows.season == season)
        if not test.any():
            continue
        model = fit(design_of(base, rows, levels, train, weight), rows.season[train])
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


def _f(value: object) -> str:
    if isinstance(value, float):
        return "-" if math.isnan(value) else f"{value:.3f}"
    return str(value)


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


__all__ = [
    "AdvisoryEvidence",
    "Base",
    "TermFold",
    "TermGates",
    "advisory_evidence",
    "advisory_table",
    "applies",
    "base_by_season",
    "clustered_se",
    "design_of",
    "fit",
    "judge",
    "neighbor_mask",
    "publish",
    "report_markdown",
    "signs_hold",
    "term_table",
    "walk_forward",
]
