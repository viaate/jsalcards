"""The own part's gates that need no traits (each-school P6a): G1's arithmetic against hand
numbers, within-morning discrimination, the walk-forward folds and their leakage (r4 12.7),
the shuffle null and the misattribution report, the shift sum and the shadow arms' scoring
reader. SYNTHETIC rows only.
"""

import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from predict.test_lines import synthetic
from snowlight.predict import backtest_lines as bl
from snowlight.predict import frozen
from snowlight.predict.anchor import LiveLabels, LiveRow
from snowlight.predict.backtest_lines import Scored
from snowlight.predict.lines import OwnFit, OwnRow


def _s(unit: str, closed: bool, ref: float, arm: float, **change: Any) -> Scored:
    return Scored(unit=unit, group="g", closed=closed, ref=ref, arm=arm, **change)


def test_g1_on_a_hand_computed_fixture() -> None:
    rows = [
        _s("a", True, 0.5, 0.8), _s("a", False, 0.5, 0.4),  # a better
        _s("b", True, 0.5, 0.2),  # b worse
        _s("c", False, 0.3, 0.3),  # c the same
    ]  # fmt: skip
    found = bl.g1(rows)
    d_a = ((math.log(1 / 0.5) - math.log(1 / 0.8)) + (math.log(1 / 0.5) - math.log(1 / 0.6))) / 2
    d_b = math.log(1 / 0.5) - math.log(1 / 0.2)
    assert found.units == 3
    assert found.median_ll == pytest.approx(0.0)  # a > 0, c = 0, b < 0
    assert d_a > 0 > d_b
    assert found.sign_p is None  # under 100 units: (b') judges
    assert (found.worse, found.better) == (1, 1)  # beyond 0.05 nats a row
    assert found.named == (("b", 1, round(d_b, 4)),)
    assert found.lower_ll <= (d_a + d_b) / 3


def test_g1_b_with_100_units_and_each_part_failing_on_a_planted_fixture() -> None:
    better = [_s(f"u{k}", True, 0.5, 0.6) for k in range(55)]
    worse = [_s(f"w{k}", True, 0.5, 0.45) for k in range(45)]
    found = bl.g1([*better, *worse])
    assert found.sign_p == pytest.approx(bl._sign_p(45, 55))
    assert found.sign_p is not None
    assert found.sign_p >= bl.SIGN_P
    assert found.passed
    bad = bl.g1(
        [
            *[_s(f"u{k}", True, 0.5, 0.6) for k in range(40)],
            *[_s(f"w{k}", True, 0.5, 0.45) for k in range(60)],
        ]
    )
    assert bad.sign_p is not None
    assert bad.sign_p < bl.SIGN_P
    assert not bad.passed
    # (b'): fewer units, a mean worse by more than 0.005 nats a row fails
    few = bl.g1([_s(f"w{k}", True, 0.5, 0.48) for k in range(20)])
    assert few.sign_p is None
    assert few.lower_ll < -bl.LIMITS[0]
    assert not few.passed
    # (c): more named worse than better fails
    named = bl.g1([_s("x", True, 0.5, 0.3), _s("y", True, 0.5, 0.52), _s("z", True, 0.5, 0.52)])
    assert (named.worse, named.better) == (1, 0)
    assert not named.passed
    # (d): a group of 30 or more units worse by more than 0.005 fails; a smaller one is reported
    rural = [_s(f"r{k}", True, 0.5, 0.48, locale="rural") for k in range(30)]
    city = [_s(f"c{k}", True, 0.5, 0.7, locale="city") for k in range(70)]
    grouped = bl.g1([*rural, *city])
    assert grouped.groups["locale rural"][0] == 30
    assert grouped.groups["locale rural"][2] is False
    assert grouped.groups["locale city"][2] is True
    assert not grouped.passed
    small = bl.g1([*rural[:29], *city])
    assert small.groups["locale rural"][2] is None
    # (d) within a group: its mean passes, but (b') within it does not
    split = [
        *[_s(f"s{k}", True, 0.5, 0.5 * math.exp(0.04), locale="suburb") for k in range(15)],
        *[_s(f"t{k}", True, 0.5, 0.5 * math.exp(-0.045), locale="suburb") for k in range(15)],
    ]
    inner = bl.g1([*split, *city])
    units, mean, ok = inner.groups["locale suburb"]
    assert units == 30
    assert mean >= -bl.LIMITS[0]
    assert ok is False
    assert not inner.passed
    # (e): a state of 10 or more units worse by more than 0.01 nats a row fails
    state = [_s(f"55{k:05d}", True, 0.5, 0.49) for k in range(10)]
    states = bl.g1([*state, *city])
    assert states.groups["state 55"][2] is False
    assert bl.g1([*state[:9], *city]).groups["state 55"][2] is None


def test_record_length_counts_storms_not_mornings_and_reports_both() -> None:
    """Honesty rule 11: dates under 5 days apart are one storm for every record count a gate
    uses. A unit whose record before the row is one 4-morning storm is in '1-3', its mornings
    reported as 4."""
    storm = [date(2024, 1, 8) + timedelta(days=k) for k in range(4)]
    assert bl.storm_count(storm) == 1
    assert bl.storm_count([*storm, date(2024, 1, 16)]) == 2
    assert bl.storm_count([date(2024, 1, 8), date(2024, 1, 12)]) == 1
    train = [
        OwnRow("2900001", day, f"{day}|m|advisory", "advisory", 0.0, k % 2 == 0)
        for k, day in enumerate(storm)
    ] + [
        OwnRow("2900002", day, f"{day}|m|advisory", "advisory", 0.0, k % 2 == 1)
        for k, day in enumerate(storm)
    ]
    test_day = date(2024, 12, 9)
    test = [
        OwnRow(u, test_day, f"{test_day}|m|advisory", "advisory", 0.0, u.endswith("1"))
        for u in ("2900001", "2900002", "2900003")
    ]
    scored, _ = bl.score_fold(train, test)
    by = {s.unit: (s.length, s.mornings) for s in scored}
    assert by == {"2900001": ("1-3", 4), "2900002": ("1-3", 4), "2900003": ("0", 0)}
    assert {s.storm for s in scored} == {test_day.isoformat()}
    found = bl.g1(scored)
    assert "length 4+" not in found.groups
    assert found.mornings["mornings 4+"][0] == 2


def _split_units(first: tuple[float, float], later: tuple[float, float]) -> list[Scored]:
    """40 units, each one record-less ('0') row and four '4+' rows, every row closed, with
    the (ref, arm) chances given for each part. The mornings count follows the length."""
    rows = []
    for k in range(40):
        unit = f"29{k:05d}"
        rows.append(_s(unit, True, *first, length="0", mornings=0, locale="rural"))
        rows += [_s(unit, True, *later, length="4+", mornings=9, locale="rural") for _ in range(4)]
    return rows


def test_each_record_length_group_judges_a_units_rows_in_that_group_alone() -> None:
    """G1(d): a unit carries into a record-length group only its rows in that group. Every
    record-less row harmed (-0.51 nats a row) and every later row helped: the record-less
    group fails at -0.51 although each unit is better over all its rows, and G1 fails; the
    '4+' group, the locale group and the mornings report carry each part's own number."""
    harmed = math.log(0.3) - math.log(0.5)
    helped = math.log(0.8) - math.log(0.5)
    found = bl.g1(_split_units((0.5, 0.3), (0.5, 0.8)))
    n0, mean0, ok0 = found.groups["length 0"]
    assert (n0, ok0) == (40, False)
    assert mean0 == pytest.approx(harmed)
    n4, mean4, ok4 = found.groups["length 4+"]
    assert (n4, ok4) == (40, True)
    assert mean4 == pytest.approx(helped)
    overall = (harmed + 4 * helped) / 5
    assert found.groups["locale rural"][1] == pytest.approx(overall)
    assert found.median_ll == pytest.approx(overall)
    assert overall > 0
    assert found.mornings["mornings 0"][1] == pytest.approx(harmed)
    assert found.mornings["mornings 4+"][1] == pytest.approx(helped)
    assert not found.passed
    # The reverse: a record-less group that helps passes there while '4+' is harmed.
    found = bl.g1(_split_units((0.5, 0.8), (0.5, 0.45)))
    assert found.groups["length 0"][2] is True
    assert found.groups["length 4+"][2] is False
    assert not found.passed


def test_the_live_walk_forward_keys_rows_by_the_anchors_storms_and_records_by_rule_11() -> None:
    """r4 10.2: the live walk-forward is by storm with the anchor's rule (mornings at most
    ``ramp_storm_gap`` weekdays apart, registered 1); honesty rule 11 (under 5 days apart)
    stays the record counts'. Monday and Wednesday are one storm by both; Monday and Thursday
    are two live storms and one record storm."""
    from snowlight.predict import anchor  # noqa: PLC0415
    from snowlight.predict.config import PredictConfig  # noqa: PLC0415

    assert anchor.AnchorSettings.of(PredictConfig.load()).storm_gap == bl.STORM_GAP == 1
    monday, wednesday, thursday = date(2026, 1, 5), date(2026, 1, 7), date(2026, 1, 8)
    live = anchor.storms_of([monday, wednesday], bl.STORM_GAP)
    assert live[wednesday] == monday
    assert anchor.storms_of([monday, thursday], bl.STORM_GAP)[thursday] == thursday
    assert bl.storms_by_date([monday, thursday])[thursday] == monday
    assert bl.storm_count([monday, thursday]) == 1


def test_the_conditional_likelihood_of_a_morning_drops_its_level() -> None:
    group = [(0.5, True), (0.5, False)]
    assert bl.cll(group) == pytest.approx(math.log(0.5))
    shifted = [
        (1 / (1 + math.exp(-(math.log(p / (1 - p)) + 2.0))), y)
        for p, y in [(0.3, True), (0.6, False), (0.2, False)]
    ]
    plain = [(0.3, True), (0.6, False), (0.2, False)]
    assert bl.cll(shifted) == pytest.approx(bl.cll(plain))
    assert bl.cll([(0.4, True), (0.9, True)]) == 0.0
    diff, mixed = bl.g3([_s("a", True, 0.3, 0.6), _s("b", False, 0.3, 0.2)])
    assert mixed == 1
    assert diff > 0


def test_a_held_out_winter_s_rows_change_no_fitted_value_of_its_fold() -> None:
    """r4 12.7 (each-school's leakage rules, as r4 12 item 7): altering a held-out winter's rows
    changes no fitted value of its fold; the one exemption is the level-free shift."""
    rows, _ = synthetic(0.8, mornings=60)
    rows = [replace(r, day=r.day - timedelta(days=365 if k % 2 else 0)) for k, r in enumerate(rows)]
    assert sorted({bl.season_of(r.day) for r in rows}) == [2022, 2023]
    folds = bl.walk_forward(rows, 2023)
    assert list(folds) == [2023]  # the held-out winter exists in its rows: the loop is not empty
    assert folds[2023][0]  # a scored fold
    assert folds[2023][1].units  # and a fitted one
    flipped = [replace(r, closed=not r.closed) if bl.season_of(r.day) == 2023 else r for r in rows]
    again = bl.walk_forward(flipped, 2023)
    assert list(again) == [2023]
    for winter in folds:
        assert again[winter][1].units == folds[winter][1].units
        assert again[winter][1].spread == folds[winter][1].spread


def test_the_shuffle_null_on_a_world_with_no_spread_finds_none_and_a_planted_one_stands_out() -> (
    None
):
    flat, _ = synthetic(0.0, units=120, mornings=20, per=25)
    null = bl.shuffle_null(flat, 20, seed=3)
    assert null.real == 0.0
    assert not null.above  # no spread: the real fit is not above the shuffles
    assert null.under >= 10  # most shuffles fit none (a variance at its boundary: not 95%)
    assert null.seconds > 0
    assert len(null.gaps) == 20
    assert null.passed is (null.under >= 19 and null.close >= 19)
    # r4 11(a)'s second half: spreads under the floor but chances far from S fail
    planted = bl.Null(0.0, (0.0,) * 20, 0.05, 1.0, ((0.5, 2.0),) * 18 + ((1.5, 2.0),) * 2)
    assert planted.under == 20
    assert not planted.passed
    near = bl.Null(0.0, (0.0,) * 20, 0.05, 1.0, ((0.5, 2.0),) * 19 + ((0.2, 4.0),))
    assert near.passed
    assert bl.chance_gaps(flat, OwnFit(0.0, {})) == (0.0, 0.0)
    moved = OwnFit(1.0, {r.unit: (1.0, 0.01) for r in flat})
    assert bl.chance_gaps(flat, moved)[0] > 1.0
    spread, _ = synthetic(1.2, units=120, mornings=40, per=25)
    found = bl.shuffle_null(spread, 20, seed=3)
    assert found.real > max(found.spreads)
    assert found.above


def test_misattribution_flags_own_standing_in_for_a_unit_trait() -> None:
    rng = np.random.default_rng(2)
    own = OwnFit(0.8, {f"u{k}": (float(m), 0.1) for k, m in enumerate(rng.normal(0, 1, 200))})
    traits = {
        "coverage": {u: m + float(rng.normal(0, 0.3)) for u, (m, _) in own.units.items()},
        "unrelated": {u: float(rng.normal()) for u in own.units},
    }
    found = bl.misattribution(own, traits)
    assert found["coverage"][1] > 0.5
    assert bl.flagged(found) == ["coverage"]


def test_the_shift_sum_holds_within_0_01() -> None:
    before, _ = synthetic(0.8, mornings=40, seed=4)
    day = date(2024, 3, 1)
    rng = np.random.default_rng(5)
    storm = [
        OwnRow(r.unit, day, f"{day}|m|advisory", "advisory", r.offset, bool(rng.uniform() < 0.6))
        for r in before[:60]
    ]
    level, own, off = bl.shift_sum(before, storm)
    assert own > 0
    assert off < 0.01
    assert level != 0
    # the registered fit: a rule 4 unit planted in the storm (its calls turned over) is in
    # neither fit, so own's shifts are the same as with its calls as they were; the level
    # (the class's, not own's) still reads its rows
    unit = storm[0].unit
    planted = [replace(r, closed=not r.closed) if r.unit == unit else r for r in storm]
    assert (
        bl.shift_sum(before, planted, excluded={unit})[1]
        == bl.shift_sum(before, storm, excluded={unit})[1]
    )
    assert bl.shift_sum(before, planted)[1] != bl.shift_sum(before, storm)[1]


def _scoring_world() -> tuple[
    date,
    list[frozen.EsFreeze],
    dict[date, frozen.FrozenDay],
    LiveLabels,
    Callable[[str], str | None],
]:
    day = date(2026, 1, 7)
    at = datetime(2026, 1, 7, 2, 7, tzinfo=UTC)
    fit = "2026-01-06T19:31:00+00:00"
    es = [
        frozen.EsFreeze(
            day,
            "d1_2007",
            "America/Chicago",
            ("m5o", "m5y"),
            fit,
            {"2900001": (0.3, None), "2900002": (0.6, 0.5), "2900003": (0.2, None)},
            at,
        ),
        frozen.EsFreeze(
            day, "d1_2130", "America/Chicago", ("m5o", "m5y"), fit, {"2900001": (0.9, None)}, at
        ),
    ]

    def row(leaid: str, p: float) -> frozen.FrozenRow:
        at = datetime(2026, 1, 7, 2, 7, tzinfo=UTC)
        return frozen.FrozenRow(
            day=day, freeze="d1_2007", zone="America/Chicago", at=at, late_by_s=0, generated_at=at,
            run_id=None, code_sha=None, live_score_sha256="0", leaid=leaid, served=True, why=None,
            p=round(p, 2), q=0.0, p_raw=p, q_raw=0.0, situation="snow_warning", klass="warning",
            alert=None, base="class", level=0.4, points=40, offset=0.0, reasons=(),
            said_open=False, forecast_read=None, forecast=None, terms=None, alert_begin=None,
            alert_end=None, heights=False, watch=None, variants={},
        )  # fmt: skip

    district = {
        day: frozen.FrozenDay(
            day, (row("2900001", 0.4), row("2900002", 0.5), row("2900003", 0.5)), (), {}
        )
    }
    labels = LiveLabels(
        rows=(
            LiveRow(day, "2900001", "m", "A", "no_school", "snow_warning"),
            LiveRow(day, "2900002", "m", "A", "unnamed", "snow_warning"),
            LiveRow(day, "2900003", "m", "A", "no_school", "advisory"),  # L1's class differs
            LiveRow(day + timedelta(days=1), "2900001", "m", "A", "no_school", "snow_warning"),
        ),
        found=True,
    )
    class_of = {"snow_warning": "warning", "advisory": "advisory"}.get
    return day, es, district, labels, class_of


def test_the_scoring_reader_scores_each_labeled_row_on_its_frozen_chances() -> None:
    day, es, district, labels, class_of = _scoring_world()
    found = bl.score_es({day: es}, district, labels, day + timedelta(days=1), class_of=class_of)
    assert set(found.rows) == {("m5o", "d1_2007"), ("m5y", "d1_2007")}
    m5o = {(s.unit, s.closed, s.ref, s.arm) for s in found.rows[("m5o", "d1_2007")]}
    assert m5o == {("2900001", True, 0.4, 0.3), ("2900002", False, 0.5, 0.6)}
    assert [(s.unit, s.arm) for s in found.rows[("m5y", "d1_2007")]] == [("2900002", 0.5)]
    assert {s.storm for rows in found.rows.values() for s in rows} == {day.isoformat()}
    # nothing of the served day or later is scored
    assert bl.score_es({day: es}, district, labels, day, class_of=class_of).rows == {}
    # a line from a fit older than 36 hours at its freeze is not scored as current
    stale = [replace(f, fit="2026-01-05T01:00:00+00:00") for f in es]
    old = bl.score_es({day: stale}, district, labels, day + timedelta(days=1), class_of=class_of)
    assert old.rows == {}
    assert old.stale == 3
    # tier B rows wait for the anchor's tier B rule; a day-after row waits for R10
    tier_b = LiveLabels(
        rows=(
            LiveRow(day, "2900001", "m", "B", "no_school", "snow_warning"),
            LiveRow(day, "2900002", "m", "A", "no_school", "advisory_after"),
        ),
        found=True,
    )
    later = day + timedelta(days=1)
    assert bl.score_es({day: es}, district, tier_b, later, class_of=class_of).rows == {}
    with_b = bl.score_es({day: es}, district, tier_b, later, class_of=class_of, tier_b={"warning"})
    assert [s.unit for s in with_b.rows[("m5o", "d1_2007")]] == ["2900001"]
    # tier B by each class's own fit: the advisory fit's rule lets no warning row in
    only_advisory = bl.score_es(
        {day: es}, district, tier_b, later, class_of=class_of, tier_b={"advisory"}
    )
    assert only_advisory.rows == {}
    # r5 3.2's base is before the class order's cap; the frozen record keeps the chance after
    # it, so each freeze counts its scored rows held at the cap
    capped = {"raw": [1.2, 0.1, 0.0, 0.0], "b": [0.6, 0.1, 0.0, 0.0], "cl": [1, 0, 0, 0]}
    at_cap = {**capped, "lo": -1.0, "hi": 0.7}
    at_high = {**capped, "lo": -1.0, "hi": 1.5, "b": [1.2, 0.1, 0.0, 0.0], "cl": [0, 0, 0, 0]}
    under_cap = {**at_cap, "raw": [0.3, 0.1, 0.0, 0.0], "b": [0.3, 0.1, 0.0, 0.0]}
    assert bl.at_order_cap(at_cap, 1.5)
    assert not bl.at_order_cap(at_high, 1.5)  # the class's own bound, not a cap
    assert not bl.at_order_cap(under_cap, 1.5)  # a cap that did not bind
    assert not bl.at_order_cap(at_cap, None)
    assert not bl.at_order_cap(None, 1.5)
    with_terms = {
        day: replace(
            district[day],
            rows=tuple(
                replace(r, terms=at_cap if r.leaid == "2900001" else under_cap)
                for r in district[day].rows
            ),
        )
    }
    counted = bl.score_es(
        {day: es}, with_terms, labels, later, class_of=class_of, highs={"warning": 1.5}
    )
    assert counted.capped == {"d1_2007": 1}
    assert bl.score_es({day: es}, with_terms, labels, later, class_of=class_of).capped == {}
    from snowlight.predict.config import PredictConfig  # noqa: PLC0415
    from snowlight.predict.forecast_adjust import AdjustSettings  # noqa: PLC0415

    settings = AdjustSettings.of(PredictConfig.load())
    highs = bl.uncapped_highs(settings)
    assert set(highs) == set(settings.bounds)
    if settings.snow_amount:
        assert set(highs.values()) == {settings.snow_amount_high}


def test_the_scoring_reader_s_rows_carry_their_units_record_length_locale_and_mornings() -> None:
    """r4 rule 11 on live rows, as score_fold's: so G1's record-length group 0 holds only the
    units with no earlier record (P7's G-LIVE runs g1 on these rows)."""
    day, es, district, labels, class_of = _scoring_world()
    found = bl.score_es({day: es}, district, labels, day + timedelta(days=1), class_of=class_of)
    # each row's record length is its unit's: with no earlier record, every unit is in group 0
    assert {(s.length, s.mornings, s.locale) for s in found.rows[("m5o", "d1_2007")]} == {
        ("0", 0, "unknown")
    }
    # a unit with three earlier storms (and an earlier labeled day of its own) is outside it
    earlier = {"2900001": [date(2025, 1, 6), date(2025, 1, 20), date(2025, 2, 3)]}
    lengths = bl.score_es(
        {day: es}, district, labels, day + timedelta(days=1), class_of=class_of,
        earlier=earlier, locale={"2900001": "rural", "2900002": "city"},
    )  # fmt: skip
    m5o_rows = lengths.rows[("m5o", "d1_2007")]
    assert {(r.unit, r.length, r.mornings, r.locale) for r in m5o_rows} == {
        ("2900001", "1-3", 3, "rural"), ("2900002", "0", 0, "city"),
    }  # fmt: skip
    groups = bl.g1(m5o_rows).groups
    assert groups["length 0"][0] == 1
    assert groups["length 1-3"][0] == 1
