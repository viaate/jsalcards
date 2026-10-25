"""S7-F's backtest scorers (spec-f s. 12 and the research plan's report additions). SYNTHETIC
rows only."""

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from predict import world
from snowlight.predict import backtest, outlook, outlook_backtest, pool
from snowlight.predict.outlook_states import INDEX_OF, MOMENTS


def frame(rows: list[tuple[str, date, str, float, float, float, float]]) -> pl.DataFrame:
    """(district, day, cluster, y, p_s7f, p_issued, p_shipped) as a scored frame at 20:00."""
    return pl.DataFrame(
        rows,
        schema={
            "district": pl.String, "day": pl.Date, "cluster": pl.String, "y": pl.Float64,
            "p_s7f": pl.Float64, "p_issued": pl.Float64, "p_shipped": pl.Float64,
        },
        orient="row",
    ).with_columns(
        pl.lit("20:00").alias("moment"), pl.lit(0, dtype=pl.Int64).alias("c0"),
        pl.lit(0, dtype=pl.Int64).alias("h"), pl.lit(0, dtype=pl.Int64).alias("f"),
        pl.lit(1, dtype=pl.Int8).alias("weather"), pl.lit(2024).alias("season"),
        pl.when(pl.col("y") > 0)
        .then(pl.lit("no_school"))
        .otherwise(pl.lit("open"))
        .alias("outcome"),
        pl.lit(0.0).alias("named"),
    )  # fmt: skip


DAY = date(2024, 1, 16)


def test_the_bootstrap_bound_is_below_zero_only_when_every_cluster_gains() -> None:
    gains = np.array([-0.1, -0.2, -0.05, -0.3])
    assert outlook_backtest.bootstrap_upper(gains, ["a", "b", "c", "d"], 500) < 0
    mixed = np.array([-0.3, 0.2, -0.3, 0.25])
    assert outlook_backtest.bootstrap_upper(mixed, ["a", "b", "c", "d"], 500) > 0
    assert np.isnan(outlook_backtest.bootstrap_upper(np.zeros(0), [], 10))


def test_ranking_counts_pairs_within_a_market_day_and_keeps_split_days_apart() -> None:
    rows = [
        ("a", DAY, "KC", 1.0, 0.9, 0.5, 0.5),
        ("b", DAY, "KC", 0.0, 0.2, 0.5, 0.6),
        ("c", DAY, "KC", 0.0, 0.95, 0.5, 0.1),
        ("d", DAY, "STL", 1.0, 0.5, 0.5, 0.5),  # one outcome only: no pair
        ("e", date(2023, 3, 14), "Hartford & New Haven, CT DMA", 1.0, 0.8, 0.1, 0.1),
        ("f", date(2023, 3, 14), "Hartford & New Haven, CT DMA", 0.0, 0.2, 0.9, 0.9),
    ]
    found = outlook_backtest.ranking(frame(rows))
    assert found["other"]["pairs"] == 2
    assert found["other"]["s7f"] == 0.5  # right on b, wrong on c
    assert found["other"]["issued"] == 0.5  # two ties
    assert found["other"]["shipped"] == 0.5
    assert found["split"] == {
        "market_days": 1, "pairs": 1, "s7f": 1.0, "issued": 0.0, "shipped": 0.0,
    }  # fmt: skip


def test_gains_split_into_rows_raised_and_lowered() -> None:
    rows = [
        ("a", DAY, "KC", 1.0, 0.9, 0.5, 0.5),  # raised, right
        ("b", DAY, "KC", 0.0, 0.6, 0.5, 0.5),  # raised, wrong
        ("c", DAY, "KC", 0.0, 0.1, 0.5, 0.5),  # lowered, right
        ("d", DAY, "KC", 0.0, 0.5, 0.5, 0.5),
    ]
    found = outlook_backtest.raised_lowered(frame(rows), "issued")
    assert found["raised"]["rows"] == 2
    assert found["raised"]["closings"] == 1
    assert found["raised"]["sse_saved"] == pytest.approx(0.25 - 0.01 + 0.25 - 0.36)
    assert found["lowered"]["sse_saved"] == pytest.approx(0.25 - 0.01)
    assert found["same"]["rows"] == 1


def test_the_level_free_shift_recovers_a_known_shift() -> None:
    rng = np.random.default_rng(3)
    z = rng.normal(size=4000)
    y = (rng.random(4000) < 1 / (1 + np.exp(-z))).astype(np.float64)
    shifted = 1 / (1 + np.exp(-(z + 1.5)))
    assert outlook_backtest.best_shift(shifted, y) == pytest.approx(-1.5, abs=0.15)
    assert outlook_backtest.best_shift(np.zeros(0), np.zeros(0)) == 0.0


def test_gf2_and_gf3_read_closings_and_alarms_at_thirty_percent() -> None:
    rows = [(f"d{i}", DAY + timedelta(days=i % 3), "KC", 1.0, 0.4, 0.2, 0.1) for i in range(40)]
    rows += [(f"o{i}", DAY, "KC", 0.0, 0.35, 0.05, 0.05) for i in range(5)]
    scored = frame(rows)
    gf2 = outlook_backtest.gf2(scored)
    assert gf2.detail["caught_30"] == {"s7f": 1.0, "issued": 0.0, "shipped": 0.0}
    assert gf2.detail["e20_none"]["gated"]
    assert gf2.passed
    gf3 = outlook_backtest.gf3(scored, 0.5)
    assert gf3.detail["e20"]["precision_30"]["s7f"] == pytest.approx(40 / 45, abs=1e-5)
    assert gf3.passed  # the baselines raise no alarm: no precision to fall short of
    # Explicit-reason rows: open rows and closings with a named weather reason.
    assert outlook_backtest.explicit(scored, 0.5).height == 5


def test_full_rates_are_the_backtest_fold_rates_for_every_cell() -> None:
    places, labels = _toy()
    usable = pool.usable_labels(labels, places)
    rows = pool.rows_from_labels(usable, places, "no_school")
    delays = pool.rows_from_labels(usable, places, "delay")
    light = world.CONFIG.model.model_copy(
        update={"own_min_days": 4, "level_min_days": 8, "m_grid": (1.0, 4.0, 16.0)}
    )
    test = rows.subset(rows.season == 2023)
    _s, _sd, p_raw, p, q = backtest.fit_predict(
        rows, delays, test, places, [2019, 2020, 2021, 2022], light
    )
    found = outlook_backtest.full_rates(rows, delays, places, [2019, 2020, 2021, 2022], light)
    assert np.allclose(found.p[test.district, test.situation], p_raw, equal_nan=True)
    published, delay = pool.publish_rates(
        found.p[test.district, test.situation], found.q[test.district, test.situation],
        light.floor, light.ceiling,
    )  # fmt: skip
    assert np.allclose(published, p, equal_nan=True)
    assert np.allclose(delay, q, equal_nan=True)


def _toy() -> tuple[pool.Places, pl.DataFrame]:
    """Two districts over five seasons: one closes for every snow warning, one never does."""
    places = pool.make_places(
        ["a", "b"], region=["south", "south"], state=["KS", "KS"],
        county=["20091", "20045"], neighbors={},
    )  # fmt: skip
    rows = []
    for season in range(2019, 2024):
        for i in range(10):
            day = date(season, 12, 1 + i)
            rows.append(("a", day, season, "no_school" if i < 6 else "open", 5, False, "KC"))
            rows.append(("b", day, season, "open" if i else "delayed", 5, False, "KC"))
            rows.append(("a", day, season, "open", 0, False, "KC"))
            rows.append(("b", day, season, "open", 1, False, "KC"))
    labels = pl.DataFrame(
        rows,
        schema=["district", "day", "season", "outcome", "weather", "after", "cluster"],
        orient="row",
    )
    return places, labels


def test_a_fold_scores_every_model_on_the_same_rows_and_the_record_is_the_identity() -> None:
    places, labels = _toy()
    light = world.CONFIG.model.model_copy(
        update={"own_min_days": 4, "level_min_days": 8, "m_grid": (1.0, 4.0, 16.0)}
    )
    usable = pool.usable_labels(labels, places).with_columns(pl.lit(0.0).alias("named"))
    rows = pool.rows_from_labels(usable, places, "no_school")
    delays = pool.rows_from_labels(usable, places, "delay")
    rates = outlook_backtest.full_rates(rows, delays, places, [2019, 2020, 2021, 2022], light)
    test = usable.filter(pl.col("season") == 2023)
    width = len(MOMENTS)
    # Each advisory night of b: an advisory is issued at 22:00 and a warning is the record.
    advisory = test.filter((pl.col("district") == "b") & (pl.col("weather") == 1))
    columns: dict[str, object] = {
        "district": advisory["district"].to_list(),
        "day": advisory["day"].to_list(),
    }
    for k in range(width):
        value = 5 if k == INDEX_OF["05:00"] else (1 if k >= INDEX_OF["22:00"] else 0)
        columns[f"w{k}"] = pl.Series([value] * advisory.height, dtype=pl.Int8)
        columns[f"h{k}"] = pl.Series([0] * advisory.height, dtype=pl.Int8)
    states = pl.DataFrame(columns)
    # The forecast at 20:00 is known (6-9 in) on b's first five advisory nights only.
    known = advisory.head(5)
    codes = pl.DataFrame(
        {
            "district": known["district"],
            "night": known["day"],
            "sample": pl.Series([MOMENTS[INDEX_OF["20:00"]].sample] * known.height, dtype=pl.Int8),
            "code": pl.Series([4] * known.height, dtype=pl.Int8),
        }
    )
    t = np.zeros((outlook.CELLS, outlook.CLASSES))
    t[:, 0] = 0.5
    t[:, 5] = 0.5
    fitted = outlook.Outlook(
        likes=tuple(
            outlook.Like(f, f, h)
            for (_s, _c, h, f) in (outlook.cell_parts(c) for c in range(outlook.CELLS))
        ),
        m_region=8.0, m_state=8.0, nation=t, region=np.zeros((9, outlook.CELLS, 8)),
        state=np.zeros((49, outlook.CELLS, 8)),
        nights_nation=np.full(outlook.CELLS, 30), nights_region=np.zeros((9, outlook.CELLS), int),
        nights_state=np.zeros((49, outlook.CELLS), int),
    )  # fmt: skip
    scored = outlook_backtest.score_fold(test, places, states, codes, fitted, rates, rates, light)
    assert scored.height == test.height * len(outlook_backtest.SCORED)
    record = scored.filter(pl.col("moment") == "05:00")
    assert (record["p_s7f"] == record["p_issued"]).all()
    assert not record["moved"].any()
    # At 20:00 nothing was out for b's advisory nights: half none, half a warning.
    b20 = scored.filter(
        (pl.col("moment") == "20:00") & (pl.col("district") == "b") & (pl.col("weather") == 1)
    )
    assert (b20["c0"] == 0).all()
    forecast = b20.filter(pl.col("f") == 4)
    assert forecast.height == 5
    assert forecast["moved"].all()
    assert not forecast["unknown_f"].any()
    # No forecast code: the identity, as serving gives it (Dark.FORECAST).
    unknown = b20.filter(pl.col("f") == outlook.UNKNOWN)
    assert unknown.height == advisory.height - 5
    assert not unknown["moved"].any()
    assert unknown["unknown_f"].all()
    assert not unknown["fell_back"].any()
    assert (unknown["p_s7f"] == unknown["p_issued"]).all()
    # A warning class row is never moved (a's and b's snow warning nights have no state: c0 is
    # none at 20:00 there too, so they move; the 22:15 advisory rows move with c0 advisory).
    b22 = scored.filter(
        (pl.col("moment") == "22:15") & (pl.col("district") == "b") & (pl.col("weather") == 1)
    )
    assert (b22["c0"] == 1).all()
    issued_rows = scored.filter(pl.col("c0") >= 2)
    assert not issued_rows["moved"].any()


# --- the research plan's checks on every gate's rows (plan sec. 2.1 T4) -------------------------


def raised_on_storms() -> pl.DataFrame:
    """S7-F raises closed advisory rows on two dates and quiet open rows a little."""
    rows = [(f"s{i}", DAY, "KC", 1.0, 0.8, 0.2, 0.3) for i in range(6)]
    rows += [(f"t{i}", DAY + timedelta(days=1), "KC", 1.0, 0.7, 0.3, 0.3) for i in range(3)]
    rows += [(f"q{i}", DAY + timedelta(days=2), "STL", 0.0, 0.05, 0.01, 0.01) for i in range(9)]
    return frame(rows).with_columns(
        pl.when(pl.col("district").str.starts_with("q"))
        .then(pl.lit(0, dtype=pl.Int8))
        .otherwise(pl.lit(1, dtype=pl.Int8))
        .alias("weather")
    )


def test_a_gain_from_raised_chances_on_alert_days_is_no_archive_evidence() -> None:
    scored = raised_on_storms()
    split = outlook_backtest.raised_lowered(scored, "issued")
    assert split["raised"]["rows"] == 18
    alert = split["raised"]["by_label_class"]["alert_days"]
    quiet = split["raised"]["by_label_class"]["none"]
    assert alert["rows"] == 9
    assert alert["closings"] == 9
    assert alert["sse_saved"] == pytest.approx(6 * (0.64 - 0.04) + 3 * (0.49 - 0.09))
    assert quiet["sse_saved"] == pytest.approx(9 * (0.0001 - 0.0025))
    found = outlook_backtest.evidence(scored, "issued")
    assert found["verdict"] == outlook_backtest.RAISED_ON_ALERT_DAYS
    assert not found["archive_evidence"]
    assert found["lowered"] == 0.0
    # One date carries most of it; the two storm dates together pass the total.
    assert [item["day"] for item in found["dates_carrying_the_gain"]] == [
        DAY.isoformat(),
        (DAY + timedelta(days=1)).isoformat(),
    ]


def test_a_gain_that_lowering_carries_is_the_only_kind_called_more_than_no_evidence() -> None:
    rows = [(f"o{i}", DAY + timedelta(days=i % 2), "KC", 0.0, 0.1, 0.6, 0.6) for i in range(6)]
    found = outlook_backtest.evidence(frame(rows), "shipped")
    assert found["verdict"] == outlook_backtest.NOT_RAISES_ALONE
    assert found["archive_evidence"]
    worse = [(f"o{i}", DAY, "KC", 0.0, 0.6, 0.1, 0.1) for i in range(3)]
    assert outlook_backtest.evidence(frame(worse), "issued")["verdict"] == outlook_backtest.NO_GAIN
    quiet_raise = frame([(f"c{i}", DAY, "KC", 1.0, 0.6, 0.1, 0.1) for i in range(3)])
    quiet_raise = quiet_raise.with_columns(pl.lit(0, dtype=pl.Int8).alias("weather"))
    assert (
        outlook_backtest.evidence(quiet_raise, "issued")["verdict"] == outlook_backtest.RAISED_ONLY
    )


def test_the_gain_by_date_marks_the_split_days_chosen_by_outcome() -> None:
    rows = [
        ("a", date(2023, 3, 14), "Hartford & New Haven, CT DMA", 1.0, 0.9, 0.5, 0.4),
        ("b", DAY, "KC", 0.0, 0.2, 0.1, 0.1),
    ]
    found = outlook_backtest.gain_by_date(frame(rows))
    assert [item["day"] for item in found] == ["2023-03-14", DAY.isoformat()]
    assert found[0]["split"]
    assert not found[1]["split"]
    assert found[0]["sse_saved_vs_issued"] == pytest.approx(0.25 - 0.01)
    assert found[1]["sse_saved_vs_shipped"] == pytest.approx(0.01 - 0.04)


def scored_moments() -> pl.DataFrame:
    """The raised-on-storms rows at every scored moment, warned at 22:15 on the first date."""
    base = raised_on_storms().with_columns(
        pl.lit(False).alias("fell_back"), pl.lit(False).alias("unknown_f")
    )
    parts = []
    for label in outlook_backtest.SCORED:
        part = base.with_columns(pl.lit(label).alias("moment"))
        if label == "22:15":
            part = part.with_columns(
                pl.when(pl.col("day") == DAY).then(5).otherwise(pl.col("c0")).alias("c0")
            )
        parts.append(part)
    return pl.concat(parts)


def test_every_gate_row_set_gets_the_checks_and_gf7_says_its_gain_is_no_evidence() -> None:
    scored = scored_moments()
    sets = outlook_backtest.gate_rows(scored)
    assert set(sets) == set(outlook_backtest.GATE_SETS)
    assert sets["daytime"].height == 3 * 18
    assert sets["late_pooled"].height == 4 * 18 - 6
    assert sets["e_22:15"].height == 12
    assert sets["all_20:00"].height == 18
    assert sets["record_storm"].height == 9
    found = outlook_backtest.diagnostics(sets["daytime"])
    for key in ("evidence", "raised_lowered", "strata_size", "strata_c0", "level_free",
                "ranking", "by_date"):  # fmt: skip
        assert found[key]
    assert found["strata_c0"][0]["c0_class"] == "none"
    gf7 = outlook_backtest.gf7(scored)
    assert gf7.passed
    assert gf7.detail["evidence"]["vs_issued"]["verdict"] == outlook_backtest.RAISED_ON_ALERT_DAYS
    assert "no archive evidence" in gf7.detail["note"]
    assert "daytime heads-up option" in gf7.detail["note"]


def test_explicit_reason_checks_say_when_they_cannot_inform() -> None:
    scored = scored_moments()
    gf1 = outlook_backtest.gf1(scored, 50, 0.5)
    explicit = gf1.detail["explicit_reason"]
    assert explicit["closings"] == 0
    assert not explicit["informative"]
    assert explicit["note"] == "not informative on the archive (0 closings on 0 dates)"
    gf3 = outlook_backtest.gf3(scored, 0.5)
    assert gf3.detail["e20"]["closings"] == 9
    assert not gf3.detail["e20"]["informative"]
    one = frame([("d", DAY, "KC", 1.0, 0.5, 0.5, 0.5)])
    assert outlook_backtest.informative(one)["note"] == (
        "not informative on the archive (1 closing on 1 date)"
    )
    many = frame([(f"d{i}", DAY + timedelta(days=i % 3), "KC", 1.0, 0.5, 0.5, 0.5)
                  for i in range(40)])  # fmt: skip
    assert outlook_backtest.informative(many)["informative"]
    assert outlook_backtest.informative(many)["note"] is None


def test_the_season_check_says_it_is_untested_when_no_season_reaches_300_rows() -> None:
    gf1 = outlook_backtest.gf1(scored_moments(), 50, 0.5)
    for base in ("vs_issued", "vs_shipped"):
        assert gf1.detail[base]["season_excess_300"] == {}
        assert gf1.detail[base]["season_rows"] == {"2024": 18}
        assert gf1.detail[base]["seasons_note"] == (
            "untested: no season reaches 300 E20 rows (largest 18)"
        )
    small = outlook_backtest.gf1(scored_moments(), 50, 0.5, min_rows=10)
    assert small.detail["vs_issued"]["seasons_note"] is None
    assert "2024" in small.detail["vs_issued"]["season_excess_300"]


def test_named_dates_report_the_no_warning_yet_closings_apart() -> None:
    rows = [(f"w{i}", date(2024, 1, 19), "KC", 1.0, 0.9, 0.9, 0.9) for i in range(3)]
    rows += [(f"n{i}", date(2024, 1, 19), "KC", 1.0, 0.4, 0.1, 0.1) for i in range(2)]
    scored = frame(rows).with_columns(
        pl.when(pl.col("district").str.starts_with("w")).then(5).otherwise(0).alias("c0")
    )
    found = {item["day"]: item for item in outlook_backtest.named_dates(scored)}["2024-01-19"]
    assert found["closings"] == 5
    assert found["no_warning_yet"] == 2
    assert found["at_30_shipped"] == pytest.approx(0.6)
    assert found["no_warning_yet_at_30_shipped"] == 0.0
    assert found["no_warning_yet_at_30_s7f"] == 1.0
    assert found["no_warning_yet_median_s7f"] == pytest.approx(0.4)


def test_coverage_counts_each_models_unpublishable_rows_and_s7fs_identity_rows() -> None:
    scored = scored_moments().with_columns(
        pl.when(pl.col("district") == "s0")
        .then(float("nan"))
        .otherwise(pl.col("p_issued"))
        .alias("p_issued"),
        pl.when(pl.col("district") == "t0").then(True).otherwise(False).alias("fell_back"),
        pl.when(pl.col("district") == "q0").then(True).otherwise(False).alias("unknown_f"),
    )
    found = outlook_backtest.coverage(scored)
    every = found["rows"]["all"]
    moments = len(outlook_backtest.SCORED)
    assert every["rows"] == 18 * moments
    assert every["nan_issued"] == moments
    assert every["nan_s7f"] == every["nan_shipped"] == 0
    assert every["left_out"] == moments
    assert every["left_out_closings"] == moments
    assert every["s7f_identity_no_rate"] == moments
    assert every["s7f_identity_unknown_forecast"] == moments
    assert found["rows"]["by_season_moment"]["2024|20:00"]["left_out"] == 1
    # s0 is warned at 22:15: not an E(t) row then.
    assert found["e_rows"]["all"]["left_out"] == moments - 1


def test_a_fit_at_the_end_of_its_grid_is_reported() -> None:
    likes = tuple(
        outlook.Like(f, f, h)
        for (_s, _c, h, f) in (outlook.cell_parts(c) for c in range(outlook.CELLS))
    )
    zeros = np.zeros((outlook.CELLS, outlook.CLASSES))
    fitted = outlook.Outlook(
        likes, 2048.0, 512.0, zeros, np.zeros((9, outlook.CELLS, 8)),
        np.zeros((49, outlook.CELLS, 8)), np.zeros(outlook.CELLS, int),
        np.zeros((9, outlook.CELLS), int), np.zeros((49, outlook.CELLS), int),
        trials=((512.0, 512.0, 0.31), (2048.0, 512.0, 0.30)),
    )  # fmt: skip
    found = outlook_backtest.fit_report(fitted, [2018, 2019], outlook.GRID)
    assert found["m_at_grid_edge"] == ["m_region"]
    assert found["loso_log_loss"] == [[512.0, 512.0, 0.31], [2048.0, 512.0, 0.3]]
    assert (
        outlook_backtest.fit_report(fitted, [2018, 2019], outlook_backtest.WIDE_GRID)[
            "m_at_grid_edge"
        ]
        == []
    )
    assert outlook_backtest.fit_report(fitted, [2018], outlook.GRID)["m_at_grid_edge"] == []


def test_failing_cells_name_every_false_check() -> None:
    detail = {
        "vs_issued": {
            "brier_ratio_ok": False,
            "log_loss_lower": False,
            "late_pooled": {"ok": True},
        },
        "explicit_reason": {"ok": False, "informative": False},
        "g1": True,
    }
    assert outlook_backtest.failing_cells(detail) == [
        "vs_issued.brier_ratio_ok",
        "vs_issued.log_loss_lower",
        "explicit_reason.ok",
    ]


def test_the_report_names_each_gates_evidence_and_renders_every_table() -> None:
    scored = scored_moments()
    sets = outlook_backtest.gate_rows(scored)
    gates = [outlook_backtest.gf1(scored, 50, 0.5), outlook_backtest.gf7(scored)]
    metrics = {
        "labels_rule": "per fold",
        "folds": {},
        "coverage": outlook_backtest.coverage(scored),
        "recount": outlook_backtest.recount(scored),
        "gates": {gate.name: gate.as_json() for gate in gates},
        "gate_rows": {name: outlook_backtest.diagnostics(part) for name, part in sets.items()},
        "by_moment": {},
        "named_dates": outlook_backtest.named_dates(scored),
        "delay_e20": {},
    }
    text = outlook_backtest.report_markdown(metrics)
    assert "Training labels: per fold." in text
    assert "| GF7 | pass |" in text
    assert "daytime: " + outlook_backtest.RAISED_ON_ALERT_DAYS in text
    assert "- GF7: passes on the numbers, but the gain is no archive evidence" in text
    assert "- GF1: untested: no season reaches 300 E20 rows (largest 18)" in text
    assert "## Gain by date: daytime" in text
