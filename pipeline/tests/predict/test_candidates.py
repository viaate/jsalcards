"""The tuning candidates (tune-v3 lane): the term fit's support rule and extra columns, the
candidates' levels and columns, the C4 climate, the level rule and the split, and the shadow
switches.

Every number, place and day here is made up for the tests; nothing comes from a real list or a
real storm.
"""

import math
from datetime import UTC, date, datetime

import numpy as np
import polars as pl
import pytest

from snowlight.predict import candidates, pool, terms
from snowlight.predict.candidates import (
    AFTERNOON,
    COLD,
    DONE_OVERNIGHT,
    ENDS_EARLY,
    NEAR,
    SCHOOL_DAY,
    WARM,
    Units,
)
from snowlight.predict.pool import Rows
from snowlight.predict.situations import SITUATIONS, WeatherClass
from snowlight.predict.terms import UNKNOWN, Design, Support, Term

ADVISORY = int(WeatherClass.ADVISORY)
WARNING = int(WeatherClass.SNOW_WARNING)


def _situation(weather: WeatherClass) -> int:
    return next(i for i, s in enumerate(SITUATIONS) if s.weather == weather and not s.after)


# --- the term fit: support, extra columns, the gate ---------------------------------------------


def _design(n: int, seed: int, days: int = 10) -> Design:
    rng = np.random.default_rng(seed)
    levels = {term: np.full(n, UNKNOWN, dtype=np.int64) for term in terms.TERM_ORDER}
    warm = rng.random(n) < 0.4
    y = (rng.random(n) < np.where(warm, 0.2, 0.7)).astype(float)
    return Design(
        offset=np.zeros(n),
        y=y,
        weather=np.full(n, ADVISORY, dtype=np.int64),
        levels=levels,
        day=rng.integers(0, days, n).astype(np.int64) + 738000,
        extra=np.column_stack([warm.astype(float), (~warm).astype(float)]),
        extra_bounds=((None, 0.0), (None, 0.0)),
    )


def test_an_extra_column_takes_its_sign_and_the_fit_is_unchanged_without_one() -> None:
    design = _design(2000, 1)
    model = terms.fit_with(design, 1.0)
    assert model.extra[0] < -0.5  # warm rows close less: the take-away column moves
    assert model.extra[1] == pytest.approx(0.0, abs=1e-6)  # held at 0 by its bound
    plain = Design(design.offset, design.y, design.weather, design.levels)
    assert terms.fit_with(plain, 1.0).extra == ()
    assert terms.fit_with(plain, 1.0) == terms.fit_with(replace_day(plain), 1.0)


def replace_day(design: Design) -> Design:
    return Design(
        design.offset,
        design.y,
        design.weather,
        design.levels,
        day=np.zeros(design.y.size, np.int64),
    )


def test_the_support_rule_fixes_a_thin_column_at_zero() -> None:
    design = _design(2000, 2, days=2)  # two dates only: under 3
    model = terms.fit_with(design, 1.0, support=Support())
    assert model.extra == (0.0, 0.0)
    wide = terms.fit_with(_design(2000, 2, days=10), 1.0, support=Support())
    assert wide.extra[0] < 0


def test_support_counts_rows_and_dates_per_column() -> None:
    x = np.array([[1, 0], [1, 0], [1, 1], [0, 1]] * 10, dtype=float)
    day = np.array([1, 2, 3, 3] * 10, dtype=np.int64)
    assert Support(20, 3).supported(x, day).tolist() == [True, False]
    assert Support(20, 1).supported(x, day).tolist() == [True, True]
    assert Support(31, 1).supported(x, day).tolist() == [False, False]


def test_the_support_rule_needs_dates_and_extra_columns_need_bounds() -> None:
    design = _design(100, 3)
    with pytest.raises(ValueError, match="date"):
        terms.fit_with(Design(design.offset, design.y, design.weather, design.levels,
                              extra=design.extra, extra_bounds=design.extra_bounds),
                       1.0, support=Support())  # fmt: skip
    with pytest.raises(ValueError, match="bounds"):
        terms.fit_with(Design(design.offset, design.y, design.weather, design.levels,
                              extra=design.extra), 1.0)  # fmt: skip


def test_the_gate_keeps_a_snow_term_from_taking_away() -> None:
    n = 3000
    rng = np.random.default_rng(4)
    snow = rng.integers(0, 6, n).astype(np.int64)
    y = (rng.random(n) < 1 / (1 + np.exp(-(0.8 * (snow - 2))))).astype(float)
    levels = {term: np.full(n, UNKNOWN, dtype=np.int64) for term in terms.TERM_ORDER}
    levels[Term.SNOW_ADVISORY] = snow
    gate = np.zeros(n, dtype=np.bool_)
    gate[: n // 2] = True
    design = Design(np.zeros(n), y, np.full(n, ADVISORY, np.int64), levels, up_only=gate)
    model = terms.fit_with(design, 1.0)
    value = terms.contributions(model, design)[Term.SNOW_ADVISORY]
    assert (value[gate] >= 0).all()
    assert (value[~gate] < 0).any()
    seasons = rng.integers(2019, 2022, n).astype(np.int64)
    again = terms.fit(design, seasons, penalties=(1.0, 10.0))
    assert (terms.contributions(again, design)[Term.SNOW_ADVISORY][gate] >= 0).all()


# --- C2 -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "level"),
    [(None, UNKNOWN), (math.nan, UNKNOWN), (20.0, COLD), (31.9, COLD), (32.0, NEAR),
     (33.9, NEAR), (34.0, WARM), (40.0, WARM)],
)  # fmt: skip
def test_temperature_levels_follow_the_edges(value: float | None, level: int) -> None:
    assert candidates.temperature_level(value) == level


@pytest.mark.parametrize(
    ("liquid", "snow", "mixed"),
    [(0.5, 1.0, True), (0.5, 3.0, False), (0.05, 0.0, False), (0.10, 0.49, True),
     (math.nan, 1.0, False), (0.3, math.nan, False)],
)  # fmt: skip
def test_a_mix_by_amounts(liquid: float, snow: float, mixed: bool) -> None:
    assert candidates.mixed_by_amounts(liquid, snow) is mixed


def test_c2_columns_apply_on_snow_days_with_snow_and_a_known_temperature() -> None:
    own = np.array([ADVISORY, WARNING, ADVISORY, ADVISORY, 0, ADVISORY, ADVISORY])
    temperature = np.array([WARM, NEAR, COLD, WARM, WARM, UNKNOWN, NEAR])
    mixed = np.array([True, True, True, False, True, True, False])
    snow = np.array([True, True, True, True, True, True, False])
    found = candidates.c2_columns(own, temperature, mixed, snow)
    assert found.tolist() == [
        [1, 1, 1, 0, 0],  # warm and mixed
        [1, 0, 0, 0, 1],  # near and mixed
        [0, 0, 0, 1, 0],  # cold and mixed adds
        [1, 1, 0, 0, 0],  # warm, not mixed
        [0, 0, 0, 0, 0],  # no alert
        [0, 0, 0, 0, 0],  # temperature unknown
        [0, 0, 0, 0, 0],  # no snow forecast
    ]
    assert candidates.C2_BOUNDS[3] == candidates.ADDS
    assert candidates.C2_BOUNDS[4] == candidates.FREE


# --- C3 -------------------------------------------------------------------------------------------


def test_a_period_goes_to_the_band_holding_most_of_its_hours() -> None:
    # EST: 06 UTC is 1 AM, 12 UTC 7 AM, 18 UTC 1 PM: periods match the bands.
    day = date(2023, 2, 28)
    assert candidates.period_weights(day, "America/New_York", 6) == (1.0, 0.0, 0.0, 0.0)
    assert candidates.period_weights(day, "America/New_York", 12) == (0.0, 1.0, 0.0, 0.0)
    assert candidates.period_weights(day, "America/New_York", 18) == (0.0, 0.0, 1.0, 0.0)
    # EDT: the 2-8 AM period is early morning (5 of its hours).
    assert candidates.period_weights(date(2023, 3, 14), "America/New_York", 12) == (
        0.0, 1.0, 0.0, 0.0,
    )  # fmt: skip
    # PST: the 4-10 AM period splits 3 and 3.
    assert candidates.period_weights(date(2024, 1, 31), "America/Los_Angeles", 18) == (
        0.0, 0.5, 0.5, 0.0,
    )  # fmt: skip


def test_snow_shares_and_timing_levels() -> None:
    day = date(2023, 2, 28)
    zone = "America/New_York"
    overnight = candidates.snow_shares(day, zone, (3.0, 0.1, 0.0, 0.0))
    assert overnight is not None
    assert candidates.timing_level(math.nan, overnight) == DONE_OVERNIGHT
    early = candidates.snow_shares(day, zone, (1.0, 2.0, 0.1, 0.0))
    assert candidates.timing_level(math.nan, early) == ENDS_EARLY
    late = candidates.snow_shares(day, zone, (0.0, 0.0, 0.5, 2.0))
    assert candidates.timing_level(math.nan, late) == AFTERNOON
    school = candidates.snow_shares(day, zone, (1.0, 1.0, 2.0, 0.0))
    assert candidates.timing_level(math.nan, school) == SCHOOL_DAY
    assert candidates.snow_shares(day, zone, (math.nan, 0.0, 0.0, math.nan)) is None
    assert candidates.timing_level(math.nan, None) == UNKNOWN
    assert candidates.timing_level(0.5, None) == DONE_OVERNIGHT
    assert candidates.timing_level(6.0, school) == ENDS_EARLY  # the alert's end decides
    assert candidates.timing_level(10.0, None) == SCHOOL_DAY


def test_alert_hours_and_the_gate_read_local_time() -> None:
    day = date(2023, 2, 28)
    end = datetime(2023, 2, 28, 12, 0, tzinfo=UTC)  # 7 AM EST
    assert candidates.local_hours(end, day, "America/New_York") == 7.0
    assert math.isnan(candidates.local_hours(None, day, "America/New_York"))
    before = datetime(2023, 2, 28, 2, 0, tzinfo=UTC)  # 21:00 EST on Feb 27
    assert candidates.began_by_snapshot(before, day, "America/New_York")
    assert not candidates.began_by_snapshot(
        datetime(2023, 2, 28, 2, 1, tzinfo=UTC), day, "America/New_York"
    )
    assert not candidates.began_by_snapshot(None, day, "America/New_York")


def test_c3_columns() -> None:
    own = np.array([ADVISORY, WARNING, ADVISORY, ADVISORY, 0])
    timing = np.array([DONE_OVERNIGHT, ENDS_EARLY, AFTERNOON, SCHOOL_DAY, ENDS_EARLY])
    assert candidates.c3_columns(own, timing).tolist() == [
        [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0], [0, 0, 0],
    ]  # fmt: skip
    assert candidates.c3_delay_columns(own, timing)[:, 0].tolist() == [0, 1, 0, 0, 0]


# --- C4 -------------------------------------------------------------------------------------------


def test_c4_levels_read_a_bucket_against_the_place_s_snowy_nights() -> None:
    snowy = np.array([50.0, 30.0, 10.0, 7.0, 3.0])  # buckets 1 to 5
    assert candidates.c4_level(0, snowy) == candidates.BELOW_MOST
    assert candidates.c4_level(1, snowy) == candidates.TYPICAL  # above none, below 50%
    assert candidates.c4_level(2, snowy) == candidates.TYPICAL  # 50% below: not more than half
    assert candidates.c4_level(3, snowy) == candidates.ABOVE_MOST  # 80% below
    assert candidates.c4_level(4, snowy) == candidates.ABOVE_MOST  # 90% below: not above 0.9
    assert candidates.c4_level(5, snowy) == candidates.FAR_ABOVE
    south = np.array([5.0, 0.0, 0.0, 0.0, 0.0])
    assert candidates.c4_level(2, south) == candidates.FAR_ABOVE  # 2 in where 1 in is the most
    assert candidates.c4_level(-1, snowy) == UNKNOWN
    assert candidates.c4_level(2, np.zeros(5)) == UNKNOWN


def test_the_climate_pools_up_and_uses_earlier_seasons_only() -> None:
    codes = pl.DataFrame(
        {
            "district": ["a"] * 25 + ["b"] * 3 + ["c"] * 2 + ["a"] * 9,
            "day": [date(2019, 1, 1)] * 30 + [date(2020, 1, 1)] * 9,
            "code": [1] * 25 + [3] * 3 + [5] * 2 + [5] * 9,
        },
        schema={"district": pl.String, "day": pl.Date, "code": pl.Int8},
    )
    counts = candidates.season_counts(codes)
    climate = candidates.climate_of(counts, [2018], {"a": "NY", "b": "NY", "c": "GA"}, {"NY": "northeast", "GA": "southeast"})  # fmt: skip # noqa: E501
    assert climate.of("a", "NY", "northeast").tolist() == [25, 0, 0, 0, 0]  # own: 25 nights
    assert climate.of("b", "NY", "northeast").tolist() == [25, 0, 3, 0, 0]  # the state's
    assert climate.of("c", "GA", "southeast").tolist() == [25, 0, 3, 0, 2]  # the nation's
    assert climate.of("z", None, None).tolist() == [25, 0, 3, 0, 2]
    later = candidates.climate_of(counts, [2018, 2019], {"a": "NY"}, {"NY": "northeast"})
    assert later.district["a"].tolist() == [25, 0, 0, 0, 9]


# --- C1 and C2b -----------------------------------------------------------------------------------


def _rows(situation: int, season: int, ys: list[float], district: int = 0) -> Rows:
    n = len(ys)
    return Rows(
        np.full(n, district, np.int64), np.full(n, situation, np.int64),
        np.full(n, season, np.int64), np.array(ys, dtype=float),
    )  # fmt: skip


def test_level_support_needs_days_dates_and_no_busy_date() -> None:
    assert pool.level_supported(30, 3, 15)
    assert not pool.level_supported(29, 3, 10)
    assert not pool.level_supported(30, 2, 15)
    assert not pool.level_supported(30, 3, 16)


def test_level_records_count_earlier_seasons_of_the_same_unit_and_situation() -> None:
    advisory = _situation(WeatherClass.ADVISORY)
    source = _rows(advisory, 2019, [1.0] * 12 + [0.0] * 24)
    day = np.array([1] * 12 + [2] * 12 + [3] * 12, dtype=np.int64)
    unit = np.zeros(36, dtype=np.int64)
    target = Rows(
        np.zeros(3, np.int64), np.array([advisory, advisory, advisory + 1]),
        np.array([2020, 2019, 2020]), np.zeros(3),
    )  # fmt: skip
    found = pool.level_records(target, np.zeros(3, np.int64), source, unit, day)
    assert found.n.tolist() == [36, 0, 0]  # the same season and another situation count none
    assert found.rate[0] == pytest.approx(1 / 3)
    assert found.supported.tolist() == [True, False, False]
    kept = pool.level_records(target, np.zeros(3, np.int64), source, unit, day, day != 1)
    assert kept.n[0] == 24
    assert not kept.supported[0]


def test_the_level_rule_serves_a_supported_state_and_the_split_moves_by_kind() -> None:
    advisory = _situation(WeatherClass.ADVISORY)
    quiet = _situation(WeatherClass.NONE)
    # The state's record: 80 advisory days on 4 dates, 20 closed; its 32 cold days, 8 a date,
    # closed 16.
    one = [1.0] * 4 + [0.0] * 4 + [1.0] + [0.0] * 11
    source = _rows(advisory, 2019, one * 4)
    day = np.repeat(np.arange(4), 20).astype(np.int64)
    kinds = np.array(([candidates.KIND_COLD] * 8 + [candidates.KIND_WARM] * 12) * 4)
    units = Units(np.zeros(80, np.int64), np.zeros(80, np.int64))
    target = Rows(
        np.zeros(3, np.int64), np.array([advisory, advisory, quiet]),
        np.full(3, 2020, np.int64), np.zeros(3),
    )  # fmt: skip
    base = np.array([0.6, 0.6, 0.02])
    raw, served, moved = candidates.level_rule_base(
        target, Units(np.zeros(3, np.int64), np.zeros(3, np.int64)),
        np.array([candidates.KIND_UNKNOWN, candidates.KIND_COLD, candidates.KIND_COLD]),
        base, lambda _s: (source, units, kinds, day), 0.01, 0.99,
    )  # fmt: skip
    assert served.tolist() == [True, True, False]  # a quiet day keeps today's chance
    assert raw[0] == pytest.approx(0.25)  # the state's raw record
    assert raw[2] == pytest.approx(0.02)
    # Cold: (16 + 8 x 0.25) / (32 + 8) = 0.45, the logit shift from 0.25 applied to 0.25.
    assert raw[1] == pytest.approx(0.45)
    assert moved.tolist() == [False, True, False]


def test_the_split_needs_its_own_support() -> None:
    advisory = _situation(WeatherClass.ADVISORY)
    source = _rows(advisory, 2019, [1.0] * 10 + [0.0] * 30)
    day = np.repeat(np.arange(4), 10).astype(np.int64)
    kinds = np.array([candidates.KIND_COLD] * 5 + [candidates.KIND_WARM] * 35)
    units = Units(np.zeros(40, np.int64), np.zeros(40, np.int64))
    target = _rows(advisory, 2020, [0.0])
    raw, _served, moved = candidates.level_rule_base(
        target, Units(np.zeros(1, np.int64), np.zeros(1, np.int64)),
        np.array([candidates.KIND_COLD]), np.array([0.5]),
        lambda _s: (source, units, kinds, day), 0.01, 0.99,
    )  # fmt: skip
    assert raw[0] == pytest.approx(0.25)  # served, not split: 5 cold days are too few
    assert not moved[0]


def test_kinds() -> None:
    temperature = np.array([COLD, COLD, NEAR, WARM, UNKNOWN])
    mixed = np.array([False, True, False, False, True])
    assert candidates.kind_of(temperature, mixed).tolist() == [0, 1, 1, 1, -1]


def test_every_shadow_switch_is_off() -> None:
    assert set(candidates.SHADOW) == {"c2a", "c2c", "c3", "c4", "c1_c2b"}
    assert not any(candidates.shadow_on(name) for name in candidates.SHADOW)


def test_a_shadow_chance_is_the_base_while_its_switch_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = np.array([0.4, 0.8])
    columns = np.array([[1.0, 0.0], [0.0, 1.0]])
    off = candidates.shadow_chance("c2a", base, columns, [-1.0, 0.5], 0.01, 0.99)
    assert off.tolist() == base.tolist()
    monkeypatch.setattr(candidates, "SHADOW", {**candidates.SHADOW, "c2a": True})
    on = candidates.shadow_chance("c2a", base, columns, [-1.0, 0.5], 0.01, 0.99)
    assert on[0] < base[0]
    assert on[1] > base[1]
    assert np.allclose(on, np.round(on, 2))
    assert candidates.shadow_chance("c2a", base, columns, [], 0.01, 0.99).tolist() == base.tolist()


def test_the_level_rule_records_its_levels_and_p8_takes_their_busiest_dates() -> None:
    advisory = _situation(WeatherClass.ADVISORY)
    # The state's record: 80 advisory days on 4 dates (20 each), the busiest date first by its
    # cold days; dates 0-3 hold 8 cold days each.
    one = [1.0] * 4 + [0.0] * 4 + [1.0] + [0.0] * 11
    source = _rows(advisory, 2019, one * 4)
    day = np.repeat(np.array([10, 11, 12, 13]), 20).astype(np.int64)
    kinds = np.array(([candidates.KIND_COLD] * 8 + [candidates.KIND_WARM] * 12) * 4)
    units = Units(np.zeros(80, np.int64), np.zeros(80, np.int64))
    target = Rows(
        np.zeros(2, np.int64), np.array([advisory, advisory]), np.full(2, 2020, np.int64),
        np.zeros(2),
    )  # fmt: skip
    target_units = Units(np.zeros(2, np.int64), np.zeros(2, np.int64))
    kind = np.array([candidates.KIND_UNKNOWN, candidates.KIND_COLD])

    def source_of(_season: int) -> tuple[Rows, Units, np.ndarray, np.ndarray]:
        return source, units, kinds, day

    rule = candidates.level_rule(
        target, target_units, kind, np.array([0.6, 0.6]), source_of, 0.01, 0.99
    )
    assert rule.served_tier.tolist() == [0, 0]  # the state serves both
    assert rule.split_tier.tolist() == [candidates.NO_TIER, 0]  # the cold row splits there
    assert candidates.TIERS[0] == "state"
    found = candidates.level_dates(
        rule, target, target_units, kind, source_of, np.array([True, True]), count=3
    )
    # Each record spans 4 equal dates: the 3 earliest of each, every date once.
    assert found == [10, 11, 12]
    assert (
        candidates.level_dates(
            rule, target, target_units, kind, source_of, np.array([False, False])
        )
        == []
    )
    raw, served, moved = candidates.level_rule_base(
        target, target_units, kind, np.array([0.6, 0.6]), source_of, 0.01, 0.99
    )
    assert raw.tolist() == rule.p.tolist()
    assert served.tolist() == rule.served.tolist()
    assert moved.tolist() == rule.moved.tolist()


def test_a_served_level_always_clears_the_thin_rule() -> None:
    # C1a serves a record only with 30 labeled days; the thin rule (E3b) flags a region with
    # fewer than the config's level_min_days, which is below that, so no served cell is thin.
    from snowlight.predict.config import PredictConfig  # noqa: PLC0415

    assert PredictConfig.load().model.level_min_days < pool.LEVEL_MIN_DAYS
    assert not pool.level_supported(pool.LEVEL_MIN_DAYS - 1, 5, 1)
