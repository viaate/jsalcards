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
from pathlib import Path
from typing import Final

import numpy as np
import polars as pl

from snowlight.output import write_json
from snowlight.predict import announce, backtest_terms, pool, term_rows, terms_file, train
from snowlight.predict import artifact as artifact_module
from snowlight.predict.config import PIPELINE_ROOT, PredictConfig
from snowlight.predict.terms import Term, fit

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
    parser.set_defaults(handler=run_terms)


def run_terms(args: argparse.Namespace) -> int:  # pragma: no cover - the real labels
    """Run ``predict terms``."""
    config = PredictConfig.load(args.config)
    labels = pl.read_parquet(args.work / "labels.parquet")
    table = pl.read_parquet(args.work / "districts.parquet")
    schools = pl.read_parquet(args.directory / "schools.parquet")
    places = train.training_places(table, schools, config.serve.neighbor_miles)
    usable = pool.usable_labels(labels, places)
    rows = pool.rows_from_labels(usable, places, "no_school")
    delay_rows = pool.rows_from_labels(usable, places, "delay")
    posts = pl.read_parquet(args.work / "posts.parquet")
    levels = term_rows.term_levels(
        usable,
        term_rows.forecast_codes(args.codes),
        pl.read_parquet(args.work / "snapshots.parquet"),
        posts,
        term_rows.training_neighbors(table, schools, config.serve.neighbor_miles),
    )
    base = backtest_terms.base_by_season(rows, delay_rows, places, config.model)
    folds = backtest_terms.walk_forward(
        rows, base, levels, config.backtest.test_seasons, config.model
    )
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
    has_base = ~np.isnan(base.p) & (base.counted >= 0)
    final = fit(backtest_terms.design_of(base, rows, levels, has_base), rows.season[has_base])
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
    (out / "report.md").write_text(markdown, encoding="utf-8")
    gate = terms_file.GateRecord(
        passed=judged.passed,
        gain=round(judged.gain, 6),
        report_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    )
    from snowlight.predict.cli import json_safe  # noqa: PLC0415

    metrics = {
        "gates": dataclasses.asdict(judged) | {"gain": judged.gain, "passed": judged.passed},
        "advisory": advisory,
        "advisory_evidence": dataclasses.asdict(evidence),
        "bins": [dataclasses.asdict(item) for item in bins],
    }
    write_json(out / "metrics.json", json_safe(json.loads(json.dumps(metrics, default=str))))
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
