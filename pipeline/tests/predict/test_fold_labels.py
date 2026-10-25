"""The per-fold rule: every walk-forward fold trains on labels built only from the seasons
before its test season (calc-research plan T1; synthetic)."""

from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from predict import world
from predict.test_artifact_backtest import toy
from predict.test_labels import CHANNELS, CHICAGO, EARLY_DAYS, FOLD_START
from snowlight.predict import (
    backtest,
    backtest_terms,
    cli,
    pool,
    terms,
    terms_cli,
    terms_file,
    train,
)
from snowlight.predict.backtest import FoldRows
from snowlight.predict.calendar import school_days
from snowlight.predict.labels import DayLit, ReadRecord
from snowlight.predict.pool import Rows
from snowlight.predict.terms import UNKNOWN, Design, Term

LIGHT = world.CONFIG.model.model_copy(
    update={"own_min_days": 4, "level_min_days": 8, "m_grid": (1.0, 4.0, 16.0)}
)
SEASONS = (2019, 2020, 2021, 2022, 2023)


def fold_frame(labels: pl.DataFrame, season: int, flip: int) -> pl.DataFrame:
    """A fold's labels: the seasons before ``season``, with the first ``flip`` snow days of
    district a moved to open (a fold's own audiences label some days another way)."""
    earlier = labels.filter(pl.col("season") < season)
    snow_a = (pl.col("district") == "a") & (pl.col("weather") == 5)
    day_rank = pl.col("day").dt.day()
    return earlier.with_columns(
        pl.when(snow_a & (day_rank <= flip))
        .then(pl.lit("open"))
        .otherwise(pl.col("outcome"))
        .alias("outcome")
    )


def fold_rows(frame: pl.DataFrame, places: pool.Places) -> FoldRows:
    usable = pool.usable_labels(frame, places)
    return FoldRows(
        pool.rows_from_labels(usable, places, "no_school"),
        pool.rows_from_labels(usable, places, "delay"),
    )


def whole_and_folds(
    flip: int = 3,
) -> tuple[pool.Places, pl.DataFrame, Rows, Rows, dict[int, FoldRows]]:
    places, labels = toy()
    usable = pool.usable_labels(labels, places)
    rows = pool.rows_from_labels(usable, places, "no_school")
    delays = pool.rows_from_labels(usable, places, "delay")
    folds = {s: fold_rows(fold_frame(labels, s, flip), places) for s in SEASONS[1:]}
    return places, labels, rows, delays, folds


def later_changed(labels: pl.DataFrame, season: int) -> pl.DataFrame:
    """``labels`` with every outcome of ``season`` and later turned around."""
    swap = pl.when(pl.col("outcome") == "open").then(pl.lit("no_school")).otherwise(pl.lit("open"))
    return labels.with_columns(
        pl.when(pl.col("season") >= season).then(swap).otherwise(pl.col("outcome")).alias("outcome")
    )


def test_a_piece_1_fold_trains_on_its_own_fold_labels_only() -> None:
    places, labels, rows, delays, folds = whole_and_folds()
    found = backtest.walk_forward(rows, delays, places, [2021, 2022], LIGHT, training=folds)
    assert [fold.season for fold in found] == [2021, 2022]
    test = rows.subset(rows.season == 2021)
    mine = folds[2021]
    _s, _d, p_raw, _p, _q = backtest.fit_predict(
        mine.rows, mine.delay_rows, test, places, [2019, 2020], LIGHT
    )
    np.testing.assert_array_equal(found[0].p_raw, p_raw)
    old = backtest.walk_forward(rows, delays, places, [2021], LIGHT)
    assert not np.array_equal(
        old[0].p_raw, found[0].p_raw, equal_nan=True
    )  # the rule changes the fit
    # The whole archive's training rows and every later fold's labels do not reach 2021's fold.
    other = later_changed(labels, 2019)
    usable = pool.usable_labels(other, places)
    changed_rows = pool.rows_from_labels(usable, places, "no_school")
    changed_delays = pool.rows_from_labels(usable, places, "delay")
    test_kept = changed_rows.subset(changed_rows.season == 2021)
    later = {
        s: fold_rows(fold_frame(later_changed(labels, 2021), s, 1), places) if s > 2021 else f
        for s, f in folds.items()
    }
    # The test rows are the same days; only their outcomes moved, and those are scored, not fit.
    again = backtest.walk_forward(
        changed_rows, changed_delays, places, [2021], LIGHT, training=later
    )
    np.testing.assert_array_equal(again[0].p_raw, found[0].p_raw)
    assert test_kept.y.tolist() != test.y.tolist()


def test_a_fold_with_no_labels_or_a_later_row_is_refused() -> None:
    places, labels, rows, delays, folds = whole_and_folds()
    with pytest.raises(ValueError, match="no fold labels for test season 2021"):
        backtest.walk_forward(rows, delays, places, [2021], LIGHT, training={2022: folds[2022]})
    leaky = {2021: fold_rows(labels.filter(pl.col("season") <= 2021), places)}
    with pytest.raises(ValueError, match="hold a row of 2021"):
        backtest.walk_forward(rows, delays, places, [2021], LIGHT, training=leaky)
    with pytest.raises(ValueError, match="not out of the rows"):
        backtest_terms.base_by_season(
            rows,
            delays,
            places,
            LIGHT,
            exclude=(np.zeros(len(rows), bool), np.zeros(len(delays), bool)),
            training=folds,
        )


def test_each_rows_base_comes_from_its_own_seasons_fold_labels() -> None:
    places, _labels, rows, delays, folds = whole_and_folds()
    fits: dict[int, backtest_terms.Predictor] = {}
    base = backtest_terms.base_by_season(rows, delays, places, LIGHT, training=folds, fits=fits)
    assert sorted(fits) == [2020, 2021, 2022, 2023]
    assert np.isnan(base.p[rows.season == 2019]).all()  # the first season has no base
    for season in (2020, 2021, 2022, 2023):
        mask = rows.season == season
        mine = folds[season]
        before = sorted(s for s in set(mine.rows.season.tolist()) if s < season)
        _s, _d, p_raw, _p, _q = backtest.fit_predict(
            mine.rows, mine.delay_rows, rows.subset(mask), places, before, LIGHT
        )
        np.testing.assert_array_equal(base.p_raw[mask], p_raw)
    # Another season's fold labels never move a row's base.
    swapped = dict(folds)
    swapped[2023] = folds[2021]
    again = backtest_terms.base_by_season(rows, delays, places, LIGHT, training=swapped)
    keep = rows.season < 2023
    np.testing.assert_array_equal(again.p_raw[keep], base.p_raw[keep])
    # The cache is reused: a fold's own rows get the same season's fit.
    fold_base = backtest_terms.base_by_season(
        folds[2023].rows, folds[2023].delay_rows, places, LIGHT, training=folds, fits=fits
    )
    assert sorted(fits) == [2020, 2021, 2022, 2023]
    assert np.isnan(fold_base.p[folds[2023].rows.season == 2019]).all()
    # The whole rule is unchanged.
    whole = backtest_terms.base_by_season(rows, delays, places, LIGHT)
    assert not np.array_equal(
        whole.p_raw[rows.season == 2021], base.p_raw[rows.season == 2021], equal_nan=True
    )


def test_a_terms_fold_fits_on_its_fold_labels_rows_bases_and_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    places, _labels, rows, delays, folds = whole_and_folds()

    def levels_of(n: int, seed: int) -> dict[Term, np.ndarray]:
        found = {term: np.full(n, UNKNOWN, dtype=np.int64) for term in terms.TERM_ORDER}
        found[Term.SNOW_ADVISORY] = np.random.default_rng(seed).integers(0, 6, n)
        return found

    levels = levels_of(len(rows), 1)
    fold_levels = {s: levels_of(len(f.rows), s) for s, f in folds.items()}
    base = backtest_terms.base_by_season(rows, delays, places, LIGHT, training=folds)
    training = backtest_terms.term_training(folds, fold_levels, places, LIGHT, [2022, 2023])
    assert sorted(training) == [2022, 2023]
    seen: list[tuple[int, int]] = []
    real = backtest_terms.fit

    def spy(design: Design, seasons: np.ndarray) -> terms.Model:
        seen.append((len(seasons), int(seasons.max())))
        return real(design, seasons)

    monkeypatch.setattr(backtest_terms, "fit", spy)
    found = backtest_terms.walk_forward(rows, base, levels, [2022, 2023], LIGHT, training=training)
    assert [fold.season for fold in found] == [2022, 2023]
    for i, (fold, season) in enumerate(zip(found, (2022, 2023), strict=True)):
        mine = training[season]
        has = ~np.isnan(mine.base.p) & (mine.base.counted >= 0)
        assert seen[i] == (int(has.sum()), season - 1)
        assert set(rows.season[fold.rows].tolist()) == {season}
    # The whole archive's earlier rows, bases and levels never reach a fold's fit.
    scrambled = {term: level[::-1].copy() for term, level in levels.items()}
    test = rows.season >= 2022
    for term, level in scrambled.items():
        level[test] = levels[term][test]
    again = backtest_terms.walk_forward(
        rows, base, scrambled, [2022, 2023], LIGHT, training=training
    )
    for one, two in zip(found, again, strict=True):
        np.testing.assert_array_equal(one.p_terms_raw, two.p_terms_raw)
    with pytest.raises(ValueError, match="no fold labels for test season 2023"):
        backtest_terms.walk_forward(
            rows, base, levels, [2023], LIGHT, training={2022: training[2022]}
        )
    late = backtest_terms.TermTraining(rows, base, levels)
    with pytest.raises(ValueError, match="hold a later row"):
        backtest_terms.walk_forward(rows, base, levels, [2023], LIGHT, training={2023: late})
    with pytest.raises(ValueError, match="not the test rows"):
        backtest_terms.walk_forward(
            rows, base, levels, [2023], LIGHT, np.ones(len(rows)), training=training
        )


def test_fold_label_files_are_read_whole_and_never_hold_their_test_season(
    tmp_path: Path,
) -> None:
    _places, toy_labels = toy()
    labels = toy_labels.filter(pl.col("weather") == 5)  # one row a district-day
    for season in (2020, 2021):
        labels.filter(pl.col("day") < train.fold_start(season)).write_parquet(
            train.fold_label_path(tmp_path, season)
        )
    found = train.read_fold_labels(tmp_path, [2020, 2021])
    assert found[2021]["day"].max() == date(2020, 12, 10)
    assert train.fold_label_path(tmp_path, 2021, private=True).name == (
        "labels-private-before-2021-07-01.parquet"
    )
    with pytest.raises(FileNotFoundError, match="2022-23"):
        train.read_fold_labels(tmp_path, [2022])
    labels.write_parquet(train.fold_label_path(tmp_path, 2022))
    with pytest.raises(ValueError, match="2022-23 or later"):
        train.read_fold_labels(tmp_path, [2022])
    audit = train.label_audit(labels, {2021: found[2021]})
    assert [(item.season, item.changes.share) for item in audit] == [(2021, 0.0)]
    moved = found[2021].with_columns(pl.lit("unknown").alias("outcome"))
    audit = train.label_audit(labels, {2021: moved})
    assert audit[0].changes.changed == audit[0].changes.training > 0


def test_backtest_v2_under_the_per_fold_rule_and_a_date_left_out(tmp_path: Path) -> None:
    places, toy_labels = toy()
    labels = toy_labels.filter(pl.col("weather") == 5)
    for season in SEASONS[1:]:
        fold_frame(labels, season, 3).write_parquet(train.fold_label_path(tmp_path, season))
    fold = train.read_fold_set(tmp_path, SEASONS[1:], places)
    assert sorted(fold.training) == list(SEASONS[1:])
    days, delay_days = fold.days(2021)
    assert len(days) == len(fold.training[2021].rows)
    assert len(delay_days) == len(fold.training[2021].delay_rows)

    def levels_of(n: int) -> dict[Term, np.ndarray]:
        return {term: np.full(n, UNKNOWN, dtype=np.int64) for term in terms.TERM_ORDER}

    usable = pool.usable_labels(labels, places)
    rows = pool.rows_from_labels(usable, places, "no_school")
    config = world.CONFIG.model_copy(update={"model": LIGHT})
    config = config.model_copy(
        update={"backtest": config.backtest.model_copy(update={"test_seasons": (2022, 2023)})}
    )
    per_fold = terms_cli.FoldTerms(
        fold, {s: levels_of(len(f.rows)) for s, f in fold.training.items()}
    )
    base, folds = per_fold.walk_forward(rows, levels_of(len(rows)), places, config)
    assert [item.season for item in folds] == [2022, 2023]
    assert np.isnan(base.p[rows.season == 2019]).all()
    left = date(2019, 12, 1).toordinal()
    fewer = per_fold.without(left)
    for season, frame in fewer.fold.usable.items():
        assert left not in {d.toordinal() for d in frame["day"].to_list()}
        assert len(fewer.fold.training[season].rows) == frame.height
        assert all(len(level) == frame.height for level in fewer.levels[season].values())
    _base, again = fewer.walk_forward(rows, levels_of(len(rows)), places, config)
    assert [item.season for item in again] == [2022, 2023]


def test_the_reports_name_their_training_labels_rule() -> None:
    note = terms_cli.labels_rule_note("# T\n\nGate line.\n\nMore.\n", per_fold=True)
    assert note.splitlines()[2] == "Gate line."
    assert note.splitlines()[4] == backtest.PER_FOLD_NOTE
    whole = terms_cli.labels_rule_note("# T\n\nGate line.\n", per_fold=False)
    assert whole.splitlines()[4] == backtest.WHOLE_NOTE


def one_cell(places: pool.Places, unit: str, situation: int, season: int) -> Rows:
    return Rows(
        np.array([places.position()[unit]], dtype=np.int64),
        np.array([situation], dtype=np.int64),
        np.array([season], dtype=np.int64),
        np.array([np.nan]),
    )


SNOW: int = pool.SITUATION_INDEX[pool.situation_of(5, False).key]


def test_a_named_days_chance_fits_on_its_seasons_fold_labels_only() -> None:
    places, labels, rows, delays, folds = whole_and_folds()
    cells = [("a", SNOW, 2021), ("a", SNOW, 2023), ("b", SNOW, 2019), ("zz", SNOW, 2021)]
    first = {2019: fold_rows(labels.filter(pl.col("season") < 2019), places)}  # no rows
    found = backtest.chances_on(rows, delays, places, cells, LIGHT, training=folds | first)
    for (unit, situation, season), chance in zip(cells[:2], found[:2], strict=True):
        mine = folds[season]
        before = sorted(s for s in set(mine.rows.season.tolist()) if s < season)
        _s, _d, _raw, p, _q = backtest.fit_predict(
            mine.rows,
            mine.delay_rows,
            one_cell(places, unit, situation, season),
            places,
            before,
            LIGHT,
        )
        assert chance == float(p[0])
    assert found[2:] == [None, None]  # nothing before 2019; a unit not in the places
    whole = backtest.chances_on(rows, delays, places, cells[:2], LIGHT)
    assert whole != found[:2]  # the rule changes the chance
    # The whole archive's rows never reach a per-fold chance: turn every outcome around.
    other = pool.usable_labels(later_changed(labels, 2019), places)
    again = backtest.chances_on(
        pool.rows_from_labels(other, places, "no_school"),
        pool.rows_from_labels(other, places, "delay"),
        places,
        cells[:2],
        LIGHT,
        training=folds,
    )
    assert again == found[:2]
    # Nor does a later season's fold: 2021's chance is the same with 2022's and 2023's moved.
    moved = dict(folds)
    moved[2023] = moved[2022] = folds[2020]
    assert backtest.chances_on(rows, delays, places, cells[:1], LIGHT, training=moved) == found[:1]
    with pytest.raises(ValueError, match="no fold labels for test season 2023"):
        backtest.chances_on(rows, delays, places, cells[:2], LIGHT, training={2021: folds[2021]})
    leaky = {2021: fold_rows(labels.filter(pl.col("season") <= 2021), places)}
    with pytest.raises(ValueError, match="hold a row of 2021"):
        backtest.chances_on(rows, delays, places, cells[:1], LIGHT, training=leaky)


def test_the_named_private_days_table_fits_per_fold_under_the_rule() -> None:
    places, labels, _rows, _delays, folds = whole_and_folds()
    days = [date(2021, 12, 8), date(2023, 12, 8)]
    weather = pl.DataFrame(
        {"district": ["a", "a"], "day": days, "weather": [5, 5]},
        schema={"district": pl.String, "day": pl.Date, "weather": pl.Int64},
    )
    names = {"a": "School A"}
    lines = cli.oracle_table(labels, weather, places, LIGHT, training=folds, names=names, days=days)
    assert backtest.PER_FOLD_NOTE in lines
    usable = pool.usable_labels(labels, places)
    rows = pool.rows_from_labels(usable, places, "no_school")
    delays = pool.rows_from_labels(usable, places, "delay")
    cells = [("a", SNOW, 2021), ("a", SNOW, 2023)]
    expected = backtest.chances_on(rows, delays, places, cells, LIGHT, training=folds)
    shown = [line for line in lines if line.startswith("| School A")]
    assert [line.split(" | ")[4] for line in shown] == [
        f"{c:.2f}" for c in expected if c is not None
    ]
    whole = cli.oracle_table(labels, weather, places, LIGHT, names=names, days=days)
    assert backtest.WHOLE_NOTE in whole
    assert [line for line in whole if line.startswith("| School A")] != shown


def test_the_per_fold_report_scores_both_rules_on_the_rows_both_score() -> None:
    places, labels, rows, delays, folds = whole_and_folds()
    # 2021's fold labels hold no snow day: its snow test rows are dark under the rule.
    calm = labels.filter((pl.col("season") < 2021) & (pl.col("weather") == 0))
    dark = folds | {2021: fold_rows(calm, places)}
    seasons = [2020, 2021, 2022, 2023]
    mine = backtest.walk_forward(rows, delays, places, seasons, LIGHT, training=dark)
    whole = backtest.walk_forward(rows, delays, places, seasons, LIGHT)
    found = backtest.compare_rules(mine, whole, rows, seasons)
    storm = backtest.WEATHER_OF_SITUATION[rows.situation] > 0

    def dark_of(folds_: list[backtest.Fold]) -> tuple[dict[int, tuple[int, int]], np.ndarray]:
        missing = np.ones(len(rows), dtype=np.bool_)
        for fold in folds_:
            missing[rows.season == fold.season] = np.isnan(fold.p)
        return {
            s: (
                int(missing[rows.season == s].sum()),
                int((missing & storm)[rows.season == s].sum()),
            )
            for s in seasons
        }, missing

    expected, missing = dark_of(mine)
    expected_whole, missing_whole = dark_of(whole)
    assert found.unmodeled == expected
    assert found.unmodeled_whole == expected_whole
    snow_2021 = int((storm & (rows.season == 2021)).sum())
    dark_2021 = expected[2021][0]
    assert expected[2021][1] == snow_2021 > 0  # every snow row of 2021 is dark under the rule
    assert expected_whole[2021][1] == 0  # and scored under the whole archive's labels
    shared = storm & ~missing & ~missing_whole
    assert found.storm_rows == int(shared.sum()) > 0
    p_whole = np.full(len(rows), np.nan)
    b0 = np.full(len(rows), np.nan)
    for fold in whole:
        p_whole[rows.season == fold.season] = fold.p
    for fold in mine:
        b0[rows.season == fold.season] = fold.b0
    assert found.brier_whole == pytest.approx(backtest.brier(p_whole[shared], rows.y[shared]))
    assert found.brier_b0 == pytest.approx(backtest.brier(b0[shared], rows.y[shared]))
    lines = found.markdown()
    dark_all = sum(n for n, _storm in expected.values())
    dark_storm = sum(storm_ for _n, storm_ in expected.values())
    assert f"unmodeled: {dark_all:,} ({dark_storm:,} storm rows)" in lines[2]
    assert f"on the {found.storm_rows:,} storm rows both rules score" in lines[2]
    assert f"| 2021-22 | {dark_2021} | {snow_2021} | {expected_whole[2021][0]} | 0 |" in lines
    assert found.as_json()["same_storm_rows"] == found.storm_rows
    # A test season no fold could fit at all counts every row of it as dark.
    late = backtest.compare_rules(mine[:1], whole, rows, seasons)
    assert late.unmodeled[2023] == (
        int((rows.season == 2023).sum()),
        int((storm & (rows.season == 2023)).sum()),
    )
    report = backtest.report_markdown(
        {},
        [],
        backtest.gates(
            backtest.scored_frame(mine, rows, places, pool.usable_labels(labels, places)),
            [],
            [],
            300,
            g1_min_storm_rows=1,
            g1_tolerance=0.005,
        ),
        [],
        per_fold=True,
        comparison=found,
    )
    assert lines[0] in report.splitlines()


def fake_run(listings: list[tuple[str, str, date]], reads: list[ReadRecord]) -> train.ArchiveRun:
    """An archive run whose every day settles with nothing lit (no replay step)."""
    ordered = sorted(reads, key=lambda item: item.fetched_at)
    first, last = ordered[0].fetched_at.date(), ordered[-1].fetched_at.date()
    return train.ArchiveRun(
        inputs=object(),
        index=train.DayIndex(object(), [], []),
        listings=listings,
        market_of={"kaaa": "Kansas City"},
        reads=ordered,
        settled_days={day: DayLit({}) for day in school_days(first, last)},
    )


def test_the_label_runs_build_a_folds_labels_from_the_seasons_before_it_only() -> None:
    channel = CHANNELS["captures"]  # kaaa's station gate: 3 captures before the fold, 23 in all
    units = ("d1", "p1")

    def listed(found: list[tuple[str, str, date]]) -> list[tuple[str, str, date]]:
        return [(station, unit, day) for station, _d, day in found for unit in units]

    run = fake_run(
        listed([*channel.early_listings, *channel.later_listings]),
        [*channel.early_reads, *channel.later_reads],
    )
    early = fake_run(listed(channel.early_listings), channel.early_reads)
    schools = pl.DataFrame(
        {
            "id": ["s1", "s2", "p1"],
            "district_id": ["d1", "d1", None],
            "kind": ["public", "public", "private"],
            "kind_flags": [0, 0, train.PRIVATE_FLAG],
        }
    )
    table = pl.DataFrame({"district": ["d1"], "time_zone": [CHICAGO], "state": ["MO"]})
    private = pl.DataFrame({"district": ["p1"], "time_zone": [CHICAGO], "state": ["MO"]})
    weather = pl.DataFrame(
        {"district": ["d1"], "day": [EARLY_DAYS[0]], "weather": [0]},
        schema={"district": pl.String, "day": pl.Date, "weather": pl.Int64},
    )
    private_weather = weather.with_columns(pl.lit("p1").alias("district"))
    config = world.CONFIG
    fold = train.run_labels(run, schools, table, weather, config, before=FOLD_START)
    assert run.markets == {}  # a fold's build leaves the run's own markets as they are
    alone = train.run_labels(early, schools, table, weather, config)
    assert fold.height > 0
    assert fold.equals(alone)
    assert set(fold["unknown_why"].to_list()) == {"thin_station"}
    assert train.fold_labels(run, schools, table, weather, config, [2018])[2018].equals(fold)
    whole = train.run_labels(run, schools, table, weather, config)
    assert run.markets == {"d1": "Kansas City", "p1": "Kansas City"}
    assert not whole.filter(pl.col("day") < FOLD_START).equals(fold)
    mine = train.run_private_labels(run, private, private_weather, fold, config, before=FOLD_START)
    assert mine.height > 0
    assert mine.equals(train.run_private_labels(early, private, private_weather, alone, config))
    folds = train.private_fold_labels(run, private, private_weather, {2018: fold}, config)
    assert folds[2018].equals(mine)
    theirs = train.run_private_labels(run, private, private_weather, whole, config)
    assert not theirs.filter(pl.col("day") < FOLD_START).equals(mine)


def test_a_terms_file_is_written_only_with_the_gate_of_its_served_fits_rule() -> None:
    assert terms_cli.terms_write_refusal("whole", report_only=False) is None
    assert terms_cli.terms_write_refusal("fold", report_only=True) is None
    refusal = terms_cli.terms_write_refusal("fold", report_only=False)
    assert refusal is not None
    assert "--report-only" in refusal
    assert "--labels-rule whole" in refusal
    # The committed file records the gate it was judged under: the whole archive's labels.
    committed = terms_file.TermsArtifact.from_bytes(terms_file.TERMS_PATH.read_bytes())
    assert committed.gate is not None
    assert committed.gate.labels_rule == "whole"
    assert not committed.gate.passed
    gate = terms_file.GateRecord(passed=True, gain=0.05, report_sha256="c" * 64, labels_rule="fold")
    assert terms_file.GateRecord.model_validate_json(gate.model_dump_json()) == gate


def test_p8s_dates_under_the_rule_come_from_the_candidates_own_fold_fits(
    tmp_path: Path,
) -> None:
    places, toy_labels = toy()
    labels = toy_labels.filter(pl.col("weather") == 5)
    for season in SEASONS[1:]:
        fold_frame(labels, season, 3).write_parquet(train.fold_label_path(tmp_path, season))
    fold = train.read_fold_set(tmp_path, SEASONS[1:], places)

    def levels_of(n: int, seed: int) -> dict[Term, np.ndarray]:
        found = {term: np.full(n, UNKNOWN, dtype=np.int64) for term in terms.TERM_ORDER}
        found[Term.SNOW_STORM] = np.random.default_rng(seed).integers(0, 6, n)
        return found

    usable = pool.usable_labels(labels, places)
    rows = pool.rows_from_labels(usable, places, "no_school")
    config = world.CONFIG.model_copy(update={"model": LIGHT})
    config = config.model_copy(
        update={"backtest": config.backtest.model_copy(update={"test_seasons": (2022, 2023)})}
    )
    per_fold = terms_cli.FoldTerms(
        fold, {s: levels_of(len(f.rows), s) for s, f in fold.training.items()}
    )
    found = per_fold.fit(rows, levels_of(len(rows), 1), places, config)
    assert [item.season for item in found.folds] == [2022, 2023]
    assert per_fold.walk_forward(rows, levels_of(len(rows), 1), places, config)[1][0].season == 2022
    # Each (district, day) a fold's own fit moves in its own training rows, counted once.
    moved: set[tuple[int, int]] = set()
    for item in found.folds:
        source = found.training[item.season]
        days, _delay = fold.days(item.season)
        for i in range(len(source.rows)):
            if np.isnan(source.base.p[i]) or source.base.counted[i] < 0:
                continue
            one = np.zeros(len(source.rows), dtype=np.bool_)
            one[i] = True
            design = backtest_terms.design_of(source.base, source.rows, source.levels, one)
            if any(v[0] != 0 for v in terms.contributions(item.model, design).values()):
                moved.add((int(source.rows.district[i]), int(days[i])))
    assert moved  # the fits move some training rows
    counts: dict[int, int] = {}
    for _unit, day in moved:
        counts[day] = counts.get(day, 0) + 1
    expected = [d for d, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    assert per_fold.moved_dates(found) == expected
    # The test rows' own levels (the whole archive's labels) never pick a date.
    again = per_fold.fit(rows, levels_of(len(rows), 99), places, config)
    assert per_fold.moved_dates(again) == expected
    first = date(2016, 2, 16).toordinal()
    assert terms_cli.p8_dates(expected) == [first, *expected]
    assert terms_cli.p8_dates([first, *expected[:1]]) == [first, *expected[:1]]
    assert backtest_terms.fold_moved_dates([], found.training, {}) == []
    # The run's walk under each rule: the per-fold one picks P8's dates from its own fits.
    levels = levels_of(len(rows), 1)
    base, folds, moved_dates = terms_cli._walk(per_fold, rows, found.base, levels, places, config)
    assert moved_dates == per_fold.moved_dates(found)
    np.testing.assert_array_equal(base.p, found.base.p)
    assert [item.season for item in folds] == [2022, 2023]
    whole = backtest_terms.base_by_season(rows, rows.subset(rows.season < 0), places, LIGHT)
    base, folds, moved_dates = terms_cli._walk(None, rows, whole, levels, places, config)
    assert moved_dates is None
    assert base is whole
    assert [item.season for item in folds] == [2022, 2023]
