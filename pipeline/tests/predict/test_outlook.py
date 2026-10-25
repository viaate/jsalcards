"""The outlook model of S7-F (spec-f s. 6): back-off, shrinkage, what a sentence may say, the
v3 artifact and the one chance function. SYNTHETIC cases only."""

import gzip
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from snowlight.predict import outlook
from snowlight.predict.outlook import (
    ANY_HEADS,
    CELLS,
    CLASSES,
    Like,
    OutlookMode,
    backoff,
    case_counts,
    cell_index,
    cell_of,
    cell_parts,
    chance,
    fit,
    training_cases,
)
from snowlight.predict.outlook_states import INDEX_OF, MOMENTS, season_cases
from snowlight.predict.pool import publish_rates
from snowlight.predict.situations import WeatherClass

KS = outlook.STATES.index("KS")
MO = outlook.STATES.index("MO")


def nights(count: int, start: date = date(2024, 12, 2)) -> list[date]:
    return [start + timedelta(days=i) for i in range(count)]


def presence(cells: dict[int, int], total: int = 60) -> np.ndarray:
    """Nation presence where each cell held a case on its first ``n`` nights."""
    found = np.zeros((total, CELLS), dtype=np.bool_)
    for cell, count in cells.items():
        found[:count, cell] = True
    return found


def test_cells_round_trip() -> None:
    for cell in (0, 1, 13, 14, 83, 84, CELLS - 1):
        slot, c0, heads, f = cell_parts(cell)
        assert cell_index(slot, c0, heads, f) == cell
        assert (
            int(cell_of(np.array([slot]), np.array([c0]), np.array([heads]), np.array([f]))[0])
            == cell
        )
    assert cell_parts(CELLS - 1) == (7, 1, 5, 13)


def test_back_off_merges_the_nearer_bucket_first_then_any_forecast_then_any_heads_up() -> None:
    # Slot 5, no class, no heads-up: 6-9 in (bucket 4) on 5 nights, 9+ (5) on 10, 4-6 (3) on
    # 10: 4 and 5 are equally near, so the larger amounts come first (15 nights), then 3 (but
    # the nights overlap: presence is per night, so 3 adds none and the ladder goes on to 2).
    cells = {
        cell_index(5, 0, 0, 4): 5,
        cell_index(5, 0, 0, 5): 10,
        cell_index(5, 0, 0, 3): 10,
        cell_index(5, 0, 0, 2): 30,
        cell_index(5, 0, 0, 9): 2,
        cell_index(5, 0, 1, 0): 3,
        cell_index(5, 0, 2, 0): 30,
    }
    likes = backoff(presence(cells))
    assert likes[cell_index(5, 0, 0, 2)] == Like(2, 2, 0)  # 30 nights: stays
    assert likes[cell_index(5, 0, 0, 4)] == Like(2, 5, 0)
    assert likes[cell_index(5, 0, 0, 5)] == Like(2, 5, 0)
    # Cold with 2 nights: its whole ladder holds only 2: any forecast with no heads-up (30).
    assert likes[cell_index(5, 0, 0, 9)] == Like(0, 13, 0)
    # A watch, quiet, 3 nights: any forecast with the watch still 3, then any heads-up.
    assert likes[cell_index(5, 0, 1, 0)] == Like(0, 13, ANY_HEADS)
    assert likes[cell_index(5, 0, 2, 0)] == Like(0, 0, 2)
    # Nothing anywhere in slot 1: the nation still answers with its widest cell.
    assert likes[cell_index(1, 1, 3, 7)] == Like(0, 13, ANY_HEADS)


def _cases(rows: list[tuple[int, date, str, int, int, int, int, int, int]]) -> pl.DataFrame:
    """(season, night, state, moment, c0, h, f, target, n) rows as a case frame."""
    frame = pl.DataFrame(
        rows,
        schema={
            "season": pl.Int32, "night": pl.Date, "state": pl.String, "moment": pl.Int8,
            "c0": pl.Int8, "h": pl.Int8, "f": pl.Int8, "target": pl.Int8, "n": pl.Int64,
        },
        orient="row",
    )  # fmt: skip
    return training_cases(frame)


def world_cases() -> pl.DataFrame:
    """Two seasons of slot 5 (20:00) cases in KS and MO: quiet nights stay none; 6-9 in of
    snow with nothing issued ends in a warning 3 times in 5 in KS and 1 in 5 in MO."""
    k = INDEX_OF["20:00"]
    rows = []
    for season, start in ((2022, date(2022, 12, 1)), (2023, date(2023, 12, 1))):
        for night in nights(30, start):
            rows.append((season, night, "KS", k, 0, 0, 0, 0, 500))
            rows.append((season, night, "MO", k, 0, 0, 0, 0, 500))
            rows.append((season, night, "KS", k, 0, 0, 4, 5, 3))
            rows.append((season, night, "KS", k, 0, 0, 4, 0, 2))
            rows.append((season, night, "MO", k, 0, 0, 4, 5, 1))
            rows.append((season, night, "MO", k, 0, 0, 4, 1, 4))
    # an early-moment row and a warning row train nothing
    rows.append((2022, date(2022, 12, 1), "KS", INDEX_OF["05:00"], 0, 0, 0, 0, 999))
    rows.append((2022, date(2022, 12, 1), "KS", k, 5, 0, 4, 5, 999))
    return _cases(rows)


def test_t_rows_sum_to_one_at_every_place_and_shrink_toward_the_place_above() -> None:
    found = fit(world_cases(), [2022, 2023])
    for table in (
        found.t_nation(),
        found.t_region().reshape(-1, CLASSES),
        found.t_state().reshape(-1, CLASSES),
    ):
        sums = table.sum(axis=1)
        assert np.allclose(sums[sums > 0], 1.0)
    cell = cell_index(5, 0, 0, 4)
    nation = found.t_nation()[cell]
    assert nation[WeatherClass.SNOW_WARNING] == pytest.approx(0.4)  # (3 + 1) / 10
    ks = found.t_state()[KS, cell]
    mo = found.t_state()[MO, cell]
    assert ks[WeatherClass.SNOW_WARNING] > nation[WeatherClass.SNOW_WARNING] > mo[5]
    assert found.m_region in outlook.GRID
    assert found.m_state in outlook.GRID
    assert found.trials  # leave-one-season-out over the two seasons
    region = outlook.REGION_OF_STATE[KS]
    n_r = found.region[region, cell]
    expected_region = (n_r + found.m_region * nation) / (n_r.sum() + found.m_region)
    assert np.allclose(found.t_region()[region, cell], expected_region)
    n_s = found.state[KS, cell]
    expected = (n_s + found.m_state * expected_region) / (n_s.sum() + found.m_state)
    assert np.allclose(ks, expected)
    # The rows that train nothing were left out: the quiet cell holds the 500s only.
    quiet = cell_index(5, 0, 0, 0)
    assert found.nation[quiet].sum() == 2 * 30 * 1000


def test_one_season_keeps_the_start_strength() -> None:
    found = fit(world_cases(), [2022])
    assert (found.m_region, found.m_state) == (outlook.START_M, outlook.START_M)
    assert not found.trials


def test_the_sentence_names_the_most_specific_place_with_twenty_nights_and_its_raw_share() -> None:
    found = fit(world_cases(), [2022, 2023])
    cell = cell_index(5, 0, 0, 4)
    scope, share, hit, total = found.says(cell, KS, int(WeatherClass.SNOW_WARNING))
    assert (scope, hit, total) == ("state", 180, 300)
    assert share == pytest.approx(0.6)
    assert found.nights_state[KS, cell] == 60
    # A state with no case of the cell: its region (Arkansas shares the South with Kansas;
    # New York's Northeast holds none), else the nation.
    ar = outlook.STATES.index("AR")
    scope, share, hit, total = found.says(cell, ar, int(WeatherClass.SNOW_WARNING))
    assert scope == "region"  # the South holds Kansas's 60 nights
    assert (hit, total) == (180, 300)
    ny = outlook.STATES.index("NY")
    scope, share, hit, total = found.says(cell, ny, int(WeatherClass.SNOW_WARNING))
    assert (scope, hit, total) == ("nation", 240, 600)


def test_a_cell_with_no_case_anywhere_reads_as_the_identity() -> None:
    found = fit(world_cases(), [2022, 2023])
    dist = found.distribution(
        np.array([1]), np.array([1]), np.array([3]), np.array([7]), np.array([KS])
    )
    assert dist[0, WeatherClass.ADVISORY] == 1.0
    assert dist.sum() == 1.0


def test_the_artifact_round_trips(tmp_path: Path) -> None:
    found = fit(world_cases(), [2022, 2023])
    path = tmp_path / "model-f.json.gz"
    size = outlook.write_artifact(path, {"schema_version": 2}, found)
    assert size == path.stat().st_size
    assert size < 400_000
    rates, back = outlook.read_artifact(path)
    assert rates == {"schema_version": 2}
    assert back.likes == found.likes
    assert np.allclose(back.t_state(), found.t_state())
    assert np.array_equal(back.nights_state, found.nights_state)
    assert back.says(cell_index(5, 0, 0, 4), KS, 5) == found.says(cell_index(5, 0, 0, 4), KS, 5)
    with pytest.raises(ValueError, match="not an outlook"):
        outlook.Outlook.from_json({"version": 2})
    path.write_bytes(gzip.compress(b'{"version": 2}'))
    with pytest.raises(ValueError, match="05:00"):
        outlook.read_artifact(path)


# --- the chance ---------------------------------------------------------------------------------

P = np.array([[0.02, 0.40, 0.5, 0.6, 0.7, 0.9, 0.95, 0.97]])
Q = np.array([[0.05, 0.30, 0.2, 0.2, 0.2, 0.1, 0.1, 0.1]])
T = np.array([[0.3, 0.2, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0]])


WARNINGS = [weather for weather in WeatherClass if weather >= outlook.C0_VALUES]


def test_every_class_from_two_up_is_a_warning_class() -> None:
    assert len(WARNINGS) == CLASSES - outlook.C0_VALUES == 6


@pytest.mark.parametrize(
    ("c0", "before", "mode"),
    [
        *[(int(weather), True, OutlookMode.ON) for weather in WARNINGS],  # a warning issued
        (0, False, OutlookMode.ON),  # from 05:00 D
        (1, False, OutlookMode.ON),
        (0, True, OutlookMode.OFF),
        (1, True, OutlookMode.SHADOW),
    ],
)
def test_the_chance_is_the_class_own_rate_when_the_outlook_does_not_apply(
    c0: int, before: bool, mode: OutlookMode
) -> None:
    found = chance(P, Q, np.array([c0]), T, np.array([before]), mode=mode, floor=0.01, ceiling=0.99)
    p, delay = publish_rates(P[:, c0], Q[:, c0], 0.01, 0.99)
    assert found.p[0] == p[0]
    assert found.delay[0] == delay[0]
    assert found.p_raw[0] == P[0, c0]
    assert not found.outlook[0]


def test_without_t_the_chance_is_the_identity_even_when_on() -> None:
    found = chance(
        P, Q, np.array([0]), None, np.array([True]), mode=OutlookMode.ON, floor=0.01, ceiling=0.99
    )
    assert found.p_raw[0] == P[0, 0]


def test_the_chance_is_the_mixture_of_the_class_rates_and_its_delay_adds_up() -> None:
    found = chance(
        P, Q, np.array([0]), T, np.array([True]), mode=OutlookMode.ON, floor=0.01, ceiling=0.99
    )
    mix = float((T * P).sum())
    delay = float((T * (1 - P) * Q).sum())
    assert found.p_raw[0] == pytest.approx(mix)
    assert found.p[0] == round(mix, 2)
    assert found.delay[0] == pytest.approx(round((1 - round(mix, 2)) * delay / (1 - mix), 2))
    assert found.p[0] + found.delay[0] <= 1.0
    assert found.outlook[0]


def test_a_batch_mixes_outlook_rows_with_identity_rows() -> None:
    p = np.repeat(P, 6, axis=0)
    q = np.repeat(Q, 6, axis=0)
    t = np.repeat(T, 6, axis=0)
    c0 = np.array([0, 5, 1, 0, 2, 7])
    before = np.array([True, True, True, False, True, True])
    found = chance(p, q, c0, t, before, mode=OutlookMode.ON, floor=0.01, ceiling=0.99)
    mix = float((T * P).sum())
    assert found.outlook.tolist() == [True, False, True, False, False, False]
    assert not found.fell_back.any()
    for row in (0, 2):
        assert found.p_raw[row] == pytest.approx(mix)
    for row in (1, 3, 4, 5):
        assert found.p_raw[row] == P[0, c0[row]]
        alone = chance(
            P, Q, c0[row : row + 1], T, before[row : row + 1],
            mode=OutlookMode.ON, floor=0.01, ceiling=0.99,
        )  # fmt: skip
        assert found.p[row] == alone.p[0]
        assert found.delay[row] == alone.delay[0]


def test_a_class_with_no_rate_and_no_weight_leaves_the_mixture_whole() -> None:
    p = P.copy()
    q = Q.copy()
    p[0, 2] = np.nan  # T[2] is 0
    q[0, 3] = np.nan  # T[3] is 0
    found = chance(
        p, q, np.array([0]), T, np.array([True]), mode=OutlookMode.ON, floor=0.01, ceiling=0.99
    )
    assert found.p_raw[0] == pytest.approx(float((T * P).sum()))
    assert np.isfinite(found.p).all()
    assert np.isfinite(found.delay).all()
    assert found.outlook[0]
    assert not found.fell_back[0]


@pytest.mark.parametrize("rate", ["p", "q"])
def test_a_weighted_class_with_no_rate_gives_the_identity_never_nan(rate: str) -> None:
    p = P.copy()
    q = Q.copy()
    (p if rate == "p" else q)[0, 5] = np.nan  # T[5] is 0.5
    found = chance(
        p, q, np.array([1]), T, np.array([True]), mode=OutlookMode.ON, floor=0.01, ceiling=0.99
    )
    own_p, own_delay = publish_rates(P[:, 1], Q[:, 1], 0.01, 0.99)
    assert found.p[0] == own_p[0]
    assert found.delay[0] == own_delay[0]
    assert not found.outlook[0]
    assert found.fell_back[0]


def test_an_all_zero_t_row_gives_the_identity() -> None:
    t = np.vstack([T, np.zeros_like(T)])
    found = chance(
        np.repeat(P, 2, axis=0), np.repeat(Q, 2, axis=0), np.array([0, 0]), t,
        np.array([True, True]), mode=OutlookMode.ON, floor=0.01, ceiling=0.99,
    )  # fmt: skip
    assert found.outlook.tolist() == [True, False]
    assert found.fell_back.tolist() == [False, True]
    assert found.p_raw[1] == P[0, 0]


@pytest.mark.parametrize(
    "bad",
    [
        np.array([[0.3, 0.2, 0.0, 0.0, 0.0, 0.4, 0.0, 0.0]]),  # sums to 0.9
        np.array([[0.3, 0.2, np.nan, 0.0, 0.0, 0.5, 0.0, 0.0]]),
        np.array([[0.3, 0.2, -0.1, 0.1, 0.0, 0.5, 0.0, 0.0]]),
        np.array([[0.5, 0.5]]),  # not one weight per class
    ],
)
def test_a_t_row_that_is_not_a_distribution_is_refused(bad: np.ndarray) -> None:
    with pytest.raises(ValueError, match="T"):
        chance(
            P, Q, np.array([0]), bad, np.array([True]),
            mode=OutlookMode.ON, floor=0.01, ceiling=0.99,
        )  # fmt: skip


def test_a_bad_t_row_on_a_warning_row_is_not_read() -> None:
    bad = np.array([[0.3, 0.2, 0.0, 0.0, 0.0, 0.4, 0.0, 0.0]])
    found = chance(
        P, Q, np.array([5]), bad, np.array([True]), mode=OutlookMode.ON, floor=0.01, ceiling=0.99
    )
    assert found.p_raw[0] == P[0, 5]


def test_class_rates_take_the_day_after_for_none_and_advisory_only() -> None:
    from snowlight.predict.pool import SITUATION_INDEX  # noqa: PLC0415

    matrix = np.arange(10, dtype=np.float64)[None, :] / 10
    found = outlook.class_rates(matrix, np.array([0, 0]), np.array([False, True]))
    assert found[0, 0] == matrix[0, SITUATION_INDEX["none"]]
    assert found[1, 0] == matrix[0, SITUATION_INDEX["none_after"]]
    assert found[1, 1] == matrix[0, SITUATION_INDEX["advisory_after"]]
    assert found[1, 5] == matrix[0, SITUATION_INDEX["snow_warning"]]


# --- leakage sentinels (GF9) --------------------------------------------------------------------


def test_cases_take_the_class_at_each_moment_and_the_target_at_five() -> None:
    night = date(2025, 1, 7)
    codes = pl.DataFrame(
        {
            "district": ["a"] * 21 + ["b"] * 21,
            "night": [night] * 42,
            "sample": list(range(21)) * 2,
            "code": [0] * 12 + [4] * 9 + [0] * 21,
        },
        schema={"district": pl.String, "night": pl.Date, "sample": pl.Int8, "code": pl.Int8},
    )
    width = len(MOMENTS)
    columns: dict[str, object] = {"district": ["a"], "day": [night]}
    for k in range(width):
        columns[f"w{k}"] = [5 if k == INDEX_OF["05:00"] else (1 if k >= INDEX_OF["22:00"] else 0)]
    for k in range(width):
        columns[f"h{k}"] = [1 if k >= INDEX_OF["20:00"] else 0]
    states = pl.DataFrame(columns).with_columns(
        pl.col("day").cast(pl.Date), *[pl.col(f"w{k}").cast(pl.Int8) for k in range(width)],
        *[pl.col(f"h{k}").cast(pl.Int8) for k in range(width)],
    )  # fmt: skip
    state_of = pl.DataFrame({"district": ["a", "b"], "state": ["KS", "KS"]})
    cases = season_cases(codes, states, state_of)
    at = cases.filter(pl.col("moment") == INDEX_OF["20:00"])
    a = at.filter(pl.col("f") == 4).row(0, named=True)
    assert (a["c0"], a["h"], a["target"], a["n"]) == (0, 1, 5, 1)
    b = at.filter(pl.col("f") == 0).row(0, named=True)
    assert (b["c0"], b["h"], b["target"]) == (0, 0, 0)
    # Before 20:00 the forecast was quiet and nothing was out: what came later never shows.
    early = cases.filter(pl.col("moment") == INDEX_OF["19:00"]).filter(pl.col("target") == 5)
    assert early.row(0, named=True)["f"] == 0
    assert early.row(0, named=True)["h"] == 0
    late = cases.filter(pl.col("moment") == INDEX_OF["22:15"]).filter(pl.col("target") == 5)
    assert late.row(0, named=True)["c0"] == 1  # 22:15 reads the 22:00 forecast and its class
    assert late.row(0, named=True)["f"] == 4
    assert cases.filter(pl.col("moment") == INDEX_OF["05:00"]).is_empty()


def test_a_season_after_the_fold_never_moves_its_t() -> None:
    cases = world_cases()
    first = fit(cases, [2022])
    more = pl.concat(
        [
            cases,
            _cases([(2024, date(2024, 12, 2), "KS", INDEX_OF["20:00"], 0, 0, 4, 7, 10_000)]),
        ]
    )
    again = fit(more, [2022])
    assert np.array_equal(first.t_state(), again.t_state())
    assert case_counts(more.filter(pl.col("season") == 2022)).state.sum() == (
        case_counts(cases.filter(pl.col("season") == 2022)).state.sum()
    )


def test_the_committed_model_f_holds_the_0500_rates_and_a_whole_outlook() -> None:
    model = outlook.read_rates()
    assert model.schema_version == 2
    _rates, found = outlook.read_artifact(outlook.ARTIFACT_PATH)
    assert len(found.likes) == CELLS
    assert outlook.ARTIFACT_PATH.stat().st_size <= 400_000
    sums = found.t_state().sum(axis=2)
    assert np.allclose(sums[sums > 0], 1.0)
