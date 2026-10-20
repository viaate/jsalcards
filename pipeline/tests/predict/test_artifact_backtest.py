"""The model file, and the walk-forward backtest on toy data."""

from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError

from predict import world
from snowlight.predict import backtest, pool
from snowlight.predict.artifact import (
    DistrictModel,
    ModelArtifact,
    RecordDay,
    load,
)


def test_the_model_file_round_trips_byte_for_byte(tmp_path: Path) -> None:
    model = world.model()
    first = model.to_bytes()
    assert model.to_bytes() == first
    assert ModelArtifact.from_bytes(first) == model
    path = tmp_path / "model.json.gz"
    assert model.write(path) == len(first)
    assert load(path) == model
    text = first.decode("latin-1")
    assert "School" not in text  # no names


def test_the_model_file_refuses_what_does_not_add_up() -> None:
    with pytest.raises(ValidationError, match="add up"):
        DistrictModel(
            state="MO", county=None, time_zone=None,
            y=(5,) + (0,) * 9, n=(4,) + (0,) * 9, yd=(0,) * 10, nd=(0,) * 10,
        )  # fmt: skip
    with pytest.raises(ValidationError, match="all together"):
        DistrictModel(state="MO", county=None, time_zone=None, y=(0,) * 10)
    with pytest.raises(ValidationError, match="sorted"):
        DistrictModel(
            state="MO",
            county=None,
            time_zone=None,
            record={
                "none": (
                    RecordDay(day=date(2025, 1, 2), did="open"),
                    RecordDay(day=date(2025, 1, 1), did="open"),
                )
            },
        )
    with pytest.raises(ValidationError, match="unknown situation"):
        DistrictModel(
            state="MO",
            county=None,
            time_zone=None,
            record={"sunny": (RecordDay(day=date(2025, 1, 2), did="open"),)},
        )
    model = world.model()
    with pytest.raises(ValidationError, match="every level"):
        model.model_validate(model.model_dump() | {"strengths": {"no_school": {}, "delay": {}}})
    with pytest.raises(ValidationError, match="situations"):
        model.model_validate(model.model_dump() | {"situations": ("none",)})


def toy() -> tuple[pool.Places, pl.DataFrame]:
    """Two districts over five seasons: one closes for every snow warning, one never does."""
    places = pool.make_places(
        ["a", "b"],
        region=["ohio_valley", "ohio_valley"],
        state=["MO", "MO"],
        county=["29095", "29047"],
        neighbors={},
    )
    rows = []
    for season in range(2019, 2024):
        for i in range(10):
            day = date(season, 12, 1 + i)
            rows.append(("a", day, season, "no_school" if i < 6 else "open", 5, False, "KC"))
            rows.append(("b", day, season, "open" if i else "delayed", 5, False, "KC"))
            rows.append(("a", day, season, "open", 0, False, "KC"))
    labels = pl.DataFrame(
        rows,
        schema=["district", "day", "season", "outcome", "weather", "after", "cluster"],
        orient="row",
    )
    return places, labels


def test_folds_fit_only_on_seasons_before_the_test_season() -> None:
    places, labels = toy()
    usable = pool.usable_labels(labels, places)
    rows = pool.rows_from_labels(usable, places, "no_school")
    delays = pool.rows_from_labels(usable, places, "delay")
    # The spec's lighter pooling, so the two districts' own records show.
    light = world.CONFIG.model.model_copy(
        update={"own_min_days": 4, "level_min_days": 8, "m_grid": (1.0, 4.0, 16.0)}
    )
    folds = backtest.walk_forward(rows, delays, places, [2019, 2021, 2023], light)
    assert [fold.season for fold in folds] == [2021, 2023]  # 2019 has nothing before it
    scored = backtest.scored_frame(folds, rows, places, usable)
    assert set(scored["season"].to_list()) == {2021, 2023}
    snow_a = scored.filter((pl.col("district") == "a") & (pl.col("weather") == 5))
    snow_b = scored.filter((pl.col("district") == "b") & (pl.col("weather") == 5))
    assert float(snow_a["p"].to_numpy().min()) > float(snow_b["p"].to_numpy().max())
    # A fold for 2021 knows nothing of 2021 or later: its counts are 2019 and 2020 only.
    fold = folds[0]
    assert fold.p_raw.shape == (int((rows.season == 2021).sum()),)
    early = pool.tables_from_rows(rows.subset(rows.season < 2021), places, [2019, 2020])
    _y, n = early.total()
    assert n.sum() == 60  # 30 labeled days a season
    bins = backtest.reliability(
        scored["p_raw"].to_numpy(), scored["y"].to_numpy(), scored["cluster"].to_list(), 10
    )
    judged = backtest.gates(scored, bins, [], 300, g1_min_storm_rows=1, g1_tolerance=0.005)
    assert judged.g1_counted == 2
    assert [item.season for item in judged.g1_by_season] == [2021, 2023]
    assert isinstance(judged.passed, bool)
    labels_all = usable.with_columns(pl.lit(None, dtype=pl.String).alias("unknown_why"))
    cases = backtest.named_cases(
        labels_all, scored, {"a": "A", "q": "Q"}, [labels_all["day"][0]], {"a": "KC"}
    )
    assert any("| A (a) |" in line for line in cases)
    assert any("no morning read" in line for line in cases)
    report = backtest.report_markdown(
        {"all": backtest.summarize(scored).as_json()}, bins, judged, cases
    )
    assert "Piece 1 gate (pooled G1, here):" in report
    assert "| bin | rows | clusters | mean p | observed | gap | SE | within |" in report
    assert "<svg" in backtest.reliability_svg(bins)


def test_metrics_on_toy_numbers() -> None:
    p = np.array([0.1, 0.9, 0.6, 0.2])
    y = np.array([0.0, 1.0, 0.0, 1.0])
    assert backtest.brier(p, y) == pytest.approx((0.01 + 0.01 + 0.36 + 0.64) / 4)
    assert np.isnan(backtest.brier(np.array([]), np.array([])))
    recall, precision = backtest.caught(p, y)
    assert recall == 0.5
    assert precision == 0.5
    found = backtest.reliability(p, y, [("d", "a"), ("d", "a"), ("d", "b"), ("d", "b")], 2)
    assert [item.rows for item in found] == [2, 2]
    assert found[0].mean_p == pytest.approx(0.15)
    assert found[0].observed == pytest.approx(0.5)
    assert backtest.ece(found) == pytest.approx((abs(0.5 - 0.15) + abs(0.5 - 0.75)) / 2)
    # One cluster: its residuals cancel; two clusters: the plain standard error.
    assert backtest.clustered_se(np.array([1.0, 0.0]), ["x", "x"]) == 0.0
    assert backtest.clustered_se(np.array([1.0, 0.0]), ["x", "y"]) == pytest.approx(0.5**0.5 / 2)
    assert backtest.Bin(0, 0.1, 400, 0.05, 0.09, 0.01).within()
    assert not backtest.Bin(0, 0.1, 400, 0.05, 0.2, 0.01).within()
    assert backtest.storm_day_briers(
        pl.DataFrame({"day": [1, 1], "cluster": ["a", "a"], "y": [1.0, 1.0], "p": [0.5, 0.5]}), 2
    ) == [0.25]


def _season_rows(season: int, rows: int, p: float, b0: float, closed: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "season": [season] * rows,
            "weather": [5] * rows,
            "y": [1.0] * closed + [0.0] * (rows - closed),
            "p": [p] * rows,
            "q": [0.0] * rows,
            "b0": [b0] * rows,
            "b1": [b0] * rows,
        }
    )


def test_amended_g1_gates_only_seasons_with_enough_storm_rows() -> None:
    """Addendum 2026-10-20 b: pooled at most B0, and each season of 300+ storm rows no
    worse than B0 by more than 0.005; a smaller season is reported, not gated."""
    # 2021: 400 rows, model a hair worse than B0 (within 0.005): passes.
    # 2022: 80 rows, model far worse: reported only.
    # 2023: 400 rows, model better: passes and carries the pooled number.
    scored = pl.concat(
        [
            _season_rows(2021, 400, 0.52, 0.50, 200),
            _season_rows(2022, 80, 0.10, 0.50, 40),
            _season_rows(2023, 400, 0.30, 0.50, 100),
        ]
    )
    judged = backtest.gates(scored, [], [2022], 300, g1_min_storm_rows=300, g1_tolerance=0.005)
    seasons = {item.season: item for item in judged.g1_by_season}
    assert seasons[2021].gated
    assert seasons[2021].excess == pytest.approx(0.0004)
    assert seasons[2021].ok
    assert not seasons[2022].gated
    assert seasons[2022].apart
    assert not seasons[2022].ok  # reported as worse, and still not gated
    assert seasons[2023].gated
    assert seasons[2023].excess < 0
    assert (judged.g1_counted, judged.g1_seasons) == (2, 2)
    assert judged.g1_pooled
    assert judged.g1_pooled_without_apart
    assert judged.g1
    report = backtest.report_markdown({}, [], judged, [])
    assert "| 2022-23 (reported apart) | 80 |" in report
    assert "reported (too few rows)" in report
    # A gated season worse than B0 by more than the tolerance fails G1.
    worse = pl.concat([scored, _season_rows(2024, 300, 0.60, 0.50, 150)])
    judged = backtest.gates(worse, [], [], 300, g1_min_storm_rows=300, g1_tolerance=0.005)
    assert judged.g1_counted == 3
    assert judged.g1_seasons == 2
    assert not judged.g1
    # Addendum 2026-10-20 d: piece 1 gates pooled G1 (and G4, the leakage tests); a season
    # over the tolerance is reported, not gated.
    assert judged.g1_pooled
    assert judged.passed
    report = backtest.report_markdown({}, [], judged, [])
    assert "Piece 1 gate (pooled G1, here): PASS (pooled G1 pass, without 2020-21 pass)." in (
        report
    )
    # G4 is the leakage tests, never a value this report computes or could call failed.
    assert backtest.G4_NOTE in report
    assert "G4 the leakage tests: PASS" not in report
    assert "Reported, not gated: G1 seasons 2 of 3" in report
    assert backtest.LAUNCH_GATE in report
    # Pooled worse than B0 fails piece 1.
    pooled_worse = pl.concat([worse, _season_rows(2025, 2000, 0.70, 0.50, 600)])
    judged = backtest.gates(pooled_worse, [], [], 300, g1_min_storm_rows=300, g1_tolerance=0.005)
    assert not judged.g1_pooled
    assert not judged.passed
    failed = backtest.report_markdown({}, [], judged, [])
    assert "Piece 1 gate (pooled G1, here): FAIL (pooled G1 FAIL" in failed
    assert "G4 the leakage tests: FAIL" not in failed
    assert backtest.G4_NOTE in failed
