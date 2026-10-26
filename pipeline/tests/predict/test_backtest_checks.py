"""Backtest v2's report-only checks of a candidate against today's model (synthetic rows)."""

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from snowlight.predict.backtest_terms import (
    SPLIT_MARKET_DAYS,
    STRATUM_TOLERANCE,
    DropTraining,
    Scored,
    best_shift,
    busiest_dates,
    checks_markdown,
    date_bootstrap,
    drop_one_date,
    drop_training_dates,
    forecast_stratum,
    level_free,
    raised_lowered,
    run_checks,
    split_market_days,
    storm_briers,
    strata_check,
    within_day_ranking,
)

D1, D2, D3 = (date(2023, 2, 28).toordinal(), date(2023, 3, 14).toordinal(),
              date(2024, 1, 16).toordinal())  # fmt: skip


def scored(**changes: object) -> Scored:
    base: dict[str, object] = {
        "y": np.array([1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0]),
        "p_base": np.array([0.6, 0.6, 0.6, 0.6, 0.5, 0.5, 0.5, 0.1]),
        "p_new": np.array([0.8, 0.3, 0.7, 0.5, 0.6, 0.6, 0.4, 0.1]),
        "day": np.array([D1, D1, D2, D2, D3, D3, D3, D3]),
        "market": ("ny", "ny", "ny", "ny", "ct", "ct", "ct", "ct"),
        "weather": np.array([1, 1, 1, 1, 5, 5, 5, 0]),
        "stratum": ("a", "a", "a", "a", "b", "b", "b", "c"),
    }
    base.update(changes)
    return Scored(**base)  # type: ignore[arg-type]


def test_strata_of_class_bucket_and_region() -> None:
    assert forecast_stratum(1, 0, northeast=True) == "advisory | under 0.5 in | northeast"
    assert forecast_stratum(1, 3, northeast=False) == "advisory | 4 to 6 in | rest"
    assert forecast_stratum(1, 7, northeast=False) == "advisory | ice | rest"
    assert forecast_stratum(5, 1, northeast=True) == "class 5 | under 2 in | northeast"
    assert forecast_stratum(5, 3, northeast=True) == "class 5 | 2 to 6 in | northeast"
    assert forecast_stratum(5, 5, northeast=True) == "class 5 | 9 in or more | northeast"
    assert forecast_stratum(1, -1, northeast=True) == "advisory | unknown | northeast"
    assert forecast_stratum(1, 10, northeast=True) == "advisory | under 0.5 in | northeast"


def test_a_stratum_is_checked_only_with_30_rows_on_2_dates() -> None:
    rows = 40
    found = strata_check(
        scored(
            y=np.zeros(rows),
            p_base=np.full(rows, 0.1),
            p_new=np.full(rows, 0.3),
            day=np.array([D1] * 20 + [D2] * 20),
            market=("ny",) * rows,
            weather=np.ones(rows, dtype=np.int64),
            stratum=("a",) * 30 + ("b",) * 10,
        )
    )
    by = {item.stratum: item for item in found}
    assert by["a"].checked
    assert by["a"].worse  # 0.09 against 0.01: worse by 0.08
    assert by["a"].brier_new - by["a"].brier_base > STRATUM_TOLERANCE
    assert not by["b"].checked
    assert not by["b"].worse


def test_one_test_date_left_out() -> None:
    found = drop_one_date(scored())
    assert [d for d, _n, _g in found.by_date] == [D1, D2, D3]
    assert [n for _d, n, _g in found.by_date] == [2, 2, 3]  # storm rows only
    assert found.gain > 0
    assert found.holds
    worse_on_one = scored(p_new=np.array([0.8, 0.3, 0.7, 0.5, 0.1, 0.1, 0.9, 0.1]))
    assert not drop_one_date(worse_on_one).holds


def test_the_bootstrap_resamples_dates() -> None:
    found = date_bootstrap(scored(), draws=500, seed=1)
    assert found.dates == 3
    assert found.difference < 0
    assert found.low <= found.difference <= found.high
    assert not found.worse
    same = date_bootstrap(scored(p_new=scored().p_base), draws=50)
    assert same.low == same.high == 0.0
    nothing = date_bootstrap(scored(weather=np.zeros(8, dtype=np.int64)))
    assert nothing.dates == 0


def test_raised_and_lowered_storm_rows() -> None:
    by = {split.name: split for split in raised_lowered(scored())}
    assert by["raised"].rows == 4
    assert by["lowered"].rows == 3
    assert by["unchanged"].rows == 0  # the no-alert row is not a storm row
    assert by["raised"].gain == pytest.approx(
        (0.16 + 0.16 + 0.25 + 0.25) - (0.04 + 0.09 + 0.16 + 0.16)
    )


def test_level_free_takes_away_each_models_class_level() -> None:
    y = np.array([1.0] * 8 + [0.0] * 2)
    shift, found = best_shift(np.full(10, 0.5), y)
    assert shift == pytest.approx(np.log(4), abs=0.01)  # 0.8 closed: the shift to 0.8
    assert found == pytest.approx(0.16, abs=1e-3)
    assert best_shift(np.zeros(0), np.zeros(0))[1] != best_shift(np.zeros(0), np.zeros(0))[1]
    rows = level_free(scored())
    assert [item.weather for item in rows] == [1, 5]
    assert all(item.brier_base <= 0.25 + 1e-4 for item in rows)  # on a 0.01 grid


def test_within_day_ranking_over_market_days_with_both_outcomes() -> None:
    found = within_day_ranking(scored())
    # ny on D1: 1 pair; ny on D2: 1 pair; ct on D3: 2 closed x 2 open (its no-alert row too).
    assert found.market_days == 3
    assert found.pairs == 6
    assert found.share_base == pytest.approx((0.5 + 0.5 + 1 + 2) / 6)  # ties count half
    assert found.share_new == pytest.approx(1.0)
    apart = within_day_ranking(scored(), frozenset({(D1, "ny")}))
    assert apart.market_days == 2
    assert apart.apart_market_days == 1
    assert apart.apart_pairs == 1
    assert apart.apart_share_new == 1.0
    # The pre-registered figure over every market-day keeps the ones reported apart.
    for item in (found, apart):
        assert item.all_market_days == 3
        assert item.all_pairs == 6
        assert item.all_share_base == pytest.approx(found.share_base)
        assert item.all_share_new == pytest.approx(found.share_new)
    assert apart.pairs + apart.apart_pairs == apart.all_pairs
    assert (date(2023, 2, 28).toordinal(), SPLIT_MARKET_DAYS[0][1]) in split_market_days()


def test_one_training_date_left_out_of_every_fit() -> None:
    day = np.array([D1, D1, D2, D3, D3, D3])
    used = np.array([True, True, True, True, True, False])
    assert busiest_dates(day, used, 2) == [D1, D3]
    calls: list[int] = []

    def score(exclude: object) -> tuple[float, float]:
        if exclude is None:
            return 0.2, 0.1
        calls.append(int(np.asarray(exclude).sum()))
        return 0.2, 0.15

    found = drop_training_dates(score, day, [D1, D3])
    assert found.brier == (0.2, 0.1)
    assert found.by_date == ((D1, 0.2, 0.15), (D3, 0.2, 0.15))
    assert calls == [2, 3]


def test_the_checks_report_names_its_veto_reasons() -> None:
    found = run_checks(scored(), draws=200)
    assert found.harm == []
    text = checks_markdown(found, "Checks")
    assert "Veto reasons seen here: none." in text
    assert "## P4" in text
    assert "## Within-day ranking" in text
    assert "Every market-day with both outcomes (pre-registered):" in text
    assert "The split market-days alone" in text
    worse = run_checks(scored(p_new=1 - scored().y), draws=200)
    assert any("worse" in reason for reason in worse.harm)
    assert storm_briers(scored())[1] < storm_briers(scored())[0]


def test_the_p8_rows_print_a_dash_where_a_brier_has_no_rows() -> None:
    nan = float("nan")
    found = replace(
        run_checks(scored(), draws=50),
        drop_training=DropTraining((0.1, 0.09), ((D1, 0.11, 0.10123456), (D2, nan, nan))),
    )
    text = checks_markdown(found, "Checks")
    assert f"| {date.fromordinal(D1).isoformat()} | 0.11000 | 0.10123 | -0.00877 |" in text
    assert "candidate less today's model -0.01000" in text
    assert f"| {date.fromordinal(D2).isoformat()} | - | - | - |" in text
    assert "nan" not in text
