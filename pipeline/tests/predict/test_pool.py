"""The pooled chain's arithmetic, its monotonicity, the scope it names, and the tuning."""

from itertools import pairwise

import numpy as np
import polars as pl
import pytest

from snowlight.predict.pool import (
    SCOPES,
    SITUATION_INDEX,
    Places,
    Rows,
    Rules,
    Strengths,
    chain,
    effective_situations,
    level_counts,
    log_loss,
    loso_counts,
    loso_predictions,
    make_places,
    make_rules,
    publish_rates,
    rows_from_labels,
    tables_from_rows,
    tune,
    usable_labels,
)

SNOW = SITUATION_INDEX["snow_warning"]
NONE = SITUATION_INDEX["none"]
SPEC = Rules(own_min_days=4, level_min_days=8)


def places() -> Places:
    # a, b, c share a county; d is the same state; e is another region.
    return make_places(
        ["a", "b", "c", "d", "e"],
        region=["ohio_valley"] * 4 + ["southwest"],
        state=["MO", "MO", "MO", "MO", "UT"],
        county=["29095", "29095", "29095", "29047", None],
        neighbors={"a": ["b"], "b": ["a", "c"], "c": ["b"]},
    )


def counts(own: dict[str, tuple[int, int]], situation: int = SNOW) -> tuple[np.ndarray, np.ndarray]:
    found = places()
    y = np.zeros((found.size, 10))
    n = np.zeros((found.size, 10))
    for district, (closed, days) in own.items():
        i = found.position()[district]
        y[i, situation], n[i, situation] = closed, days
    return y, n


def test_the_chain_arithmetic() -> None:
    p = places()
    y, n = counts({"a": (6, 10), "b": (1, 4), "d": (0, 6), "e": (0, 2)})
    m = Strengths.uniform(2.0)
    found = chain(level_counts(p, y, n), m, rules=SPEC)
    nation = (7 + 1) / (22 + 2)
    region = (7 + 2 * nation) / (20 + 2)
    state = (7 + 2 * region) / (20 + 2)
    county_a = (7 + 2 * state) / (14 + 2)
    nearby_a = (1 + 2 * county_a) / (4 + 2)  # b only
    assert found.rate["nation"][0, SNOW] == pytest.approx(nation)
    assert found.rate["region"][0, SNOW] == pytest.approx(region)
    assert found.rate["state"][0, SNOW] == pytest.approx(state)
    assert found.rate["county"][0, SNOW] == pytest.approx(county_a)
    assert found.rate["nearby"][0, SNOW] == pytest.approx(nearby_a)
    # a: 10 own days; its nearby (4 days) does not qualify, its county (14) does.
    assert found.own[0, SNOW]
    assert SCOPES[found.scope[0, SNOW]] == "county"
    assert found.p[0, SNOW] == pytest.approx((6 + 2 * county_a) / (10 + 2))
    # c has no days of its own: pooled, from its county.
    assert not found.own[2, SNOW]
    assert found.p[2, SNOW] == pytest.approx(found.rate["county"][2, SNOW])
    # e (Utah) has 2 days: under the minimum, and nothing below its region qualifies.
    assert SCOPES[found.scope[4, SNOW]] == "region"
    assert found.p[4, SNOW] == pytest.approx(found.rate["region"][4, SNOW])


def test_more_closings_never_lower_the_rate() -> None:
    p = places()
    m = Strengths.uniform(4.0)
    rates = []
    for closed in range(11):
        y, n = counts({"a": (closed, 10), "b": (2, 10)})
        rates.append(chain(level_counts(p, y, n), m, rules=SPEC).p[0, SNOW])
    assert all(later >= earlier for earlier, later in pairwise(rates))
    assert rates[-1] > rates[0]


def test_an_unseen_district_takes_its_level_and_publish_rounds_within_bounds() -> None:
    p = places()
    y, n = counts({"a": (4, 10), "b": (3, 10)}, situation=NONE)
    found = chain(level_counts(p, y, n), Strengths.uniform(8.0), rules=SPEC)
    assert found.p[2, NONE] == pytest.approx(found.rate["nearby"][2, NONE])
    assert SCOPES[found.scope[2, NONE]] == "nearby"
    no_school, delay = publish_rates(
        np.array([0.0001, 0.5, 0.999]), np.array([0.5, 1.0, 1.0]), 0.01, 0.99
    )
    assert no_school.tolist() == [0.01, 0.5, 0.99]
    assert delay.tolist() == [0.5, 0.5, 0.01]
    assert all(a + b <= 1 for a, b in zip(no_school, delay, strict=True))


def labels() -> pl.DataFrame:
    rows = []
    for season in (2021, 2022, 2023):
        for i in range(8):
            rows.append(("a", season, "no_school" if i < 5 else "open", 5, False))
            rows.append(("b", season, "delayed" if i < 2 else "open", 5, False))
            rows.append(("c", season, "open", 0, i == 0))
        rows.append(("c", season, "unknown", 0, False))
        rows.append(("z", season, "no_school", 5, False))  # not in the places
    return pl.DataFrame(
        rows, schema=["district", "season", "outcome", "weather", "after"], orient="row"
    )


def test_rows_and_tables_from_labels() -> None:
    p = places()
    frame = labels()
    usable = usable_labels(frame, p)
    assert "unknown" not in usable["outcome"].to_list()
    assert "z" not in usable["district"].to_list()
    rows = rows_from_labels(usable, p, "no_school")
    delay = rows_from_labels(usable, p, "delay")
    assert len(rows) == 72
    assert len(delay) == 72 - 15
    assert set(rows.situation.tolist()) == {SNOW, NONE, SITUATION_INDEX["none_after"]}
    tables = tables_from_rows(rows, p, [2021, 2022, 2023])
    y, n = tables.total()
    assert y[0, SNOW] == 15
    assert n[0, SNOW] == 24
    y1, n1 = tables.total([2021])
    assert y1[0, SNOW] == 5
    assert n1[0, SNOW] == 8


def test_tuning_leaves_each_season_out_and_picks_from_the_grid() -> None:
    p = places()
    rows = rows_from_labels(labels(), p, "no_school")
    seasons = [2021, 2022, 2023]
    tables = tables_from_rows(rows, p, seasons)
    held = loso_counts(p, tables, seasons)
    for season, level in held.items():
        y, _n = tables.total([s for s in seasons if s != season])
        assert np.array_equal(level.y["own"], y)
    p_loso = loso_predictions(rows, held, Strengths.uniform(4.0), rules=SPEC)
    assert not np.isnan(p_loso).any()
    tuned = tune(rows, p, tables, seasons, [1, 4, 16], sweeps=1, rules=SPEC)
    values = {m for groups in tuned.strengths.m.values() for m in groups.values()}
    assert values <= {1.0, 4.0, 16.0, 8.0}
    assert tuned.trials
    lone = tune(rows, p, tables, [2021], [1, 4], rules=SPEC)
    assert lone.strengths == Strengths.uniform(8.0)
    assert log_loss(np.array([0.5]), np.array([1.0])) == pytest.approx(np.log(2))


def test_places_must_be_sorted() -> None:
    with pytest.raises(ValueError, match="sorted"):
        make_places(["b", "a"], [None, None], [None, None], [None, None], {})
    empty = Rows(np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0))
    assert len(empty) == 0


TRUE = make_rules(
    own_min_days=4,
    level_min_days=8,
    nation_min_days=10,
    almost_share=0.05,
    floor=0.01,
    ceiling=0.99,
    fallback={"lake_snow": "snow_warning", "none_after": "none"},
)


def test_a_named_level_is_true_of_its_own_days_else_the_base_moves_up() -> None:
    p = places()
    # Missouri (a-d) closed 2 of 40 warnings; Utah (e) 36 of 40. With m = 64 Missouri's 40
    # days hold under half the weight: its shrunk rate is far from its own 5%, so the base
    # names a level whose days set it, the nation (38 of 80), never "Missouri's state".
    y, n = counts({"a": (1, 10), "b": (1, 10), "c": (0, 10), "d": (0, 10), "e": (36, 40)})
    heavy = chain(level_counts(p, y, n), Strengths.uniform(64.0), rules=TRUE)
    assert SCOPES[heavy.scope[0, SNOW]] == "nation"
    assert heavy.p[0, SNOW] == pytest.approx(heavy.rate["nation"][0, SNOW])
    assert not heavy.own[0, SNOW]
    # Light pooling: the county's 30 days set its own rate, so it is named; what it names is
    # within the tolerance of what those days did.
    light = chain(level_counts(p, y, n), Strengths.uniform(1.0), rules=TRUE)
    raw = {"county": 2 / 30, "nearby": 2 / 20}
    for district in (0, 1, 2, 3):
        scope = SCOPES[light.scope[district, SNOW]]
        assert scope != "nation"
        level_y = level_counts(p, y, n).y[scope][district, SNOW]
        level_n = level_counts(p, y, n).n[scope][district, SNOW]
        shown = TRUE.published(light.p[district : district + 1, SNOW])[0]
        if not light.own[district, SNOW]:
            assert abs(shown - level_y / level_n) <= 0.05 + 1e-9, (district, scope)
    assert SCOPES[light.scope[0, SNOW]] in raw
    # Every published p is true of the level it names, or the scope moved up the chain.
    for strength in (1.0, 4.0, 16.0, 64.0, 1024.0):
        found = chain(level_counts(p, y, n), Strengths.uniform(strength), rules=TRUE)
        counted = level_counts(p, y, n)
        for district in range(p.size):
            scope = SCOPES[found.scope[district, SNOW]]
            if found.own[district, SNOW]:
                level_y, level_n = y[district, SNOW], n[district, SNOW]
            else:
                level_y = counted.y[scope][district, SNOW]
                level_n = counted.n[scope][district, SNOW]
            shown = TRUE.published(found.p[district : district + 1, SNOW])[0]
            assert abs(shown - level_y / level_n) <= 0.05 + 1e-9, (strength, district, scope)


def test_a_region_with_no_labeled_days_is_never_named() -> None:
    p = places()
    y, n = counts({"a": (5, 10), "b": (5, 10), "c": (5, 10), "d": (5, 10)})
    found = chain(level_counts(p, y, n), Strengths.uniform(1.0), rules=TRUE)
    # Utah's region (e) has no days: it takes the nation, said as the nation.
    assert SCOPES[found.scope[4, SNOW]] == "nation"


def test_a_situation_without_enough_days_takes_its_fallback_never_a_uniform_prior() -> None:
    p = places()
    y, n = counts({"a": (6, 10), "b": (5, 10)})  # snow warnings only
    found = chain(level_counts(p, y, n), Strengths.uniform(4.0), rules=TRUE)
    lake = SITUATION_INDEX["lake_snow"]
    # No lake effect day anywhere: never (0 + 1) / (0 + 2) = 50%; the snow warning rates.
    assert found.situation[0, lake] == SNOW
    assert found.p[0, lake] == pytest.approx(found.p[0, SNOW])
    assert not np.isclose(found.p[:, lake], 0.5).any()
    # A situation with no fallback and no days is not modeled at all (-1: nothing published).
    tropical = SITUATION_INDEX["tropical"]
    assert found.situation[0, tropical] == -1
    # The nation's own count must be true of it too: 10 days needed.
    mapping = effective_situations(y.sum(axis=0), n.sum(axis=0), TRUE)
    assert mapping[SNOW] == SNOW
    thin = effective_situations(np.full(10, 1.0), np.full(10, 9.0), TRUE)
    assert (thin == -1).all()
    with pytest.raises(ValueError, match="unknown situation"):
        make_rules(
            own_min_days=4,
            level_min_days=8,
            nation_min_days=10,
            almost_share=0.05,
            floor=0.01,
            ceiling=0.99,
            fallback={"lake_snow": "sleet"},
        )
