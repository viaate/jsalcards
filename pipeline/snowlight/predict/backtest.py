"""The walk-forward backtest (spec c.3): the gate for every piece. Internal only.

For each test season ``S``, the strengths and the counts are fit on the seasons before
``S`` only, and every labeled district-day of ``S`` is predicted as the model would
have published it (the same chain, rounding and clamp). Scored: Brier (all, storm
district-days, by class, region and season, and per storm day), log loss, reliability
in bins of the unrounded chance with standard errors clustered by storm day, ECE, the
share of closings given 50% or more ("caught"), the precision at 50%, and the same
for delays. Baselines: B0 the national rate per class, B1 the state rate per class.

Gates (piece 1):

* G1 (amended by the lead, spec addendum 2026-10-20 b): storm district-day Brier at most
  B0's pooled over the test seasons, and in every test season with at least
  ``g1_min_storm_rows`` (300) storm rows no worse than B0's by more than ``g1_tolerance``
  (0.005). Seasons with fewer storm rows are reported, not gated. The season reported apart
  (2020-21) is gated like any other when it has the rows.
* G2: every reliability bin of 300 or more district-days within
  ``max(0.05, 2 clustered SE)`` of its mean chance.
* G3: closings caught at 50%+ at least B0's.
* G4: no leakage (the leakage tests in ``tests/predict``, run with every gate).

Piece 1's gate (spec addendum 2026-10-20 d): G4 and pooled G1 (with and without the season
reported apart) gate it; G1 per season, G2 and G3 are reported, not gated, because the
model and B0 are judged on the same labels, which the archive biases high under alerts (its
lists come mostly from the storm days it captured). The launch gate before the public
launch: the storm classes' absolute levels re-anchored on live-read days (complete daily
reads of every list this winter) by piece 3's retrain under its no-worse rule.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.predict.calendar import season_label
from snowlight.predict.config import ModelSettings
from snowlight.predict.pool import (
    Floats,
    Places,
    Rows,
    Strengths,
    chain,
    delay_rules,
    effective_situations,
    level_counts,
    publish_rates,
    rules_of,
    tables_from_rows,
    tune,
)
from snowlight.predict.situations import SITUATIONS, WeatherClass

WEATHER_OF_SITUATION: Final = np.array([int(item.weather) for item in SITUATIONS], dtype=np.int64)


@dataclass(frozen=True, slots=True)
class Scored:
    """Every test row's outcome and the chances each model gave it."""

    frame: pl.DataFrame
    """Columns: district, day, season, weather, region, state, cluster, outcome (no_school,
    delayed, open), y (no school), y_delay, p (published), p_raw, q (published delay), b0, b1."""


def brier(p: Floats, y: Floats) -> float:
    """Mean squared error (NaN for no rows)."""
    return float(np.mean((p - y) ** 2)) if p.size else math.nan


def clustered_se(y: Floats, clusters: Sequence[object]) -> float:
    """The standard error of the mean of ``y`` with clusters (a storm day's district-days
    move together)."""
    n = y.size
    if n == 0:
        return math.nan
    residual = y - y.mean()
    sums: dict[object, float] = {}
    for value, cluster in zip(residual.tolist(), clusters, strict=True):
        sums[cluster] = sums.get(cluster, 0.0) + value
    return math.sqrt(sum(total * total for total in sums.values())) / n


@dataclass(frozen=True, slots=True)
class Bin:
    """One reliability bin."""

    low: float
    high: float
    rows: int
    mean_p: float
    observed: float
    se: float
    clusters: int = 0
    """Storm-day clusters (day, market) the bin's rows fall in."""

    @property
    def gap(self) -> float:
        """Observed rate less the mean chance."""
        return self.observed - self.mean_p

    def within(self, floor: float = 0.05) -> bool:
        """Whether the observed rate is within ``max(floor, 2 SE)`` of the mean chance."""
        return abs(self.observed - self.mean_p) <= max(floor, 2 * self.se)


def reliability(p: Floats, y: Floats, clusters: Sequence[object], bins: int) -> list[Bin]:
    """Equal-width bins of ``p`` on [0, 1]."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    cluster_array = np.empty(len(clusters), dtype=object)
    cluster_array[:] = list(clusters)
    found: list[Bin] = []
    for b in range(bins):
        mask = index == b
        rows = int(mask.sum())
        if not rows:
            found.append(Bin(float(edges[b]), float(edges[b + 1]), 0, math.nan, math.nan, math.nan))
            continue
        members = cluster_array[mask].tolist()
        found.append(
            Bin(
                float(edges[b]),
                float(edges[b + 1]),
                rows,
                float(p[mask].mean()),
                float(y[mask].mean()),
                clustered_se(y[mask], members),
                len(set(members)),
            )
        )
    return found


def ece(found: Sequence[Bin]) -> float:
    """Expected calibration error: the row-weighted mean gap of the bins."""
    total = sum(item.rows for item in found)
    if not total:
        return math.nan
    return sum(item.rows * abs(item.observed - item.mean_p) for item in found if item.rows) / total


def caught(p: Floats, y: Floats, threshold: float = 0.5) -> tuple[float, float]:
    """(share of outcomes given ``threshold`` or more, precision at ``threshold``)."""
    hits = p >= threshold
    positives = y > 0
    recall = float((hits & positives).sum() / positives.sum()) if positives.any() else math.nan
    precision = float((hits & positives).sum() / hits.sum()) if hits.any() else math.nan
    return recall, precision


def _rate_by(key: npt.NDArray[np.int64], y: Floats, n_keys: int) -> Floats:
    ys = np.bincount(key, weights=y, minlength=n_keys)
    ns = np.bincount(key, minlength=n_keys).astype(np.float64)
    return (ys + 1.0) / (ns + 2.0)


def baselines(train: Rows, test: Rows, places: Places) -> tuple[Floats, Floats]:
    """B0 (national rate per class) and B1 (state rate per class), from the training rows."""
    classes = len(WeatherClass)
    train_class = WEATHER_OF_SITUATION[train.situation]
    test_class = WEATHER_OF_SITUATION[test.situation]
    b0 = _rate_by(train_class, train.y, classes)[test_class]
    states = len(places.states) + 1
    train_state = places.state[train.district] + 1
    test_state = places.state[test.district] + 1
    key_train = train_state * classes + train_class
    key_test = test_state * classes + test_class
    ys = np.bincount(key_train, weights=train.y, minlength=states * classes)
    ns = np.bincount(key_train, minlength=states * classes).astype(np.float64)
    national = _rate_by(train_class, train.y, classes)
    b1 = (ys[key_test] + 2.0 * national[test_class]) / (ns[key_test] + 2.0)
    return b0, b1


@dataclass(frozen=True, slots=True)
class Fold:
    """One test season's fit and predictions."""

    season: int
    strengths: Strengths
    strengths_delay: Strengths
    p_raw: Floats
    p: Floats
    q: Floats
    b0: Floats
    b1: Floats


def fit_predict(  # noqa: PLR0913, PLR0917 - the rows, the places, the seasons and the settings
    rows: Rows,
    delay_rows: Rows,
    test: Rows,
    places: Places,
    seasons: Sequence[int],
    settings: ModelSettings,
) -> tuple[Strengths, Strengths, Floats, Floats, Floats]:
    """Fit strengths and counts on ``seasons`` and predict ``test``: (strengths for no
    school, for delays, raw p, published p, published delay)."""
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
    p, delay = publish_rates(found.p, q, settings.floor, settings.ceiling)
    unmodeled = found.situation < 0
    p_raw = np.where(unmodeled, np.nan, found.p)
    return strengths, strengths_delay, p_raw, np.where(unmodeled, np.nan, p), delay


def walk_forward(
    rows: Rows,
    delay_rows: Rows,
    places: Places,
    test_seasons: Sequence[int],
    settings: ModelSettings,
) -> list[Fold]:
    """Every test season, fit on the seasons before it only."""
    seasons = sorted(set(rows.season.tolist()))
    folds: list[Fold] = []
    for season in test_seasons:
        before = [s for s in seasons if s < season]
        test = rows.subset(rows.season == season)
        if not before or not len(test):
            continue
        strengths, strengths_delay, p_raw, p, q = fit_predict(
            rows, delay_rows, test, places, before, settings
        )
        train = rows.subset(np.isin(rows.season, np.array(before)))
        b0, b1 = baselines(train, test, places)
        folds.append(Fold(season, strengths, strengths_delay, p_raw, p, q, b0, b1))
    return folds


@dataclass(frozen=True, slots=True)
class Summary:
    """The metrics of one set of rows."""

    rows: int
    brier: float
    brier_b0: float
    brier_b1: float
    log_loss: float
    caught: float
    precision: float
    caught_b0: float
    precision_b0: float = math.nan

    def as_json(self) -> dict[str, float | int]:
        """Rounded for the report."""
        return {
            name: (round(value, 5) if isinstance(value, float) and not math.isnan(value) else value)
            for name, value in (
                ("rows", self.rows),
                ("brier", self.brier),
                ("brier_b0", self.brier_b0),
                ("brier_b1", self.brier_b1),
                ("log_loss", self.log_loss),
                ("caught_50", self.caught),
                ("precision_50", self.precision),
                ("caught_50_b0", self.caught_b0),
                ("precision_50_b0", self.precision_b0),
            )
        }


def summarize(frame: pl.DataFrame) -> Summary:
    """Metrics over ``frame`` (a :class:`Scored` frame or part of one)."""
    y = frame["y"].to_numpy().astype(np.float64)
    p = frame["p"].to_numpy().astype(np.float64)
    b0 = frame["b0"].to_numpy().astype(np.float64)
    q = np.clip(p, 1e-6, 1 - 1e-6)
    loss = float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))) if y.size else math.nan
    recall, precision = caught(p, y)
    recall_b0, precision_b0 = caught(b0, y)
    return Summary(
        rows=frame.height,
        brier=brier(p, y),
        brier_b0=brier(b0, y),
        brier_b1=brier(frame["b1"].to_numpy().astype(np.float64), y),
        log_loss=loss,
        caught=recall,
        precision=precision,
        caught_b0=recall_b0,
        precision_b0=precision_b0,
    )


@dataclass(frozen=True, slots=True)
class SeasonG1:
    """G1 in one test season, on its storm district-days."""

    season: int
    storm_rows: int
    brier: float
    brier_b0: float
    gated: bool
    apart: bool
    tolerance: float

    @property
    def excess(self) -> float:
        """How much worse than B0 the model is (negative: better)."""
        return self.brier - self.brier_b0

    @property
    def ok(self) -> bool:
        """No worse than B0 by more than the tolerance."""
        return self.excess <= self.tolerance


@dataclass(frozen=True, slots=True)
class Gates:
    """G1 to G3 and what they found."""

    g1_pooled: bool
    """Pooled over every test season, the season reported apart (2020-21) included."""
    g1_pooled_without_apart: bool
    """Pooled over the test seasons without the season reported apart (spec c.3)."""
    g1_by_season: tuple[SeasonG1, ...]
    g2: bool
    g2_failing: tuple[str, ...]
    g3: bool

    @property
    def g1_counted(self) -> int:
        """Seasons gated (enough storm rows)."""
        return sum(item.gated for item in self.g1_by_season)

    @property
    def g1_seasons(self) -> int:
        """Gated seasons within the tolerance of B0."""
        return sum(item.gated and item.ok for item in self.g1_by_season)

    @property
    def g1(self) -> bool:
        """G1 as amended: pooled with and without the season reported apart, and every gated
        season."""
        return (
            self.g1_pooled and self.g1_pooled_without_apart and self.g1_seasons == self.g1_counted
        )

    @property
    def passed(self) -> bool:
        """Piece 1's gate (addendum 2026-10-20 d): pooled G1, with and without the season
        reported apart. G4 is the leakage tests; G1 per season, G2 and G3 are reported."""
        return self.g1_pooled and self.g1_pooled_without_apart


def gates(  # noqa: PLR0913 - the gate's settings, passed through
    scored: pl.DataFrame,
    bins: Sequence[Bin],
    apart: Sequence[int],
    min_rows: int,
    *,
    g1_min_storm_rows: int,
    g1_tolerance: float,
) -> Gates:
    """Judge G1 to G3 on the scored test rows."""
    storm = scored.filter(pl.col("weather") > 0)
    pooled = summarize(storm)
    by_season: list[SeasonG1] = []
    for season in sorted(set(storm["season"].to_list())):
        part = summarize(storm.filter(pl.col("season") == season))
        by_season.append(
            SeasonG1(
                season=int(season),
                storm_rows=part.rows,
                brier=part.brier,
                brier_b0=part.brier_b0,
                gated=part.rows >= g1_min_storm_rows,
                apart=season in apart,
                tolerance=g1_tolerance,
            )
        )
    failing = tuple(
        f"[{item.low:.1f}, {item.high:.1f})"
        for item in bins
        if item.rows >= min_rows and not item.within()
    )
    everything = summarize(scored)
    kept = summarize(storm.filter(~pl.col("season").is_in(list(apart))))
    return Gates(
        g1_pooled=pooled.brier <= pooled.brier_b0,
        g1_pooled_without_apart=kept.rows == 0 or kept.brier <= kept.brier_b0,
        g1_by_season=tuple(by_season),
        g2=not failing,
        g2_failing=failing,
        g3=everything.caught >= everything.caught_b0,
    )


def scored_frame(
    folds: Sequence[Fold],
    rows: Rows,
    places: Places,
    labels: pl.DataFrame,
) -> pl.DataFrame:
    """The test rows of every fold, joined back to their labels (day, outcome, cluster). A row
    of a situation that fold could not publish (no labeled days of it or its fallbacks in the
    training seasons: a dark pass) is left out; :func:`unmodeled_rows` counts them."""
    parts: list[pl.DataFrame] = []
    region_names = np.array([*places.regions, "?"], dtype=object)
    state_names = np.array([*places.states, "?"], dtype=object)
    for fold in folds:
        test = rows.subset(rows.season == fold.season)
        parts.append(
            pl.DataFrame(
                {
                    "position": np.flatnonzero(rows.season == fold.season),
                    "district": [places.districts[i] for i in test.district.tolist()],
                    "season": test.season,
                    "weather": WEATHER_OF_SITUATION[test.situation],
                    "region": region_names[places.region[test.district]].tolist(),
                    "state": state_names[places.state[test.district]].tolist(),
                    "y": test.y,
                    "p_raw": fold.p_raw,
                    "p": fold.p,
                    "q": fold.q,
                    "b0": fold.b0,
                    "b1": fold.b1,
                }
            )
        )
    if not parts:
        return pl.DataFrame()
    found = pl.concat(parts).filter(pl.col("p").is_not_nan())
    keyed = labels.with_row_index("position").select(
        pl.col("position").cast(pl.Int64), "day", "outcome", "cluster"
    )
    return found.with_columns(pl.col("position").cast(pl.Int64)).join(
        keyed, on="position", how="left"
    )


def unmodeled_rows(folds: Sequence[Fold]) -> int:
    """Test rows no fold could publish a chance for."""
    return sum(int(np.isnan(fold.p).sum()) for fold in folds)


def storm_day_briers(scored: pl.DataFrame, min_closings: int) -> list[float]:
    """Brier per storm day: (day, cluster) groups with ``min_closings`` or more closings."""
    groups = (
        scored.group_by("day", "cluster")
        .agg(
            pl.col("y").sum().alias("closings"),
            ((pl.col("p") - pl.col("y")) ** 2).mean().alias("brier"),
        )
        .filter(pl.col("closings") >= min_closings)
    )
    return sorted(groups["brier"].to_list())


def by_key(scored: pl.DataFrame, key: str) -> dict[str, dict[str, float | int]]:
    """Summaries per value of ``key``."""
    return {
        str(value): summarize(scored.filter(pl.col(key) == value)).as_json()
        for value in sorted(set(scored[key].to_list()), key=str)
    }


def g1_table(judged: Gates) -> list[str]:
    """The report's G1 table per season, on storm rows, as the amended gate reads it."""
    lines = ["", "## G1 by season (storm rows, reported for piece 1)", ""]
    lines.append(
        "G1 as amended by the lead (spec addendum 2026-10-20 b): pooled storm Brier at most "
        "B0's, and every season with enough storm rows no worse than B0's by more than the "
        "tolerance; smaller seasons are reported. Addendum 2026-10-20 d: for piece 1 the "
        "seasons are reported, not gated; pooled G1 gates."
    )
    lines.extend(["", "| season | storm rows | brier | b0 | model - b0 | amended G1 |"])
    lines.append("|---|---|---|---|---|---|")
    for item in judged.g1_by_season:
        verdict = "within tolerance" if item.ok else "over tolerance"
        status = verdict if item.gated else "reported (too few rows)"
        note = " (reported apart)" if item.apart else ""
        lines.append(
            f"| {season_label(item.season)}{note} | {item.storm_rows} | {item.brier:.5f} | "
            f"{item.brier_b0:.5f} | {item.excess:+.5f} | {status} |"
        )
    lines.append("")
    return lines


def bin_table(bins: Sequence[Bin]) -> list[str]:
    """One reliability table: each bin's rows, storm-day clusters, mean chance, observed rate,
    their gap, the clustered SE and whether the gap is within G2's bound."""
    lines = ["| bin | rows | clusters | mean p | observed | gap | SE | within |"]
    lines.append("|---|---|---|---|---|---|---|---|")
    for item in bins:
        if item.rows:
            lines.append(
                f"| {item.low:.1f}-{item.high:.1f} | {item.rows} | {item.clusters} | "
                f"{item.mean_p:.4f} | {item.observed:.4f} | {item.gap:+.4f} | {item.se:.4f} | "
                f"{'yes' if item.within() else 'no'} |"
            )
    return lines


G4_NOTE: Final = (
    "G4 (no leakage) is not computed here: it is the leakage tests in tests/predict, which "
    "run with every gate (pytest), and piece 1 needs them to pass as well."
)

PIECE1_DECISION: Final = (
    "Gate decision (spec addendum 2026-10-20 d): G4 (leakage) and pooled G1 (model against "
    "B0) gate piece 1. G1 per season, G2 and G3 are reported, not gated: the archive's lists "
    "come mostly from the storm days it captured, so the labeled closing rates under alerts "
    "are biased high, and the model and B0 are judged on the same labels. The archive "
    "supports relative propensities (which districts close more readily than their "
    "neighbors) far better than absolute levels per alert class."
)
LAUNCH_GATE: Final = (
    "Launch gate (before the public launch): the storm classes' absolute levels are "
    "re-anchored on live-read days (complete daily reads of every list this winter) by "
    "piece 3's automatic retrain under its no-worse rule. Until then the alert-class chances "
    "are what the recorded storms say, and the why sentence counts the recorded days."
)


def report_markdown(
    metrics: Mapping[str, object],
    bins: Sequence[Bin],
    judged: Gates,
    cases: Sequence[str],
) -> str:
    """The internal backtest report."""
    lines = ["# Backtest, piece 1 (internal)", ""]
    lines.append(
        f"Piece 1 gate (pooled G1, here): {'PASS' if judged.passed else 'FAIL'} (pooled G1 "
        f"{'pass' if judged.g1_pooled else 'FAIL'}, without 2020-21 "
        f"{'pass' if judged.g1_pooled_without_apart else 'FAIL'})."
    )
    lines.append("")
    lines.append(G4_NOTE)
    lines.extend(["", PIECE1_DECISION, ""])
    lines.append(
        f"Reported, not gated: G1 seasons {judged.g1_seasons} of {judged.g1_counted} with "
        f"enough storm rows within the tolerance, "
        f"G2 {'pass' if judged.g2 else 'FAIL ' + ', '.join(judged.g2_failing)}, "
        f"G3 {'pass' if judged.g3 else 'FAIL'}."
    )
    lines.extend(["", LAUNCH_GATE])
    lines.extend(g1_table(judged))
    for name in ("all", "storm"):
        summary = metrics.get(name)
        if isinstance(summary, dict):
            lines.append(f"- {name}: " + ", ".join(f"{k} {v}" for k, v in summary.items()))
    for title in ("by_season", "by_class", "by_region"):
        table = metrics.get(title)
        if not isinstance(table, dict):
            continue
        lines.extend(["", f"## {title.replace('_', ' ')}", ""])
        lines.append(
            "| key | rows | brier | b0 | b1 | caught 50 | b0 caught | precision | b0 precision |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for key, value in table.items():
            label = season_label(int(key)) if title == "by_season" else key
            lines.append(
                f"| {label} | {value['rows']} | {value['brier']} | {value['brier_b0']} | "
                f"{value['brier_b1']} | {value['caught_50']} | {value['caught_50_b0']} | "
                f"{value['precision_50']} | {value.get('precision_50_b0')} |"
            )
    lines.extend(["", "## Reliability (unrounded chance, SE clustered by storm day)", ""])
    lines.extend(bin_table(bins))
    regional = metrics.get("reliability_by_region")
    if isinstance(regional, dict):
        lines.extend(["", "## Reliability by region (same bins; G2 is judged nationally)", ""])
        for region, found in regional.items():
            lines.extend(["", f"### {region}", ""])
            lines.extend(bin_table(found))
    lines.extend(["", "## Named cases", ""])
    lines.extend(cases)
    return "\n".join(lines) + "\n"


def named_cases(
    labels: pl.DataFrame,
    scored: pl.DataFrame,
    names: Mapping[str, str],
    days: Sequence[object],
    markets: Mapping[str, str],
) -> list[str]:
    """The named cases (spec c.3): every named district on every named day, with its label or
    why it has none, its published chance when scored, and what the rest of its market did."""
    lines = [
        "Every named district and day: its label, or why it has none; its chance where the "
        "backtest scored it; and the labels of the other districts of its market that day.",
        "",
        "| district | day | label | chance | market that day |",
        "|---|---|---|---|---|",
    ]
    keyed = {(row["district"], row["day"]): row for row in labels.iter_rows(named=True)}
    chances = {
        (row["district"], row["day"]): row
        for row in scored.iter_rows(named=True)
        if row["district"] in names
    }
    for leaid, name in names.items():
        market = markets.get(leaid)
        for day in days:
            row = keyed.get((leaid, day))
            if row is None:
                label = "no morning read (no station that lists it read that morning)"
            elif row["outcome"] == "unknown":
                label = f"unknown ({row['unknown_why']})"
            else:
                label = str(row["outcome"])
            score = chances.get((leaid, day))
            chance = f"{score['p']:.2f} (b0 {score['b0']:.2f})" if score else "-"
            told = ""
            if market is not None:
                peers = labels.filter(
                    (pl.col("day") == day)
                    & (pl.col("cluster") == market)
                    & (pl.col("district") != leaid)
                )
                counts = peers.group_by("outcome").len().sort("outcome")
                told = ", ".join(f"{outcome} {count}" for outcome, count in counts.iter_rows())
            lines.append(
                f"| {name} ({leaid}) | {day} | {label} | {chance} | "
                f"{market or '?'}: {told or 'no labels'} |"
            )
    return lines


def reliability_svg(bins: Sequence[Bin]) -> str:
    """The reliability diagram as a small SVG (observed against mean chance, per bin)."""
    size, pad = 360, 40
    inner = size - 2 * pad

    def x(value: float) -> float:
        return pad + value * inner

    def y(value: float) -> float:
        return size - pad - value * inner

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" font-family="sans-serif" font-size="11">',
        f'<rect width="{size}" height="{size}" fill="white"/>',
        f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(1)}" y2="{y(1)}" stroke="#999" '
        'stroke-dasharray="4 3"/>',
        f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(1)}" y2="{y(0)}" stroke="#333"/>',
        f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(0)}" y2="{y(1)}" stroke="#333"/>',
        f'<text x="{size / 2}" y="{size - 8}" text-anchor="middle">mean chance</text>',
        f'<text x="12" y="{size / 2}" transform="rotate(-90 12 {size / 2})" '
        'text-anchor="middle">observed</text>',
    ]
    for item in bins:
        if not item.rows:
            continue
        radius = 2 + min(8.0, math.log10(item.rows + 1) * 2)
        low = max(0.0, item.observed - 2 * item.se)
        high = min(1.0, item.observed + 2 * item.se)
        parts.append(
            f'<line x1="{x(item.mean_p):.1f}" y1="{y(low):.1f}" x2="{x(item.mean_p):.1f}" '
            f'y2="{y(high):.1f}" stroke="#2a6fdb"/>'
        )
        parts.append(
            f'<circle cx="{x(item.mean_p):.1f}" cy="{y(item.observed):.1f}" r="{radius:.1f}" '
            'fill="#2a6fdb"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def chances_on(
    rows: Rows,
    delay_rows: Rows,
    places: Places,
    cells: Sequence[tuple[str, int, int]],
    settings: ModelSettings,
) -> list[float | None]:
    """The walk-forward chance of each (unit, situation index, season) cell, labeled or not:
    fit on the seasons before its own only (the named cases' days, spec piece 2). ``None``
    where no season comes before, or the unit is not in ``places``."""
    position = places.position()
    seasons = sorted(set(rows.season.tolist()))
    found: list[float | None] = []
    for unit, situation, season in cells:
        before = [s for s in seasons if s < season]
        if not before or unit not in position:
            found.append(None)
            continue
        test = Rows(
            np.array([position[unit]], dtype=np.int64),
            np.array([situation], dtype=np.int64),
            np.array([season], dtype=np.int64),
            np.array([np.nan]),
        )
        _s, _d, _raw, p, _q = fit_predict(rows, delay_rows, test, places, before, settings)
        found.append(None if np.isnan(p[0]) else float(p[0]))
    return found
