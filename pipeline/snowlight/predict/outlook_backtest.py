"""S7-F's walk-forward backtest and its gates GF1-GF8 and GF10 (spec-f s. 12). Internal only.

For each test season ``S`` (2019-20 to 2025-26), ``T`` is fit on the cases of the seasons
before ``S`` (from 2018-19, the first NDFD season) and the class rates on the labels of the
seasons before ``S``; every labeled district-day of ``S`` is then given, at each scoring moment
``t``, the chance each model would have published:

* **S7-F**: :func:`snowlight.predict.outlook.chance` with ``T``, rates from the 05:00 labels;
* **B-issued**: the class issued by ``t`` (rule D2), rates refit on the 05:00 labels (isolates
  the outlook);
* **B-shipped**: the class issued by ``t``, piece 1's 21:00 rates (what ships today; S7-L adds
  nothing in the archive seasons).

Labels: the 05:00 record's (rule D3), the same rows for every model. ``E(t)``: labeled rows
with no warning issued by ``t``; ``E20`` = ``E(20:00 D-1)``; ``E20-none``: no alert and no
heads-up at all at 20:00. Clusters: date x market. The archive's labels are storm-biased (its
lists come mostly from big storm days), so this backtest can veto an idea that hurts but cannot
prove one helps: the report splits every gain into rows raised and rows lowered, and reports
each gate within class and storm-size strata and a level-free within-day ranking (calc-research
plan, sec. 2.1 T4).
"""

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.output import write_json
from snowlight.predict import backtest, outlook, pool, train
from snowlight.predict.config import ModelSettings, PredictConfig
from snowlight.predict.outlook_states import INDEX_OF, MOMENTS, RECORD_INDEX

type Floats = npt.NDArray[np.float64]
type Ints = npt.NDArray[np.int64]
type Bools = npt.NDArray[np.bool_]

MODELS: Final = ("s7f", "issued", "shipped")
SCORED: Final = ("20:00", "19:15", "22:15", "01:15", "04:15", "10:15", "13:15", "16:15", "05:00")
LATE: Final = ("19:15", "22:15", "01:15", "04:15")
DAYTIME: Final = ("10:15", "13:15", "16:15")
FIRST_CASE_SEASON: Final = 2018
NAMED_DATES: Final = (
    date(2024, 1, 16),
    date(2024, 1, 22),
    date(2024, 1, 19),
    date(2025, 2, 6),
    date(2023, 3, 14),
)
"""The five largest no-warning-yet dates (spec-f GF10)."""
KC_DAYS: Final = tuple(date(2025, 1, day) for day in range(6, 11))
SPLIT_MARKET_DAYS: Final = (
    (date(2023, 2, 28), "New York, NY DMA"),
    (date(2023, 3, 14), "New York, NY DMA"),
    (date(2023, 3, 14), "Hartford & New Haven, CT DMA"),
    (date(2025, 2, 21), "Colorado Springs-Pueblo, CO DMA"),
)
"""The split market-days chosen by outcome (plan sec. 2.1 T4): reported apart, in sample."""
THRESHOLD: Final = 0.30
WIDE_GRID: Final = (*outlook.GRID, 8192.0, 32768.0, 131072.0)
"""A wider grid for ``m``, chosen on the training seasons only (a diagnostic: the spec's grid
stops at 2048, where every fold from 2020-21 lands)."""
INFORMATIVE_CLOSINGS: Final = 40
INFORMATIVE_DATES: Final = 3
"""A subset check informs only with 40 or more closings on 3 or more dates (GF2's bar)."""
SEASON_ROWS: Final = 300
_EPSILON: Final = 1e-6


# --- the rates ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rates:
    """A fold's chain over every (district, situation): no school and delay, raw."""

    p: Floats
    q: Floats


def full_rates(
    rows: pool.Rows,
    delay_rows: pool.Rows,
    places: pool.Places,
    seasons: Sequence[int],
    settings: ModelSettings,
) -> Rates:
    """The rates fit on ``seasons`` (as :func:`snowlight.predict.backtest.fit_predict` fits
    them) for every district and situation; NaN where nothing may be published."""
    keep = np.isin(rows.season, np.array(list(seasons)))
    keep_delay = np.isin(delay_rows.season, np.array(list(seasons)))
    train_rows, train_delay = rows.subset(keep), delay_rows.subset(keep_delay)
    tables = pool.tables_from_rows(train_rows, places, sorted(seasons))
    tables_delay = pool.tables_from_rows(train_delay, places, sorted(seasons))
    rules = pool.rules_of(settings)
    later = pool.delay_rules(rules)
    strengths = pool.tune(
        train_rows, places, tables, sorted(seasons), settings.m_grid, rules=rules
    ).strengths
    strengths_delay = pool.tune(
        train_delay, places, tables_delay, sorted(seasons), settings.m_grid, rules=later
    ).strengths
    found = pool.chain(pool.level_counts(places, *tables.total()), strengths, rules=rules)
    total_y, total_n = tables.total()
    mapping = pool.effective_situations(total_y.sum(axis=0), total_n.sum(axis=0), rules)
    q = pool.chain(
        pool.level_counts(places, *tables_delay.total()),
        strengths_delay,
        rules=later,
        effective=mapping,
    ).p
    p = np.where(found.situation < 0, np.nan, found.p)
    return Rates(np.asarray(p, dtype=np.float64), np.asarray(q, dtype=np.float64))


# --- the rows -----------------------------------------------------------------------------------


def row_states(
    test: pl.DataFrame, states: pl.DataFrame, codes: pl.DataFrame
) -> tuple[Ints, Ints, Ints]:
    """Each test row's class, heads-up and forecast bucket at every moment: three arrays of
    shape (rows, moments); a row with no state is none, with no code unknown (13)."""
    width = len(MOMENTS)
    keyed = test.select("district", "day").with_row_index("row")
    joined = keyed.join(states, on=["district", "day"], how="left").sort("row")
    weather = np.zeros((test.height, width), dtype=np.int64)
    heads = np.zeros((test.height, width), dtype=np.int64)
    for k in range(width):
        weather[:, k] = joined[f"w{k}"].fill_null(0).to_numpy()
        heads[:, k] = joined[f"h{k}"].fill_null(0).to_numpy()
    bucket = np.full((test.height, width), outlook.UNKNOWN, dtype=np.int64)
    wide = codes.join(keyed.rename({"day": "night"}), on=["district", "night"], how="inner").select(
        "row", "sample", "code"
    )
    for k, moment in enumerate(MOMENTS):
        if moment.sample < 0:
            continue
        part = wide.filter(pl.col("sample") == moment.sample)
        bucket[part["row"].to_numpy(), k] = part["code"].to_numpy()
    return weather, heads, bucket


@dataclass(frozen=True, slots=True)
class Scores:
    """Every test row's chance at every scored moment, per model."""

    frame: pl.DataFrame
    """One row per (test row, moment): district, day, season, cluster, state, region, weather
    (05:00 class), outcome, y, y_delay, named, moment, c0, h, f, and p_/d_ per model (the
    published no-school and delay chances)."""


def score_fold(  # noqa: PLR0913, PLR0917 - the fold's rows, rates, outlook and settings
    test: pl.DataFrame,
    places: pool.Places,
    states: pl.DataFrame,
    codes: pl.DataFrame,
    fitted: outlook.Outlook,
    issued: Rates,
    shipped: Rates,
    settings: ModelSettings,
    wide: outlook.Outlook | None = None,
) -> pl.DataFrame:
    """The fold's scored rows (see :class:`Scores`). A row whose forecast bucket is unknown
    gets the identity from S7-F, as serving gives it (no ``T`` for that district; lead
    decision ``Dark.FORECAST``): ``unknown_f``. ``fell_back``: S7-F gave the identity because
    ``T`` weighs a class with no rate in the fold. ``wide``: the outlook fit on the wider
    grid of :data:`WIDE_GRID` (a diagnostic: ``p_s7fw``, ``d_s7fw``)."""
    position = places.position()
    district = np.array([position[d] for d in test["district"].to_list()], dtype=np.int64)
    after = test["after"].to_numpy().astype(np.bool_)
    weather, heads, bucket = row_states(test, states, codes)
    p05 = outlook.class_rates(issued.p, district, after)
    q05 = outlook.class_rates(issued.q, district, after)
    p21 = outlook.class_rates(shipped.p, district, after)
    q21 = outlook.class_rates(shipped.q, district, after)
    state_index = {name: i for i, name in enumerate(outlook.STATES)}
    state_names = [places.states[i] if i >= 0 else "?" for i in places.state[district].tolist()]
    state = np.array([state_index.get(name, -1) for name in state_names], dtype=np.int64)
    t_state = fitted.t_state()
    t_wide = wide.t_state() if wide is not None else None
    parts: list[pl.DataFrame] = []
    base = test.select(
        "district", "day", "season", "cluster", "weather", "outcome", "named"
    ).with_columns(
        pl.Series("state", state_names),
        (pl.col("outcome") == "no_school").cast(pl.Float64).alias("y"),
        (pl.col("outcome") == "delayed").cast(pl.Float64).alias("y_delay"),
    )
    for label in SCORED:
        k = INDEX_OF[label]
        moment = MOMENTS[k]
        c0 = weather[:, k]
        h = heads[:, k]
        f = bucket[:, k]
        before = np.full(c0.size, k != RECORD_INDEX)
        unknown = f == outlook.UNKNOWN
        dist = dist_wide = None
        if moment.slot > 0:
            slot = np.full(c0.size, moment.slot)
            dist = fitted.distribution(slot, np.minimum(c0, 1), h, f, state, table=t_state)
            dist[unknown] = 0.0
            if wide is not None:
                dist_wide = wide.distribution(slot, np.minimum(c0, 1), h, f, state, table=t_wide)
                dist_wide[unknown] = 0.0
        found: dict[str, outlook.Chance] = {
            "s7f": outlook.chance(
                p05, q05, c0, dist, before,
                mode=outlook.OutlookMode.ON, floor=settings.floor, ceiling=settings.ceiling,
            ),
            "issued": outlook.chance(
                p05, q05, c0, None, before,
                mode=outlook.OutlookMode.OFF, floor=settings.floor, ceiling=settings.ceiling,
            ),
            "shipped": outlook.chance(
                p21, q21, c0, None, before,
                mode=outlook.OutlookMode.OFF, floor=settings.floor, ceiling=settings.ceiling,
            ),
        }  # fmt: skip
        if wide is not None:
            found["s7fw"] = outlook.chance(
                p05, q05, c0, dist_wide, before,
                mode=outlook.OutlookMode.ON, floor=settings.floor, ceiling=settings.ceiling,
            )  # fmt: skip
        columns = {
            "moment": [label] * c0.size,
            "c0": c0,
            "h": h,
            "f": f,
            **{f"p_{name}": item.p for name, item in found.items()},
            **{f"d_{name}": item.delay for name, item in found.items()},
            "moved": found["s7f"].outlook,
            "unknown_f": found["s7f"].fell_back & unknown,
            "fell_back": found["s7f"].fell_back & ~unknown,
        }
        parts.append(base.hstack(pl.DataFrame(columns)))
    return pl.concat(parts)


# --- metrics ------------------------------------------------------------------------------------


def brier(p: Floats, y: Floats) -> float:
    """Mean squared error (NaN for no rows)."""
    return float(np.mean((p - y) ** 2)) if p.size else math.nan


def log_loss(p: Floats, y: Floats) -> float:
    """Mean log loss."""
    if not p.size:
        return math.nan
    q = np.clip(p, _EPSILON, 1 - _EPSILON)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def bootstrap_upper(
    diff: Floats, clusters: Sequence[object], draws: int, seed: int = 20261025
) -> float:
    """The upper end of the 90% cluster-bootstrap interval of the mean of ``diff`` (``draws``
    resamples of whole clusters)."""
    if not diff.size:
        return math.nan
    names = sorted(set(clusters), key=str)
    index = {name: i for i, name in enumerate(names)}
    member = np.array([index[c] for c in clusters], dtype=np.int64)
    sums = np.bincount(member, weights=diff, minlength=len(names))
    counts = np.bincount(member, minlength=len(names)).astype(np.float64)
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(names), size=(draws, len(names)))
    means = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    return float(np.quantile(means, 0.95))


def caught_at(p: Floats, y: Floats, threshold: float = THRESHOLD) -> tuple[float, float]:
    """(share of outcomes at ``threshold`` or more, precision at ``threshold``)."""
    return backtest.caught(p, y, threshold)


def clusters_of(frame: pl.DataFrame) -> list[str]:
    """Date x market."""
    return [
        f"{day}|{market}"
        for day, market in zip(frame["day"].to_list(), frame["cluster"].to_list(), strict=True)
    ]


def ece_of(frame: pl.DataFrame, model: str, bins: int = 10) -> tuple[float, list[backtest.Bin]]:
    """ECE and reliability bins (clustered SE) of a model's chance on ``frame``."""
    found = backtest.reliability(
        frame[f"p_{model}"].to_numpy().astype(np.float64),
        frame["y"].to_numpy().astype(np.float64),
        clusters_of(frame),
        bins,
    )
    return backtest.ece(found), found


def model_metrics(frame: pl.DataFrame) -> dict[str, Any]:
    """Rows, dates, closings and each model's Brier, log loss, caught and precision at 30%."""
    y = frame["y"].to_numpy().astype(np.float64)
    out: dict[str, Any] = {
        "rows": frame.height,
        "dates": frame["day"].n_unique(),
        "closings": int(y.sum()),
    }
    for model in MODELS:
        p = frame[f"p_{model}"].to_numpy().astype(np.float64)
        recall, precision = caught_at(p, y)
        out[model] = {
            "brier": _r(brier(p, y)),
            "log_loss": _r(log_loss(p, y)),
            "caught_30": _r(recall),
            "precision_30": _r(precision),
            "mean_p": _r(float(p.mean()) if p.size else math.nan),
        }
    return out


def _r(value: float, digits: int = 5) -> float | None:
    return None if math.isnan(value) else round(value, digits)


def _at(series: pl.Series, threshold: float = THRESHOLD) -> float:
    """The share of ``series`` at ``threshold`` or more (NaN for none)."""
    values = series.to_numpy().astype(np.float64)
    return float((values >= threshold).mean()) if values.size else math.nan


def _median(series: pl.Series) -> float:
    values = series.to_numpy().astype(np.float64)
    return float(np.median(values)) if values.size else math.nan


def strata(frame: pl.DataFrame) -> pl.DataFrame:
    """``frame`` with ``label_class`` (the 05:00 class: none, advisory, warning) and ``size``
    (the forecast at the moment: quiet, snow under 4 in, snow 4 in+, ice, cold, unknown)."""
    size = (
        pl.when(pl.col("f") == 0)
        .then(pl.lit("quiet"))
        .when(pl.col("f").is_between(1, 2))
        .then(pl.lit("snow_under_4"))
        .when(pl.col("f").is_between(3, 5))
        .then(pl.lit("snow_4_up"))
        .when(pl.col("f").is_between(6, 8))
        .then(pl.lit("ice"))
        .when(pl.col("f").is_between(9, 12))
        .then(pl.lit("cold"))
        .otherwise(pl.lit("unknown"))
    )
    return frame.with_columns(
        _class_name("weather").alias("label_class"),
        _class_name("c0").alias("c0_class"),
        size.alias("size"),
    )


def _class_name(column: str) -> pl.Expr:
    return (
        pl.when(pl.col(column) == 0)
        .then(pl.lit("none"))
        .when(pl.col(column) == 1)
        .then(pl.lit("advisory"))
        .otherwise(pl.lit("warning"))
    )


def by_strata(frame: pl.DataFrame, within: str = "size") -> list[dict[str, Any]]:
    """:func:`model_metrics` within (05:00 class) x ``within`` strata (``size``: the storm size
    the forecast gave at the moment; ``c0_class``: the class issued by then); a stratum with 30
    or more rows on 2 or more dates where S7-F is worse than a baseline by more than 0.01 is
    flagged."""
    found: list[dict[str, Any]] = []
    marked = strata(frame)
    for (label, size), part in sorted(
        marked.group_by("label_class", within), key=lambda item: (str(item[0][0]), str(item[0][1]))
    ):
        item = {"class": label, within: size, **model_metrics(part)}
        worse = [
            name
            for name in ("issued", "shipped")
            if item["rows"] >= 30  # noqa: PLR2004 - plan sec. 2.1 P3
            and item["dates"] >= 2  # noqa: PLR2004
            and (item["s7f"]["brier"] or 0) > (item[name]["brier"] or 0) + 0.01
        ]
        item["flag_worse_than"] = worse
        found.append(item)
    return found


def best_shift(p: Floats, y: Floats) -> float:
    """The single logit shift that minimizes the log loss of ``p`` on ``y`` (Newton steps)."""
    if not p.size:
        return 0.0
    z = np.log(np.clip(p, _EPSILON, 1 - _EPSILON) / (1 - np.clip(p, _EPSILON, 1 - _EPSILON)))
    shift = 0.0
    for _ in range(50):
        q = 1 / (1 + np.exp(-(z + shift)))
        gradient = float((q - y).sum())
        curvature = float((q * (1 - q)).sum())
        if curvature <= 0:
            break
        step = gradient / curvature
        shift -= float(np.clip(step, -2.0, 2.0))
        if abs(step) < _EPSILON:
            break
    return shift


def level_free(frame: pl.DataFrame) -> dict[str, Any]:
    """Each model's Brier after its own best logit shift per 05:00 class (removing the
    national class level; plan sec. 2.1 T4, a diagnostic)."""
    marked = strata(frame)
    out: dict[str, Any] = {}
    y_all = marked["y"].to_numpy().astype(np.float64)
    for model in MODELS:
        shifted = np.zeros(marked.height)
        for label in ("none", "advisory", "warning"):
            mask = (marked["label_class"] == label).to_numpy()
            if not mask.any():
                continue
            p = marked[f"p_{model}"].to_numpy().astype(np.float64)[mask]
            shift = best_shift(p, y_all[mask])
            z = np.log(
                np.clip(p, _EPSILON, 1 - _EPSILON) / (1 - np.clip(p, _EPSILON, 1 - _EPSILON))
            )
            shifted[mask] = 1 / (1 + np.exp(-(z + shift)))
        out[model] = _r(brier(shifted, y_all))
    return out


def ranking(frame: pl.DataFrame) -> dict[str, Any]:
    """Within-day ranking over every market-day with both outcomes: the share of (closed, not
    closed) district pairs each model orders the right way (ties count half), pooled over
    pairs; the four split market-days apart (in sample)."""
    split = {(day, market) for day, market in SPLIT_MARKET_DAYS}
    totals: dict[str, dict[str, float]] = {
        group: dict.fromkeys(MODELS, 0.0) | {"pairs": 0.0, "days": 0.0}
        for group in ("other", "split")
    }
    for (day, market), part in frame.group_by("day", "cluster"):
        y = part["y"].to_numpy()
        if y.min() == y.max():
            continue
        group = "split" if (day, market) in split else "other"
        closed, opened = y > 0, y == 0
        pairs = float(closed.sum() * opened.sum())
        totals[group]["pairs"] += pairs
        totals[group]["days"] += 1
        for model in MODELS:
            p = part[f"p_{model}"].to_numpy().astype(np.float64)
            a, b = p[closed][:, None], p[opened][None, :]
            totals[group][model] += float((a > b).sum() + 0.5 * (a == b).sum())
    return {
        group: {
            "market_days": int(item["days"]),
            "pairs": int(item["pairs"]),
            **{
                model: _r(item[model] / item["pairs"]) if item["pairs"] else None
                for model in MODELS
            },
        }
        for group, item in totals.items()
    }


def raised_lowered(frame: pl.DataFrame, against: str, model: str = "s7f") -> dict[str, Any]:
    """``model``'s gain over ``against`` split into rows it raised, lowered and left: rows,
    dates, closings and the summed squared error saved (positive: ``model`` better), each also
    by the 05:00 class (``alert_days``: advisory or warning, where the archive's lists are
    kept mostly from big storms)."""
    p = frame[f"p_{model}"].to_numpy().astype(np.float64)
    b = frame[f"p_{against}"].to_numpy().astype(np.float64)
    y = frame["y"].to_numpy().astype(np.float64)
    weather = frame["weather"].to_numpy().astype(np.int64)
    days = frame["day"].to_list()
    saved = (b - y) ** 2 - (p - y) ** 2
    out: dict[str, Any] = {}
    for name, mask in (("raised", p > b), ("lowered", p < b), ("same", p == b)):
        out[name] = {
            "rows": int(mask.sum()),
            "dates": len({d for d, m in zip(days, mask.tolist(), strict=True) if m}),
            "closings": int(y[mask].sum()),
            "sse_saved": _r(float(saved[mask].sum())),
            "by_label_class": {
                label: {
                    "rows": int(part.sum()),
                    "closings": int(y[part].sum()),
                    "sse_saved": _r(float(saved[part].sum())),
                }
                for label, part in (
                    ("none", mask & (weather == 0)),
                    ("alert_days", mask & (weather > 0)),
                )
            },
        }
    return out


def gain_by_date(frame: pl.DataFrame, model: str = "s7f") -> list[dict[str, Any]]:
    """``model``'s summed squared error saved over each baseline, per date (``split``: the
    date holds one of the four split market-days chosen by outcome)."""
    split_days = {day for day, _market in SPLIT_MARKET_DAYS}
    y = pl.col("y")
    found = (
        frame.group_by("day")
        .agg(
            pl.len().alias("rows"),
            y.sum().cast(pl.Int64).alias("closings"),
            *[
                ((pl.col(f"p_{base}") - y) ** 2 - (pl.col(f"p_{model}") - y) ** 2)
                .sum()
                .alias(f"vs_{base}")
                for base in ("issued", "shipped")
            ],
        )
        .sort("day")
    )
    return [
        {
            "day": row["day"].isoformat(),
            "rows": row["rows"],
            "closings": row["closings"],
            "sse_saved_vs_issued": _r(row["vs_issued"]),
            "sse_saved_vs_shipped": _r(row["vs_shipped"]),
            "split": row["day"] in split_days,
        }
        for row in found.iter_rows(named=True)
    ]


NO_GAIN: Final = "no gain"
RAISED_ON_ALERT_DAYS: Final = (
    "no archive evidence (plan T4): the gain comes from raised chances on alert days"
)
RAISED_ONLY: Final = "no archive evidence (plan T4): the gain comes from raised chances"
NOT_RAISES_ALONE: Final = (
    "the gain does not come from raises alone; still in sample, and the storm-biased "
    "archive can veto but not prove help"
)


def evidence(frame: pl.DataFrame, against: str, model: str = "s7f") -> dict[str, Any]:
    """What ``model``'s gain over ``against`` on ``frame`` is worth under plan T4: the total
    squared error saved, the part from raised rows (and from raised rows on alert days) and
    from lowered rows, the fewest dates whose gain makes up the total, and the verdict (a gain
    that raised chances on alert days account for, or raised chances at all, is no evidence)."""
    split = raised_lowered(frame, against, model)
    raised = split["raised"]["sse_saved"] or 0.0
    lowered = split["lowered"]["sse_saved"] or 0.0
    raised_alert = split["raised"]["by_label_class"]["alert_days"]["sse_saved"] or 0.0
    total = raised + lowered
    dates = sorted(
        (
            (item[f"sse_saved_vs_{against}"] or 0.0, item["day"])
            for item in gain_by_date(frame, model)
        ),
        reverse=True,
    )
    carried: list[dict[str, Any]] = []
    if total > 0:
        running = 0.0
        for gain, day in dates:
            carried.append({"day": day, "sse_saved": _r(gain)})
            running += gain
            if running >= total:
                break
    if total <= 0:
        verdict = NO_GAIN
    elif raised_alert >= total:
        verdict = RAISED_ON_ALERT_DAYS
    elif raised >= total:
        verdict = RAISED_ONLY
    else:
        verdict = NOT_RAISES_ALONE
    return {
        "sse_saved": _r(total),
        "raised": _r(raised),
        "raised_on_alert_days": _r(raised_alert),
        "lowered": _r(lowered),
        "dates_carrying_the_gain": carried,
        "verdict": verdict,
        "archive_evidence": verdict == NOT_RAISES_ALONE,
    }


def diagnostics(frame: pl.DataFrame) -> dict[str, Any]:
    """The research plan's checks (sec. 2.1 P3, T4) on one gate's rows: the metrics, the
    strata (05:00 class by storm size and by the class issued), the raised-vs-lowered split
    and its verdict against each baseline, the level-free check, the within-day ranking and
    the gain by date; and how many rows S7-F gave the identity (no rate in a class ``T``
    weighs, or no forecast)."""
    return {
        **model_metrics(frame),
        "s7f_identity_no_rate": int(frame["fell_back"].sum()) if "fell_back" in frame else 0,
        "s7f_identity_unknown_forecast": int(frame["unknown_f"].sum())
        if "unknown_f" in frame
        else 0,
        "evidence": {f"vs_{base}": evidence(frame, base) for base in ("issued", "shipped")},
        "raised_lowered": {
            f"vs_{base}": raised_lowered(frame, base) for base in ("issued", "shipped")
        },
        "strata_size": by_strata(frame, "size"),
        "strata_c0": by_strata(frame, "c0_class"),
        "level_free": level_free(frame),
        "ranking": ranking(frame),
        "by_date": gain_by_date(frame),
    }


GATE_SETS: Final[dict[str, tuple[str, ...]]] = {
    "e20": ("GF1", "GF2", "GF3", "GF4"),
    "late_pooled": ("GF1",),
    "e_22:15": ("GF4",),
    "e_04:15": ("GF4",),
    "all_20:00": ("GF4",),
    "daytime": ("GF7",),
    "record_storm": ("GF8",),
}
"""Each gate's labeled rows (GF5 reads T's cases, GF6 the unlabeled quiet nights: no
labels to split)."""


def gate_rows(scored: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """The rows of each set of :data:`GATE_SETS`."""
    e = pl.col("c0") < outlook.C0_VALUES
    return {
        "e20": scored.filter((pl.col("moment") == "20:00") & e),
        "late_pooled": scored.filter(pl.col("moment").is_in(LATE) & e),
        "e_22:15": scored.filter((pl.col("moment") == "22:15") & e),
        "e_04:15": scored.filter((pl.col("moment") == "04:15") & e),
        "all_20:00": scored.filter(pl.col("moment") == "20:00"),
        "daytime": scored.filter(pl.col("moment").is_in(DAYTIME) & e),
        "record_storm": scored.filter((pl.col("moment") == "05:00") & (pl.col("weather") > 0)),
    }


# --- the gates ----------------------------------------------------------------------------------


@dataclass(slots=True)
class Gate:
    """One gate: whether it passed and what it measured."""

    name: str
    passed: bool
    detail: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        """For the report."""
        return {"passed": self.passed, **self.detail}


def explicit(frame: pl.DataFrame, share: float) -> pl.DataFrame:
    """Rows whose label does not rest on the class of a no-reason closing: open rows, and
    closed or delayed rows with a weather reason named by ``share`` or more of the schools."""
    return frame.filter((pl.col("outcome") == "open") | (pl.col("named") >= share))


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def informative(frame: pl.DataFrame) -> dict[str, Any]:
    """Whether a subset check can tell anything: its closings and closing dates, and a note
    when they fall under 40 on 3 dates (the check then passes or fails on almost only open
    rows, so it is not cited as support)."""
    closed = frame.filter(pl.col("y") > 0)
    closings = closed.height
    dates = closed["day"].n_unique()
    enough = closings >= INFORMATIVE_CLOSINGS and dates >= INFORMATIVE_DATES
    return {
        "closings": closings,
        "closing_dates": dates,
        "informative": enough,
        "note": None
        if enough
        else (
            f"not informative on the archive ({_count(closings, 'closing')} on "
            f"{_count(dates, 'date')})"
        ),
    }


def gf1(scored: pl.DataFrame, draws: int, share: float, min_rows: int = 300) -> Gate:
    """Night-before skill on E20 (spec-f GF1)."""
    e20 = scored.filter((pl.col("moment") == "20:00") & (pl.col("c0") < outlook.C0_VALUES))
    y = e20["y"].to_numpy().astype(np.float64)
    p = e20["p_s7f"].to_numpy().astype(np.float64)
    detail: dict[str, Any] = {"e20": model_metrics(e20)}
    ok = True
    clusters = clusters_of(e20)
    for base in ("issued", "shipped"):
        b = e20[f"p_{base}"].to_numpy().astype(np.float64)
        ratio_ok = brier(p, y) <= 0.98 * brier(b, y)
        loss_ok = log_loss(p, y) < log_loss(b, y)
        upper = bootstrap_upper((p - y) ** 2 - (b - y) ** 2, clusters, draws)
        seasons: dict[str, Any] = {}
        season_ok = True
        sizes = {int(season): part.height for (season,), part in e20.group_by("season")}
        for season in sorted(sizes):
            part = e20.filter(pl.col("season") == season)
            if part.height < min_rows:
                continue
            ys = part["y"].to_numpy().astype(np.float64)
            excess = brier(part["p_s7f"].to_numpy().astype(np.float64), ys) - brier(
                part[f"p_{base}"].to_numpy().astype(np.float64), ys
            )
            seasons[str(season)] = _r(excess)
            season_ok &= excess <= 0.005  # noqa: PLR2004
        late = scored.filter(pl.col("moment").is_in(LATE) & (pl.col("c0") < outlook.C0_VALUES))
        yl = late["y"].to_numpy().astype(np.float64)
        late_ok = brier(late["p_s7f"].to_numpy().astype(np.float64), yl) <= brier(
            late[f"p_{base}"].to_numpy().astype(np.float64), yl
        )
        detail[f"vs_{base}"] = {
            "brier_ratio": _r(brier(p, y) / brier(b, y)) if brier(b, y) else None,
            "brier_ratio_ok": ratio_ok,
            "log_loss_lower": loss_ok,
            "bootstrap_upper": _r(upper),
            "bootstrap_ok": upper < 0,
            "season_excess_300": seasons,
            "seasons_ok": season_ok,
            "season_rows": {str(k): v for k, v in sorted(sizes.items())},
            "seasons_note": None
            if seasons
            else (
                f"untested: no season reaches {min_rows} E20 rows "
                f"(largest {max(sizes.values(), default=0)})"
            ),
            "late_pooled": {
                "rows": late.height,
                "brier_s7f": _r(brier(late["p_s7f"].to_numpy().astype(np.float64), yl)),
                f"brier_{base}": _r(brier(late[f"p_{base}"].to_numpy().astype(np.float64), yl)),
                "ok": late_ok,
            },
        }
        ok &= ratio_ok and loss_ok and upper < 0 and season_ok and late_ok
    named = explicit(e20, share)
    yn = named["y"].to_numpy().astype(np.float64)
    named_ok = brier(named["p_s7f"].to_numpy().astype(np.float64), yn) <= brier(
        named["p_shipped"].to_numpy().astype(np.float64), yn
    )
    detail["explicit_reason"] = {**model_metrics(named), **informative(named), "ok": named_ok}
    return Gate("GF1", ok and named_ok, detail)


def gf2(scored: pl.DataFrame) -> Gate:
    """Closings caught at 30% on E20 (spec-f GF2)."""
    e20 = scored.filter((pl.col("moment") == "20:00") & (pl.col("c0") < outlook.C0_VALUES))
    closed = e20.filter(pl.col("y") > 0)
    share = {model: _at(closed[f"p_{model}"]) for model in MODELS}
    ok = share["s7f"] >= share["shipped"] + 0.03 and share["s7f"] >= share["issued"]
    none = closed.filter((pl.col("c0") == 0) & (pl.col("h") == 0))
    none_share = _at(none["p_s7f"])
    gated = none.height >= 40 and none["day"].n_unique() >= 3  # noqa: PLR2004
    none_ok = (not gated) or none_share >= 0.5  # noqa: PLR2004
    return Gate(
        "GF2",
        ok and none_ok,
        {
            "closings": closed.height,
            "caught_30": {model: _r(value) for model, value in share.items()},
            "e20_none": {
                "closings": none.height,
                "dates": none["day"].n_unique(),
                "caught_30_s7f": _r(none_share),
                "gated": gated,
                "ok": none_ok,
                "note": None
                if gated
                else "under 40 closings on 3 dates: reported; S7-L's live check carries it",
            },
        },
    )


def gf3(scored: pl.DataFrame, share: float) -> Gate:
    """False alarms: precision at 30% on E20 and its explicit-reason rows (spec-f GF3)."""
    e20 = scored.filter((pl.col("moment") == "20:00") & (pl.col("c0") < outlook.C0_VALUES))
    detail: dict[str, Any] = {}
    ok = True
    for name, part in (("e20", e20), ("explicit_reason", explicit(e20, share))):
        y = part["y"].to_numpy().astype(np.float64)
        precision = {
            model: caught_at(part[f"p_{model}"].to_numpy().astype(np.float64), y)[1]
            for model in MODELS
        }
        alarms = {model: int((part[f"p_{model}"] >= THRESHOLD).sum()) for model in MODELS}
        s7f = precision["s7f"]
        here = all(
            math.isnan(precision[base]) or (not math.isnan(s7f) and s7f >= precision[base] - 0.03)
            for base in ("issued", "shipped")
        )
        detail[name] = {
            "precision_30": {model: _r(value) for model, value in precision.items()},
            "at_30": alarms,
            **informative(part),
            "ok": here,
        }
        ok &= here
    return Gate("GF3", ok, detail)


def gf4(scored: pl.DataFrame) -> Gate:
    """Calibration (spec-f GF4)."""
    detail: dict[str, Any] = {}
    ok = True
    for label in ("20:00", "22:15", "04:15"):
        part = scored.filter((pl.col("moment") == label) & (pl.col("c0") < outlook.C0_VALUES))
        found = {model: ece_of(part, model) for model in MODELS}
        lower = min(found["issued"][0], found["shipped"][0])
        here = found["s7f"][0] <= lower + 0.01
        detail[f"e_{label}"] = {
            "ece": {model: _r(value[0]) for model, value in found.items()},
            "ok": here,
            "reliability_s7f": [_bin(item) for item in found["s7f"][1]],
        }
        ok &= here
    every = scored.filter(pl.col("moment") == "20:00")
    all_s7f, bins = ece_of(every, "s7f")
    all_shipped, _ = ece_of(every, "shipped")
    every_ok = all_s7f <= all_shipped + 0.005
    detail["all_20:00"] = {
        "ece_s7f": _r(all_s7f),
        "ece_shipped": _r(all_shipped),
        "ok": every_ok,
        "reliability_s7f": [_bin(item) for item in bins],
    }
    return Gate("GF4", ok and every_ok, detail)


def _bin(item: backtest.Bin) -> dict[str, Any]:
    return {
        "bin": f"[{item.low:.1f}, {item.high:.1f})",
        "rows": item.rows,
        "mean_p": _r(item.mean_p),
        "observed": _r(item.observed),
        "se": _r(item.se),
        "clusters": item.clusters,
    }


def gf6(quiet: pl.DataFrame) -> Gate:
    """Quiet stays quiet (spec-f GF6): ``quiet`` holds per district and season the quiet
    20:00 cases (``n``) and each model's chance there."""
    detail: dict[str, Any] = {"cases": int(quiet["n"].sum()) if quiet.height else 0}
    ok = True
    n = quiet["n"].to_numpy().astype(np.float64)
    for base in ("issued", "shipped"):
        diff = (quiet["p_s7f"] - quiet[f"p_{base}"]).to_numpy().astype(np.float64)
        mean = float((diff * n).sum() / n.sum()) if n.sum() else math.nan
        order = np.argsort(diff)
        cumulative = np.cumsum(n[order]) / n.sum() if n.sum() else np.zeros(0)
        p99 = float(diff[order][np.searchsorted(cumulative, 0.99)]) if n.sum() else math.nan
        here = mean <= 0.005 and p99 <= 0.02  # noqa: PLR2004
        detail[f"vs_{base}"] = {"mean": _r(mean), "p99": _r(p99), "ok": here}
        ok &= here
    return Gate("GF6", ok, detail)


def gf7(scored: pl.DataFrame) -> Gate:
    """Other slots (spec-f GF7): E(t) at 10:15, 13:15, 16:15, pooled."""
    part = scored.filter(pl.col("moment").is_in(DAYTIME) & (pl.col("c0") < outlook.C0_VALUES))
    y = part["y"].to_numpy().astype(np.float64)
    found = {model: brier(part[f"p_{model}"].to_numpy().astype(np.float64), y) for model in MODELS}
    ok = found["s7f"] <= found["issued"] and found["s7f"] <= found["shipped"]
    worth = {f"vs_{base}": evidence(part, base) for base in ("issued", "shipped")}
    detail: dict[str, Any] = {
        "rows": part.height,
        "brier": {m: _r(v) for m, v in found.items()},
        "evidence": worth,
        "note": None,
    }
    if ok and not any(item["archive_evidence"] for item in worth.values()):
        detail["note"] = (
            "passes on the numbers, but the gain is no archive evidence (plan T4): "
            + "; ".join(f"{name} {item['verdict']}" for name, item in worth.items())
            + ". It cannot support the daytime heads-up option until live labels arrive "
            "(plan T5)."
        )
    return Gate("GF7", ok, detail)


def gf8(scored: pl.DataFrame, g1: backtest.Gates) -> Gate:
    """Morning-of (spec-f GF8): at 05:00 D, storm rows; and the amended G1 of the 05:00 rates."""
    part = scored.filter((pl.col("moment") == "05:00") & (pl.col("weather") > 0))
    y = part["y"].to_numpy().astype(np.float64)
    v3 = brier(part["p_issued"].to_numpy().astype(np.float64), y)
    piece1 = brier(part["p_shipped"].to_numpy().astype(np.float64), y)
    here = v3 <= piece1 + 0.002
    return Gate(
        "GF8",
        here and g1.g1,
        {
            "storm_rows": part.height,
            "brier_v3": _r(v3),
            "brier_piece1": _r(piece1),
            "ok": here,
            "g1_pooled": g1.g1_pooled,
            "g1_pooled_without_apart": g1.g1_pooled_without_apart,
            "g1_by_season": [
                {
                    "season": item.season,
                    "storm_rows": item.storm_rows,
                    "brier": _r(item.brier),
                    "brier_b0": _r(item.brier_b0),
                    "gated": item.gated,
                    "ok": item.ok,
                }
                for item in g1.g1_by_season
            ],
            "g1": g1.g1,
        },
    )


# --- GF5: T's own calibration -------------------------------------------------------------------


def _calibration_failing(
    table: pl.DataFrame, keys: Sequence[str], min_cases: int
) -> tuple[int, list[dict[str, Any]]]:
    pooled = (
        table.group_by(*keys)
        .agg(
            pl.col("cases").sum(),
            pl.col("sum_p").sum(),
            pl.col("sum_y").sum(),
            pl.col("cluster_ss").sum(),
        )
        .with_columns(
            (pl.col("sum_p") / pl.col("cases")).alias("mean_p"),
            (pl.col("sum_y") / pl.col("cases")).alias("observed"),
        )
        .sort(*keys)
    )
    failing: list[dict[str, Any]] = []
    checked = 0
    for row in pooled.iter_rows(named=True):
        if row["cases"] < min_cases:
            continue
        checked += 1
        se = math.sqrt(row["cluster_ss"]) / row["cases"]
        gap = abs(row["observed"] - row["mean_p"])
        if gap > max(0.03, 2 * se):
            failing.append(
                {
                    **{key: row[key] for key in keys},
                    "cases": int(row["cases"]),
                    "mean_p": _r(row["mean_p"]),
                    "observed": _r(row["observed"]),
                    "se": _r(se),
                }
            )
    return checked, failing


def gf5(calibration: pl.DataFrame, min_cases: int = 2000) -> Gate:
    """``T`` calibration on every test-season case (spec-f GF5): ``calibration`` holds per
    (slot, class, bin, month group) the cases, the summed T, the observed count and the sum of
    squares clustered by date x state (:func:`calibration_rows`); every (slot, class, bin) with
    ``min_cases`` or more within ``max(0.03, 2 SE)``. By month group it is reported."""
    checked, failing = _calibration_failing(calibration, ("slot", "target", "bin"), min_cases)
    by_month: dict[str, Any] = {}
    for (months,), part in sorted(calibration.group_by("months"), key=lambda x: str(x[0][0])):
        month_checked, month_failing = _calibration_failing(
            part, ("slot", "target", "bin"), min_cases
        )
        by_month[str(months)] = {
            "cases": int(part.filter(pl.col("target") == 0)["cases"].sum()),
            "bins_checked": month_checked,
            "bins_failing": len(month_failing),
        }
    return Gate(
        "GF5",
        not failing,
        {
            "bins_checked": checked,
            "bins_failing": len(failing),
            "failing": failing,
            "by_month_group": by_month,
        },
    )


MONTH_GROUP: Final = {8: "aug-oct", 9: "aug-oct", 10: "aug-oct", 11: "nov-dec", 12: "nov-dec",
                      1: "jan-feb", 2: "jan-feb", 3: "mar-jun", 4: "mar-jun", 5: "mar-jun",
                      6: "mar-jun"}  # fmt: skip


def calibration_rows(cases: pl.DataFrame, fitted: outlook.Outlook) -> pl.DataFrame:
    """One test season's cases (sample hours and late-in-slot moments, ``c0`` none or
    advisory) as T calibration sums per (slot, target class, bin, month group): cases, summed T,
    observed, and the clustered sum of squares by date x state."""
    slot_of = {k: moment.slot for k, moment in enumerate(MOMENTS)}
    index = {state: i for i, state in enumerate(outlook.STATES)}
    part = cases.filter(
        (pl.col("moment") != RECORD_INDEX)
        & (pl.col("c0") < outlook.C0_VALUES)
        & pl.col("state").is_in(list(outlook.STATES))
    ).with_columns(
        pl.col("moment").replace_strict(slot_of, return_dtype=pl.Int64).alias("slot"),
        pl.col("state").replace_strict(index, return_dtype=pl.Int64).alias("state_index"),
    )
    dist = fitted.distribution(
        part["slot"].to_numpy(),
        part["c0"].to_numpy().astype(np.int64),
        part["h"].to_numpy().astype(np.int64),
        part["f"].to_numpy().astype(np.int64),
        part["state_index"].to_numpy(),
    )
    target = part["target"].to_numpy().astype(np.int64)
    n = part["n"].to_numpy().astype(np.float64)
    months = [MONTH_GROUP.get(night.month, "other") for night in part["night"].to_list()]
    out: list[pl.DataFrame] = []
    for c in range(outlook.CLASSES):
        p = dist[:, c]
        hit = (target == c).astype(np.float64)
        frame = pl.DataFrame(
            {
                "slot": part["slot"],
                "target": np.full(part.height, c, dtype=np.int64),
                "bin": np.clip((p * 10).astype(np.int64), 0, 9),
                "months": months,
                "night": part["night"],
                "state": part["state"],
                "n": n,
                "p": p,
                "y": hit,
            }
        )
        # the bin's observed share, to centre each cluster's residual sum
        grouped = frame.group_by("slot", "target", "bin", "months", "night", "state").agg(
            pl.col("n").sum().alias("cases"),
            (pl.col("n") * pl.col("p")).sum().alias("sum_p"),
            (pl.col("n") * pl.col("y")).sum().alias("sum_y"),
        )
        totals = grouped.group_by("slot", "target", "bin").agg(
            (pl.col("sum_y").sum() / pl.col("cases").sum()).alias("rate")
        )
        out.append(
            grouped.join(totals, on=["slot", "target", "bin"])
            .group_by("slot", "target", "bin", "months")
            .agg(
                pl.col("cases").sum(),
                pl.col("sum_p").sum(),
                pl.col("sum_y").sum(),
                ((pl.col("sum_y") - pl.col("cases") * pl.col("rate")) ** 2)
                .sum()
                .alias("cluster_ss"),
            )
        )
    return pl.concat(out)


# --- the run ------------------------------------------------------------------------------------


def _codes(work_codes: Path, season: int, keys: pl.DataFrame) -> pl.DataFrame:
    path = work_codes / f"codes-{season}.parquet"
    if not path.is_file():
        return pl.DataFrame(
            schema={"district": pl.String, "night": pl.Date, "sample": pl.Int8, "code": pl.Int8}
        )
    codes = pl.read_parquet(path, columns=["district", "night", "sample", "code_filled"]).rename(
        {"code_filled": "code"}
    )
    return codes.join(keys.rename({"day": "night"}).unique(), on=["district", "night"], how="semi")


def quiet_rows(  # noqa: PLR0913, PLR0917 - the season's files, rates and outlook
    work_codes: Path,
    season: int,
    states: pl.DataFrame,
    places: pool.Places,
    fitted: outlook.Outlook,
    issued: Rates,
    shipped: Rates,
    settings: ModelSettings,
) -> pl.DataFrame:
    """Per district, its quiet 20:00 cases of ``season`` (no class, no heads-up, ``f`` quiet)
    and each model's chance on them (no day-after: these nights are unlabeled)."""
    path = work_codes / f"codes-{season}.parquet"
    k = INDEX_OF["20:00"]
    sample = MOMENTS[k].sample
    codes = pl.read_parquet(path, columns=["district", "night", "sample", "code_filled"])
    busy = states.filter((pl.col(f"w{k}") > 0) | (pl.col(f"h{k}") > 0)).select(
        "district", pl.col("day").alias("night")
    )
    quiet = (
        codes.filter((pl.col("sample") == sample) & (pl.col("code_filled") == 0))
        .join(busy, on=["district", "night"], how="anti")
        .group_by("district")
        .agg(pl.len().alias("n"))
        .filter(pl.col("district").is_in(list(places.districts)))
        .sort("district")
    )
    position = places.position()
    district = np.array([position[d] for d in quiet["district"].to_list()], dtype=np.int64)
    after = np.zeros(district.size, dtype=np.bool_)
    zeros = np.zeros(district.size, dtype=np.int64)
    state_index = {name: i for i, name in enumerate(outlook.STATES)}
    state = np.array(
        [
            state_index.get(places.states[i], -1) if i >= 0 else -1
            for i in places.state[district].tolist()
        ],
        dtype=np.int64,
    )
    dist = fitted.distribution(np.full(district.size, MOMENTS[k].slot), zeros, zeros, zeros, state)
    before = np.ones(district.size, dtype=np.bool_)
    found = {}
    for name, rates, use in (
        ("s7f", issued, dist),
        ("issued", issued, None),
        ("shipped", shipped, None),
    ):
        p_class = outlook.class_rates(rates.p, district, after)
        q_class = outlook.class_rates(rates.q, district, after)
        found[name] = outlook.chance(
            p_class, q_class, zeros, use, before,
            mode=outlook.OutlookMode.ON if use is not None else outlook.OutlookMode.OFF,
            floor=settings.floor, ceiling=settings.ceiling,
        ).p  # fmt: skip
    return quiet.with_columns(
        pl.lit(season).alias("season"),
        *[pl.Series(f"p_{name}", value) for name, value in found.items()],
    ).filter(pl.col("p_issued").is_not_nan() & pl.col("p_s7f").is_not_nan())


def fit_report(
    fitted: outlook.Outlook, case_seasons: Sequence[int], grid: Sequence[float]
) -> dict[str, Any]:
    """A fold's outlook fit: its training seasons, ``m``, whether ``m`` sits at an end of the
    grid (the leave-one-season-out loss wants more, or less, pooling than the grid allows),
    the cells backed off and every try's loss."""
    edges = (min(grid), max(grid))
    at_edge = [
        name
        for name, value in (("m_region", fitted.m_region), ("m_state", fitted.m_state))
        if len(case_seasons) >= 2 and value in edges  # noqa: PLR2004 - one season leaves none out
    ]
    return {
        "case_seasons": list(case_seasons),
        "m_region": fitted.m_region,
        "m_state": fitted.m_state,
        "grid": list(grid),
        "m_at_grid_edge": at_edge,
        "backed_off": backed_off(fitted),
        "loso_log_loss": [[m_r, m_s, round(loss, 7)] for m_r, m_s, loss in fitted.trials],
    }


def wide_report(
    sets: Mapping[str, pl.DataFrame], fits: Mapping[str, Any], calibration: pl.DataFrame
) -> dict[str, Any]:
    """The outlook on :data:`WIDE_GRID` (``m`` chosen on the training seasons only) beside the
    spec's grid, on each gate's rows, and its own calibration (GF5's bins)."""
    out: dict[str, Any] = {"folds": fits, "gf5": gf5(calibration).detail}
    out["gf5"].pop("failing", None)
    for name, part in sets.items():
        y = part["y"].to_numpy().astype(np.float64)
        out[name] = {
            "rows": part.height,
            **{
                f"brier_{model}": _r(brier(part[f"p_{model}"].to_numpy().astype(np.float64), y))
                for model in ("s7f", "s7fw", "issued", "shipped")
            },
            "evidence_vs_issued": evidence(part, "issued", "s7fw")["verdict"],
        }
    return out


def backed_off(fitted: outlook.Outlook) -> int:
    """Cells whose counted cell is wider than themselves."""
    found = 0
    for cell, like in enumerate(fitted.likes):
        _slot, _c0, heads, f = outlook.cell_parts(cell)
        found += like != outlook.Like(f, f, heads)
    return found


def _fold_rows(path: Path, places: pool.Places) -> tuple[pool.Rows, pool.Rows]:
    usable = pool.usable_labels(pl.read_parquet(path), places)
    return (
        pool.rows_from_labels(usable, places, "no_school"),
        pool.rows_from_labels(usable, places, "delay"),
    )


def recount(scored: pl.DataFrame) -> dict[str, Any]:
    """Step 0 (spec-f s. 13): E20 and E20-none, rows, dates and closings, by season."""
    e20 = scored.filter((pl.col("moment") == "20:00") & (pl.col("c0") < outlook.C0_VALUES))
    none = e20.filter((pl.col("c0") == 0) & (pl.col("h") == 0))
    advisory = e20.filter(pl.col("c0") == 1)

    def counts(part: pl.DataFrame) -> dict[str, Any]:
        return {
            "rows": part.height,
            "dates": part["day"].n_unique(),
            "closings": int(part["y"].sum()),
            "closing_dates": part.filter(pl.col("y") > 0)["day"].n_unique(),
            "by_season": {
                str(season): {"rows": g.height, "closings": int(g["y"].sum())}
                for (season,), g in sorted(part.group_by("season"), key=lambda x: int(x[0][0]))
            },
        }

    return {
        "e20": counts(e20),
        "e20_none": counts(none),
        "e20_heads_up_only": counts(e20.filter((pl.col("c0") == 0) & (pl.col("h") > 0))),
        "e20_advisory": counts(advisory),
    }


def named_dates(scored: pl.DataFrame) -> list[dict[str, Any]]:
    """GF10's report: on the five largest no-warning-yet dates, the share of closing rows at
    30% or more at 20:00 the night before, before (B-shipped) and after (S7-F)."""
    out: list[dict[str, Any]] = []
    at = scored.filter(pl.col("moment") == "20:00")
    for day in (*NAMED_DATES, *KC_DAYS):
        part = at.filter((pl.col("day") == day) & (pl.col("y") > 0))
        waiting = part.filter(pl.col("c0") < outlook.C0_VALUES)
        out.append(
            {
                "day": day.isoformat(),
                "closings": part.height,
                "no_warning_yet": waiting.height,
                "at_30_shipped": _r(_at(part["p_shipped"])),
                "at_30_s7f": _r(_at(part["p_s7f"])),
                "median_shipped": _r(_median(part["p_shipped"])),
                "median_s7f": _r(_median(part["p_s7f"])),
                "no_warning_yet_at_30_shipped": _r(_at(waiting["p_shipped"])),
                "no_warning_yet_at_30_s7f": _r(_at(waiting["p_s7f"])),
                "no_warning_yet_median_shipped": _r(_median(waiting["p_shipped"])),
                "no_warning_yet_median_s7f": _r(_median(waiting["p_s7f"])),
            }
        )
    return out


def coverage(scored: pl.DataFrame) -> dict[str, Any]:
    """Which rows each model could not publish (NaN: no rate under the class) and which S7-F
    gave the identity, by season and moment, over every row and over the E(t) rows (``c0``
    none or advisory); a row any model cannot publish is left out for every model, so the
    counts say what that leaves out and its outcomes."""
    nan = {model: pl.col(f"p_{model}").is_nan() for model in MODELS}
    dropped = pl.any_horizontal(list(nan.values()))

    def counts(part: pl.DataFrame) -> dict[str, Any]:
        out = part.select(
            pl.len().alias("rows"),
            *[expr.sum().alias(f"nan_{model}") for model, expr in nan.items()],
            dropped.sum().alias("left_out"),
            pl.col("y").filter(dropped).sum().cast(pl.Int64).alias("left_out_closings"),
            pl.col("fell_back").sum().alias("s7f_identity_no_rate"),
            pl.col("unknown_f").sum().alias("s7f_identity_unknown_forecast"),
        ).row(0, named=True)
        return {key: int(value or 0) for key, value in out.items()}

    def table(part: pl.DataFrame) -> dict[str, Any]:
        return {
            "all": counts(part),
            "by_season_moment": {
                f"{season}|{moment}": counts(group)
                for (season, moment), group in sorted(
                    part.group_by("season", "moment"), key=lambda x: (int(x[0][0]), str(x[0][1]))
                )
            },
        }

    return {
        "rows": table(scored),
        "e_rows": table(scored.filter(pl.col("c0") < outlook.C0_VALUES)),
    }


def run(  # noqa: PLR0913, PLR0915 - the files, the settings and every gate
    *,
    work: Path,
    labels_dir: Path,
    shipped_dir: Path,
    directory: Path,
    out: Path,
    config: PredictConfig,
    draws: int,
    work_codes: Path | None = None,
    fold_labels: Path | None = None,
    wide_grid: bool = True,
    say: Callable[[str], None] = print,
) -> int:  # pragma: no cover - the real labels, states and cases
    """The walk-forward backtest and report (``metrics.json``, ``report.md`` in ``out``).

    ``fold_labels``: a folder of each test season's training labels (``labels-<S>.parquet``
    for the 05:00 labels, ``shipped-<S>.parquet`` for the 21:00 ones), made with the station
    audiences and gates of the seasons before ``S`` only (calc-research plan T1); the rates of
    fold ``S`` are then fit on them, and the test rows stay the whole archive's labels."""
    from snowlight.predict.outlook_cli import NDFD_DISTRICTS, season_cases_frame  # noqa: PLC0415

    codes_dir = work_codes or NDFD_DISTRICTS
    settings = config.model
    labels05 = pl.read_parquet(labels_dir / "labels.parquet")
    labels21 = pl.read_parquet(shipped_dir / "labels.parquet")
    table = pl.read_parquet(labels_dir / "districts.parquet")
    schools = pl.read_parquet(directory / "schools.parquet")
    places = train.training_places(table, schools, config.serve.neighbor_miles)
    usable05 = pool.usable_labels(labels05, places)
    usable21 = pool.usable_labels(labels21, places)
    reasons_path = labels_dir / "reasons.parquet"
    reasons = (
        pl.read_parquet(reasons_path)
        if reasons_path.is_file()
        else pl.DataFrame(schema={"district": pl.String, "day": pl.Date, "named_share": pl.Float64})
    )
    usable05 = usable05.join(reasons, on=["district", "day"], how="left").with_columns(
        pl.col("named_share").fill_null(0.0).alias("named")
    )
    rows05 = pool.rows_from_labels(usable05, places, "no_school")
    delay05 = pool.rows_from_labels(usable05, places, "delay")
    rows21 = pool.rows_from_labels(usable21, places, "no_school")
    delay21 = pool.rows_from_labels(usable21, places, "delay")
    cases = season_cases_frame(work)
    train_cases = outlook.training_cases(cases)
    seasons05 = sorted(set(rows05.season.tolist()))
    seasons21 = sorted(set(rows21.season.tolist()))
    parts: list[pl.DataFrame] = []
    quiet_parts: list[pl.DataFrame] = []
    calibration: list[pl.DataFrame] = []
    calibration_wide: list[pl.DataFrame] = []
    fits: dict[str, Any] = {}
    wide_fits: dict[str, Any] = {}
    for season in config.backtest.test_seasons:
        test = usable05.filter(pl.col("season") == season)
        case_seasons = list(range(FIRST_CASE_SEASON, season))
        if not test.height or not case_seasons:
            continue
        fitted = outlook.fit(train_cases, case_seasons)
        wide = outlook.fit(train_cases, case_seasons, WIDE_GRID) if wide_grid else None
        fits[str(season)] = fit_report(fitted, case_seasons, outlook.GRID)
        if wide is not None:
            wide_fits[str(season)] = fit_report(wide, case_seasons, WIDE_GRID)
        fit05 = (rows05, delay05)
        fit21 = (rows21, delay21)
        if fold_labels is not None:
            fit05 = _fold_rows(fold_labels / f"labels-{season}.parquet", places)
            fit21 = _fold_rows(fold_labels / f"shipped-{season}.parquet", places)
        before05 = [s for s in seasons05 if s < season]
        issued = full_rates(*fit05, places, before05, settings)
        shipped = full_rates(*fit21, places, [s for s in seasons21 if s < season], settings)
        trained = fit05[0].subset(np.isin(fit05[0].season, np.array(before05)))
        states = pl.read_parquet(work / f"states-{season}.parquet")
        codes = _codes(codes_dir, season, test.select("district", "day"))
        found = score_fold(test, places, states, codes, fitted, issued, shipped, settings, wide)
        b0, b1 = backtest.baselines(
            trained, pool.rows_from_labels(test, places, "no_school"), places
        )
        repeat = len(SCORED)
        found = found.with_columns(
            pl.Series("b0", np.tile(b0, repeat)), pl.Series("b1", np.tile(b1, repeat))
        )
        parts.append(found)
        quiet_parts.append(
            quiet_rows(codes_dir, season, states, places, fitted, issued, shipped, settings)
        )
        season_cases = cases.filter(pl.col("season") == season)
        calibration.append(calibration_rows(season_cases, fitted))
        if wide is not None:
            calibration_wide.append(calibration_rows(season_cases, wide))
        say(
            f"fold {season}: {test.height} rows, T on {case_seasons}, m {fitted.m_region:g}"
            + (f" (wide grid {wide.m_region:g}/{wide.m_state:g})" if wide is not None else "")
        )
    scored_all = pl.concat(parts)
    covered = coverage(scored_all)
    nan_rows = covered["rows"]["all"]["left_out"]
    scored = scored_all.filter(pl.all_horizontal([pl.col(f"p_{m}").is_not_nan() for m in MODELS]))
    share = config.labels.no_school_share
    record = scored.filter(pl.col("moment") == "05:00").with_columns(pl.col("p_issued").alias("p"))
    g1 = backtest.gates(
        record,
        [],
        config.backtest.apart,
        config.backtest.reliability_min_rows,
        g1_min_storm_rows=config.backtest.g1_min_storm_rows,
        g1_tolerance=config.backtest.g1_tolerance,
    )
    gates = [
        gf1(scored, draws, share),
        gf2(scored),
        gf3(scored, share),
        gf4(scored),
        gf5(pl.concat(calibration)),
        gf6(pl.concat(quiet_parts)),
        gf7(scored),
        gf8(scored, g1),
    ]
    e20 = scored.filter((pl.col("moment") == "20:00") & (pl.col("c0") < outlook.C0_VALUES))
    sets = gate_rows(scored)
    metrics: dict[str, Any] = {
        "labels_rule": "per fold: each fold's training labels made from the seasons before it "
        "(plan T1; the primary run)"
        if fold_labels is not None
        else "whole archive (plan T1 leak: training labels depend on later seasons; "
        "comparison only)",
        "folds": fits,
        "rows_left_out_unpublishable": nan_rows,
        "coverage": covered,
        "recount": recount(scored),
        "gates": {gate.name: gate.as_json() for gate in gates},
        "gate_rows": {name: diagnostics(part) for name, part in sets.items()},
        "by_moment": {
            label: model_metrics(
                scored.filter((pl.col("moment") == label) & (pl.col("c0") < outlook.C0_VALUES))
            )
            for label in SCORED
        },
        "named_dates": named_dates(scored),
        "delay_e20": {
            model: _r(
                brier(
                    e20[f"d_{model}"].to_numpy().astype(np.float64),
                    e20["y_delay"].to_numpy().astype(np.float64),
                )
            )
            for model in MODELS
        },
    }
    if wide_grid:
        metrics["wide_grid"] = wide_report(sets, wide_fits, pl.concat(calibration_wide))
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "metrics.json", json.loads(json.dumps(metrics, default=str)))
    scored.write_parquet(out / "scored.parquet")
    (out / "report.md").write_text(report_markdown(metrics), encoding="utf-8")
    for gate in gates:
        say(f"{gate.name}: {'pass' if gate.passed else 'FAIL'}")
    return 0


def failing_cells(detail: Mapping[str, Any], path: str = "") -> list[str]:
    """Every ``ok``-like flag of a gate's detail that is false, by its path."""
    found: list[str] = []
    for key, value in detail.items():
        where = f"{path}.{key}" if path else key
        if isinstance(value, Mapping):
            found += failing_cells(value, where)
        elif value is False and (key in {"ok", "log_loss_lower", "g1"} or key.endswith("_ok")):
            found.append(where)
    return found


def _num(value: object, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:g}" if value.is_integer() and abs(value) >= 1 else f"{value:.{digits}f}"
    return str(value)


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_num(cell) for cell in row) + " |" for row in rows]
    return lines


def _notes(gate: Mapping[str, Any]) -> list[str]:
    notes: list[str] = []
    for key, value in gate.items():
        if isinstance(value, Mapping):
            notes += _notes(value)
        elif key in {"note", "seasons_note"} and value:
            notes.append(str(value))
    return sorted(set(notes))


def report_markdown(metrics: Mapping[str, Any]) -> str:
    """The report for the lead (internal)."""
    sets: Mapping[str, Any] = metrics["gate_rows"]
    lines = [
        "# S7-F F2 walk-forward backtest (internal)",
        "",
        f"Training labels: {metrics.get('labels_rule', 'whole archive')}. Test labels: the 05:00 "
        "record (rule D2, D3). Archive labels are storm-biased: this backtest can veto an idea "
        "that hurts, not prove one helps (plan T4). A gain that raised chances account for is "
        "no archive evidence.",
        "",
        "## Gates",
        "",
    ]
    rows: list[list[object]] = []
    for name, gate in metrics["gates"].items():
        names = [key for key, gates in GATE_SETS.items() if name in gates]
        verdicts = [
            f"{key}: {sets[key]['evidence']['vs_issued']['verdict']} / "
            f"{sets[key]['evidence']['vs_shipped']['verdict']}"
            for key in names
        ]
        rows.append(
            [
                name,
                "pass" if gate["passed"] else "FAIL",
                ", ".join(failing_cells(gate)) or "-",
                "; ".join(verdicts) or "no labeled rows to split",
            ]
        )
    lines += _table(["gate", "result", "failing cells", "evidence vs B-issued / B-shipped"], rows)
    lines += ["", "Notes:", ""]
    for name, gate in metrics["gates"].items():
        lines += [f"- {name}: {note}" for note in _notes(gate)]
    lines += ["", "## Each gate's rows: raised vs lowered (SSE saved, + is S7-F better)", ""]
    rows = []
    for key, item in sets.items():
        rows.extend(
            [
                key,
                base,
                item["rows"],
                item["dates"],
                item["closings"],
                item["s7f"]["brier"],
                item[base]["brier"],
                item["evidence"][f"vs_{base}"]["raised"],
                item["evidence"][f"vs_{base}"]["raised_on_alert_days"],
                item["evidence"][f"vs_{base}"]["lowered"],
                ", ".join(
                    f"{d['day']} {d['sse_saved']:+.1f}"
                    for d in item["evidence"][f"vs_{base}"]["dates_carrying_the_gain"]
                )
                or "-",
            ]
            for base in ("issued", "shipped")
        )
    lines += _table(
        [
            "rows", "vs", "n", "dates", "closings", "Brier S7-F", "Brier base", "raised",
            "raised on alert days", "lowered", "dates carrying the gain",
        ],
        rows,
    )  # fmt: skip
    lines += ["", "## Strata flagged (S7-F worse by more than 0.01 on 30+ rows, 2+ dates)", ""]
    rows = [
        [key, kind, cell["class"], cell.get("size", cell.get("c0_class")), cell["rows"],
         cell["dates"], cell["closings"], cell["s7f"]["brier"], cell["issued"]["brier"],
         cell["shipped"]["brier"], ", ".join(cell["flag_worse_than"])]
        for key, item in sets.items()
        for kind in ("strata_size", "strata_c0")
        for cell in item[kind]
        if cell["flag_worse_than"]
    ]  # fmt: skip
    lines += _table(
        ["rows", "strata", "05:00 class", "within", "n", "dates", "closings", "S7-F",
         "B-issued", "B-shipped", "worse than"],
        rows,
    ) if rows else ["none"]  # fmt: skip
    lines += ["", "## Level-free Brier and within-day ranking", ""]
    rows = [
        [key, *[item["level_free"][m] for m in MODELS],
         item["ranking"]["other"]["market_days"],
         *[item["ranking"]["other"][m] for m in MODELS],
         item["ranking"]["split"]["market_days"],
         *[item["ranking"]["split"][m] for m in MODELS]]
        for key, item in sets.items()
    ]  # fmt: skip
    lines += _table(
        ["rows", "level-free S7-F", "B-issued", "B-shipped", "market-days", "rank S7-F",
         "B-issued", "B-shipped", "split days (in sample)", "S7-F", "B-issued", "B-shipped"],
        rows,
    )  # fmt: skip
    lines += ["", "## Coverage: rows a model cannot publish, by season (E(t) rows)", ""]
    by_season: dict[str, dict[str, int]] = {}
    for key, item in metrics["coverage"]["e_rows"]["by_season_moment"].items():
        season = key.split("|")[0]
        total = by_season.setdefault(season, dict.fromkeys(item, 0))
        for name, value in item.items():
            total[name] += value
    columns = list(metrics["coverage"]["e_rows"]["all"])
    lines += _table(
        ["season", *columns],
        [[season, *[item[c] for c in columns]] for season, item in sorted(by_season.items())]
        + [["all", *[metrics["coverage"]["e_rows"]["all"][c] for c in columns]]],
    )
    lines += [
        "",
        "Per moment: metrics.json coverage.*.by_season_moment. A row any model cannot publish "
        "is left out for every model; S7-F gives the identity (today's chance) where T weighs a "
        "class with no rate or the forecast is unknown.",
        "",
        "## Outlook fits (m by leave-one-season-out log loss)",
        "",
    ]
    rows = []
    for season, fit in metrics["folds"].items():
        trials = sorted(fit["loso_log_loss"], key=lambda item: item[2])[:3]
        rows.append(
            [season, len(fit["case_seasons"]), fit["m_region"], fit["m_state"],
             ", ".join(fit["m_at_grid_edge"]) or "-", fit["backed_off"],
             "; ".join(f"{a:g}/{b:g} {c:.6f}" for a, b, c in trials) or "-"]
        )  # fmt: skip
    lines += _table(
        ["fold", "case seasons", "m_region", "m_state", "at grid edge", "cells backed off",
         "best 3 (m_region/m_state loss)"],
        rows,
    )  # fmt: skip
    wide = metrics.get("wide_grid")
    if wide:
        lines += ["", "## Wider grid for m (chosen on training seasons only; a diagnostic)", ""]
        lines += _table(
            ["fold", "m_region", "m_state", "at grid edge"],
            [
                [season, fit["m_region"], fit["m_state"], ", ".join(fit["m_at_grid_edge"]) or "-"]
                for season, fit in wide["folds"].items()
            ],
        )
        lines += [""]
        lines += _table(
            ["rows", "n", "Brier S7-F", "S7-F wide", "B-issued", "B-shipped", "wide vs B-issued"],
            [
                [key, item["rows"], item["brier_s7f"], item["brier_s7fw"], item["brier_issued"],
                 item["brier_shipped"], item["evidence_vs_issued"]]
                for key, item in wide.items()
                if key in sets
            ],
        )  # fmt: skip
        lines += [
            "",
            f"GF5 with the wider grid: {wide['gf5']['bins_failing']} of "
            f"{wide['gf5']['bins_checked']} bins failing (spec grid: "
            f"{metrics['gates']['GF5']['bins_failing']} of "
            f"{metrics['gates']['GF5']['bins_checked']}).",
        ]
    lines += ["", "## GF10 named dates (20:00 the night before; closings)", ""]
    lines += _table(
        ["day", "closings", "at 30% shipped", "at 30% S7-F", "median shipped", "median S7-F",
         "no warning yet", "at 30% shipped", "at 30% S7-F", "median shipped", "median S7-F"],
        [
            [d["day"], d["closings"], d["at_30_shipped"], d["at_30_s7f"], d["median_shipped"],
             d["median_s7f"], d["no_warning_yet"], d["no_warning_yet_at_30_shipped"],
             d["no_warning_yet_at_30_s7f"], d["no_warning_yet_median_shipped"],
             d["no_warning_yet_median_s7f"]]
            for d in metrics["named_dates"]
        ],
    )  # fmt: skip
    for key, item in sets.items():
        lines += ["", f"## Gain by date: {key} (SSE saved, + is S7-F better)", ""]
        lines += _table(
            ["day", "rows", "closings", "vs B-issued", "vs B-shipped", "split day"],
            [
                [d["day"], d["rows"], d["closings"], d["sse_saved_vs_issued"],
                 d["sse_saved_vs_shipped"], "yes" if d["split"] else ""]
                for d in item["by_date"]
            ],
        )  # fmt: skip
    lines += ["", "## Recount (step 0)", "", "```", json.dumps(metrics["recount"], indent=1), "```"]
    lines += ["", "## Gate detail", "", "```", json.dumps(metrics["gates"], indent=1), "```"]
    for key in ("by_moment", "named_dates", "delay_e20"):
        lines += ["", f"## {key}", "", "```", json.dumps(metrics[key], indent=1), "```"]
    return "\n".join(lines) + "\n"
