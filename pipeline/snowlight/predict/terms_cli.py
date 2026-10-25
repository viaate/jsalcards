"""``snowlight predict terms``: backtest v2 and the reasons' fit (S7 spec, piece 3).

Reads the labels folder (``predict labels``: ``labels.parquet``, ``posts.parquet``,
``snapshots.parquet``), the forecast history's code files (the artifact of the history
workflow, downloaded to ``.cache/predict/ndfd-districts``) and the committed model. Writes the
internal report (``backtest/terms/report.md`` and ``metrics.json`` in the labels folder) and,
unless ``--report-only``, the committed terms (``data/predict/terms.json.gz``): the terms fit
on every season's rows, each with its walk-forward base, the usual posting times, and the gate
as judged here (passed or not, the gain and the report's SHA-256). A failing fit is still
written, so the report and the owner's tables read it, but serving refuses it without the
lead's override.
"""

import argparse
import dataclasses
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.output import write_json
from snowlight.predict import announce, backtest_terms, pool, term_rows, terms_file, train
from snowlight.predict import artifact as artifact_module
from snowlight.predict.backtest import FoldRows
from snowlight.predict.config import PIPELINE_ROOT, PredictConfig
from snowlight.predict.geography import REGION_OF
from snowlight.predict.terms import Model, Term, contributions, fit

CODES: Final = PIPELINE_ROOT / ".cache" / "predict" / "ndfd-districts"


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``predict terms``."""
    parser = actions.add_parser("terms", help="backtest v2 and the reasons' fit")
    parser.add_argument("--work", type=Path, default=train.DEFAULT_OUT, help="labels folder")
    parser.add_argument("--directory", type=Path, default=train.TrainPaths().directory)
    parser.add_argument("--codes", type=Path, default=CODES, help="forecast history code files")
    parser.add_argument("--model", type=Path, default=artifact_module.ARTIFACT_PATH)
    parser.add_argument("--out", type=Path, default=terms_file.TERMS_PATH)
    parser.add_argument("--report-only", action="store_true", help="write no terms file")
    parser.add_argument(
        "--drop-training-dates",
        action="store_true",
        help="also refit without each of the busiest training dates (P8; slow)",
    )
    from snowlight.predict.cli import labels_rule_options  # noqa: PLC0415

    labels_rule_options(parser)
    parser.set_defaults(handler=run_terms)


SERVED_FIT_RULE: Final = "whole"
"""The training labels of the served terms fit's walk-forward bases: every season's rows over
the labels a pass would have had (all of them past at serve time)."""


def terms_write_refusal(labels_rule: str, *, report_only: bool) -> str | None:
    """Why ``predict terms`` must not write a terms file, or ``None``: the gate it records
    must be judged on the training labels the served fit uses (:data:`SERVED_FIT_RULE`), so a
    gate judged under another rule never stands for that fit. The lead decides any change."""
    if report_only or labels_rule == SERVED_FIT_RULE:
        return None
    return (
        f"a terms file records the gate of its own fit, whose bases use the {SERVED_FIT_RULE} "
        f"rule; this run judges the gate under the {labels_rule} rule: run with --report-only, "
        f"or with --labels-rule {SERVED_FIT_RULE} to write the file"
    )


def run_terms(args: argparse.Namespace) -> int:  # pragma: no cover - the real labels
    """Run ``predict terms``."""
    refusal = terms_write_refusal(args.labels_rule, report_only=args.report_only)
    if refusal is not None:
        print(f"predict terms: {refusal}", file=sys.stderr)  # noqa: T201
        return 2
    config = PredictConfig.load(args.config)
    labels = pl.read_parquet(args.work / "labels.parquet")
    table = pl.read_parquet(args.work / "districts.parquet")
    schools = pl.read_parquet(args.directory / "schools.parquet")
    places = train.training_places(table, schools, config.serve.neighbor_miles)
    usable = pool.usable_labels(labels, places)
    rows = pool.rows_from_labels(usable, places, "no_school")
    delay_rows = pool.rows_from_labels(usable, places, "delay")
    posts = pl.read_parquet(args.work / "posts.parquet")
    codes = term_rows.forecast_codes(args.codes)
    levels = term_rows.term_levels(
        usable,
        codes,
        pl.read_parquet(args.work / "snapshots.parquet"),
        posts,
        term_rows.training_neighbors(table, schools, config.serve.neighbor_miles),
    )
    neighbors = term_rows.training_neighbors(table, schools, config.serve.neighbor_miles)
    snapshots = pl.read_parquet(args.work / "snapshots.parquet")
    whole_base = backtest_terms.base_by_season(rows, delay_rows, places, config.model)
    from snowlight.predict.cli import fold_set  # noqa: PLC0415

    fold = fold_set(args, sorted(set(rows.season.tolist()))[1:], places)
    per_fold = (
        None
        if fold is None
        else FoldTerms(
            fold,
            {
                season: term_rows.term_levels(frame, codes, snapshots, posts, neighbors)
                for season, frame in fold.usable.items()
            },
        )
    )
    base, folds, moved = _walk(per_fold, rows, whole_base, levels, places, config)
    clusters = list(zip(usable["day"].to_list(), usable["cluster"].to_list(), strict=True))
    judged, bins = backtest_terms.judge(
        folds,
        rows,
        clusters,
        backtest_terms.neighbor_mask(levels),
        bins=config.backtest.reliability_bins,
        min_rows=config.backtest.reliability_min_rows,
        apart=config.backtest.apart,
        min_storm_rows=config.backtest.g1_min_storm_rows,
        test_seasons=config.backtest.test_seasons,
    )
    advisory = backtest_terms.advisory_table(folds, rows, base, levels[Term.SNOW_ADVISORY])
    # The served fit: every season's rows, each on its walk-forward base over the labels a pass
    # would have had (all of them past at serve time), as before the per-fold rule.
    has_base = ~np.isnan(whole_base.p) & (whole_base.counted >= 0)
    final = fit(backtest_terms.design_of(whole_base, rows, levels, has_base), rows.season[has_base])
    evidence = backtest_terms.advisory_evidence(folds, rows, base, levels, final)
    zone_of = {d: z for d, z in zip(table["district"], table["time_zone"], strict=True) if z}
    usual = announce.usual_minutes(
        (
            (unit, day, at)
            for unit, day, at in posts.select("unit", "day", "posted_at").iter_rows()
            if at is not None and unit in zone_of
        ),
        zone_of,
        config.labels.read_until,
    )
    out = args.work / "backtest" / "terms"
    out.mkdir(parents=True, exist_ok=True)
    markdown = backtest_terms.report_markdown(judged, folds, advisory, final, len(usual), evidence)
    markdown = labels_rule_note(markdown, per_fold=per_fold is not None)
    (out / "report.md").write_text(markdown, encoding="utf-8")
    gate = terms_file.GateRecord(
        passed=judged.passed,
        gain=round(judged.gain, 6),
        report_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        labels_rule="whole" if per_fold is None else "fold",
    )
    from snowlight.predict.cli import json_safe  # noqa: PLC0415

    metrics = {
        "gates": dataclasses.asdict(judged) | {"gain": judged.gain, "passed": judged.passed},
        "advisory": advisory,
        "advisory_evidence": dataclasses.asdict(evidence),
        "bins": [dataclasses.asdict(item) for item in bins],
        "labels_rule": "whole" if per_fold is None else "fold",
    }
    write_json(out / "metrics.json", json_safe(json.loads(json.dumps(metrics, default=str))))
    write_checks(
        args,
        out,
        folds,
        rows,
        delay_rows,
        usable,
        levels,
        places,
        table,
        codes,
        final,
        per_fold,
        moved,
    )
    print(markdown.splitlines()[2])  # noqa: T201
    if args.report_only:
        return 0
    found = terms_file.TermsArtifact(
        schema_version=1,
        model_sha256=artifact_module.sha256_of(Path(args.model).read_bytes()),
        seasons=tuple(sorted(set(rows.season[has_base].tolist()))),
        rows=int(has_base.sum()),
        penalty=final.penalty,
        terms={term.value: terms_file.entry_of(item) for term, item in final.fits.items()},
        announce=usual,
        gate=gate,
    )
    size = found.write(args.out)
    print(f"terms: {args.out} ({size:,} bytes)")  # noqa: T201
    return 0


def _walk(  # noqa: PLR0913, PLR0917 - the rule's folds, the rows, their base, levels, places, settings
    per_fold: "FoldTerms | None",
    rows: pool.Rows,
    whole_base: backtest_terms.Base,
    levels: dict[Term, npt.NDArray[np.int64]],
    places: pool.Places,
    config: PredictConfig,
) -> tuple[backtest_terms.Base, list[backtest_terms.TermFold], list[int] | None]:
    """Backtest v2's walk-forward under the run's rule: every row's base, the folds, and under
    the per-fold rule P8's busiest dates of its own fold fits (``None`` under the whole rule)."""
    if per_fold is None:
        folds = backtest_terms.walk_forward(
            rows, whole_base, levels, config.backtest.test_seasons, config.model
        )
        return whole_base, folds, None
    found = per_fold.fit(rows, levels, places, config)
    return found.base, found.folds, per_fold.moved_dates(found)


def write_checks(  # noqa: PLR0913, PLR0917 - the run's rows, fit and inputs
    args: argparse.Namespace,
    out: Path,
    folds: list[backtest_terms.TermFold],
    rows: pool.Rows,
    delay_rows: pool.Rows,
    usable: pl.DataFrame,
    levels: dict[Term, npt.NDArray[np.int64]],
    places: pool.Places,
    table: pl.DataFrame,
    codes: pl.DataFrame,
    final: Model,
    per_fold: "FoldTerms | None" = None,
    moved_dates: Sequence[int] | None = None,
) -> None:  # pragma: no cover - the real labels
    """The report-only checks of the terms against the base (calc-research plan T3, T4):
    ``checks.md`` and ``checks.json`` beside the report (no gate and no terms file read them).
    With ``--drop-training-dates``, P8 refits without 2016-02-16 and each of the 3 training
    dates with the most rows the terms move: under the per-fold rule ``moved_dates``, those the
    candidate's own fold fits move in their fold labels (:meth:`FoldTerms.moved_dates`);
    under the whole rule those the served terms move."""
    config = PredictConfig.load(args.config)
    day = np.array([d.toordinal() for d in usable["day"].to_list()], dtype=np.int64)
    market = [str(c) for c in usable["cluster"].to_list()]
    code_of = {
        (district, night): int(code)
        for district, night, code in codes.select("district", "day", "code").iter_rows()
        if code is not None
    }
    code = np.array(
        [code_of.get(key, -1) for key in usable.select("district", "day").iter_rows()],
        dtype=np.int64,
    )
    state_of = dict(zip(table["district"], table["state"], strict=True))
    northeast = np.array(
        [REGION_OF.get(state_of.get(d) or "") == "northeast" for d in usable["district"]],
        dtype=np.bool_,
    )
    scored = backtest_terms.scored_from_folds(folds, rows, day, market, code, northeast)
    dropped = None
    if args.drop_training_dates:
        if per_fold is not None:
            if moved_dates is None:
                raise ValueError("the per-fold rule picks P8's dates from its own fold fits")
            dates = p8_dates(moved_dates)
        else:
            moved = np.zeros(len(rows), dtype=np.bool_)
            base = backtest_terms.base_by_season(rows, delay_rows, places, config.model)
            everything = ~np.isnan(base.p) & (base.counted >= 0)
            values = contributions(final, backtest_terms.design_of(base, rows, levels, everything))
            for value in values.values():
                moved[np.flatnonzero(everything)[value != 0]] = True
            training = rows.season < max(config.backtest.test_seasons)
            dates = p8_dates(backtest_terms.busiest_dates(day, moved & everything & training))
        delay_day = np.array(
            [
                d.toordinal()
                for d, outcome in usable.select("day", "outcome").iter_rows()
                if outcome != "no_school"
            ],
            dtype=np.int64,
        )

        def score(exclude: npt.NDArray[np.bool_] | None) -> tuple[float, float]:
            if exclude is None:
                return backtest_terms.storm_briers(scored)
            left = day[exclude][0]
            if per_fold is not None:
                _base, refit = per_fold.without(left).walk_forward(rows, levels, places, config)
                again = backtest_terms.scored_from_folds(refit, rows, day, market, code, northeast)
                return backtest_terms.storm_briers(again)
            mine = backtest_terms.base_by_season(
                rows, delay_rows, places, config.model, exclude=(exclude, delay_day == left)
            )
            refit = backtest_terms.walk_forward(
                rows, mine, levels, config.backtest.test_seasons, config.model, exclude=exclude
            )
            again = backtest_terms.scored_from_folds(refit, rows, day, market, code, northeast)
            return backtest_terms.storm_briers(again)

        dropped = backtest_terms.drop_training_dates(score, day, dates)
    checks = backtest_terms.run_checks(
        scored, apart=backtest_terms.split_market_days(), drop_training=dropped
    )
    (out / "checks.md").write_text(
        backtest_terms.checks_markdown(checks, "Backtest v2 checks: the terms against the base"),
        encoding="utf-8",
    )
    from snowlight.predict.cli import json_safe  # noqa: PLC0415

    write_json(
        out / "checks.json",
        json_safe(json.loads(json.dumps(dataclasses.asdict(checks) | {"harm": checks.harm}))),
    )


@dataclass(frozen=True, slots=True)
class FoldTerms:
    """Backtest v2 under the per-fold rule: the fold label files and their rows' levels."""

    fold: train.FoldSet
    levels: dict[int, dict[Term, npt.NDArray[np.int64]]]
    """Season to its fold labels' levels, in the order of ``fold.usable``."""

    def walk_forward(
        self,
        rows: pool.Rows,
        levels: dict[Term, npt.NDArray[np.int64]],
        places: pool.Places,
        config: PredictConfig,
    ) -> tuple[backtest_terms.Base, list[backtest_terms.TermFold]]:
        """Every row of ``rows`` (the test rows: the whole archive's labels, ``levels`` theirs)
        gets its base fit on its season's fold labels, and every test season's terms are fit
        on its fold labels' rows with their own bases."""
        found = self.fit(rows, levels, places, config)
        return found.base, found.folds

    def fit(
        self,
        rows: pool.Rows,
        levels: dict[Term, npt.NDArray[np.int64]],
        places: pool.Places,
        config: PredictConfig,
    ) -> "FoldFit":
        """:meth:`walk_forward` with each test season's term training kept."""
        fits: dict[int, backtest_terms.Predictor] = {}
        training = self.fold.training
        base = backtest_terms.base_by_season(
            rows, _no_rows(rows), places, config.model, training=training, fits=fits
        )
        seasons = config.backtest.test_seasons
        terms = backtest_terms.term_training(
            training, self.levels, places, config.model, seasons, fits=fits
        )
        folds = backtest_terms.walk_forward(
            rows, base, levels, seasons, config.model, training=terms
        )
        return FoldFit(base, folds, terms)

    def moved_dates(self, found: "FoldFit", count: int = 3) -> list[int]:
        """P8's busiest training dates under the per-fold rule: those with the most rows the
        candidate's own fold fits move (:func:`backtest_terms.fold_moved_dates`)."""
        days = {season: self.fold.days(season)[0] for season in found.training}
        return backtest_terms.fold_moved_dates(found.folds, found.training, days, count)

    def without(self, day: int) -> "FoldTerms":
        """The same folds with every row of ``day`` (an ordinal) left out (plan P8)."""
        usable: dict[int, pl.DataFrame] = {}
        training: dict[int, FoldRows] = {}
        levels: dict[int, dict[Term, npt.NDArray[np.int64]]] = {}
        for season, frame in self.fold.usable.items():
            days, delay_days = self.fold.days(season)
            keep = days != day
            usable[season] = frame.filter(pl.Series(keep))
            training[season] = self.fold.training[season].without(keep, delay_days != day)
            levels[season] = {term: level[keep] for term, level in self.levels[season].items()}
        return FoldTerms(train.FoldSet(usable, training), levels)


@dataclass(frozen=True, slots=True)
class FoldFit:
    """Backtest v2 under the per-fold rule: every row's base, the folds and their training."""

    base: backtest_terms.Base
    folds: list[backtest_terms.TermFold]
    training: dict[int, backtest_terms.TermTraining]


def p8_dates(moved: Sequence[int]) -> list[int]:
    """P8's dates: 2016-02-16 (the plan's named date), then the busiest of ``moved``."""
    dates = [date(2016, 2, 16).toordinal()]
    return dates + [d for d in moved if d not in dates]


def _no_rows(rows: pool.Rows) -> pool.Rows:
    """No rows (the per-fold rule reads every fit's delay rows from the fold labels)."""
    return rows.subset(np.zeros(len(rows), dtype=np.bool_))


def labels_rule_note(markdown: str, *, per_fold: bool) -> str:
    """``markdown`` with the training labels' rule after its gate line."""
    from snowlight.predict.backtest import PER_FOLD_NOTE, WHOLE_NOTE  # noqa: PLC0415

    lines = markdown.splitlines()
    lines[3:3] = ["", PER_FOLD_NOTE if per_fold else WHOLE_NOTE]
    return "\n".join(lines) + "\n"
