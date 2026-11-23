"""The regression, the test and its gate, the usual rates, own records, and the model file."""

import gzip
import itertools
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from snowlight.flights import artifact, records, train
from snowlight.flights import model as fm
from snowlight.flights.obs import Kind
from snowlight.schemas.flights import FlightsModel


def test_the_fit_finds_a_known_rule() -> None:
    rng = np.random.default_rng(7)
    x = rng.normal(size=(4000, 2))
    p = fm.expit(-3.0 + 1.5 * x[:, 0] - 0.5 * x[:, 1])
    trials = np.full(4000, 50.0)
    events = rng.binomial(50, p).astype(np.float64)
    fitted = fm.fit(x, events, trials, ridge=0.0)
    slope = np.asarray(fitted.coef) / np.asarray(fitted.scale)
    assert slope == pytest.approx([1.5, -0.5], abs=0.08)
    again = fm.Fitted.from_json(fitted.as_json())
    assert again.predict(x[:3]) == pytest.approx(fitted.predict(x[:3]), abs=1e-4)
    with pytest.raises(TypeError, match="list"):
        fm.Fitted.from_json({"intercept": 0, "coef": 1, "mean": [], "scale": []})


def test_scores_and_the_gate() -> None:
    events = np.array([10.0, 0.0, 30.0])
    trials = np.array([100.0, 100.0, 100.0])
    base = np.full(3, 0.13)
    sharp = fm.score(np.array([0.1, 0.01, 0.3]), base, events, trials)
    assert sharp.skill > 0
    assert sharp.calibration == pytest.approx(41 / 40)
    assert sharp.high_seen == pytest.approx(0.3)
    assert fm.passes("dep_canc", sharp)
    assert not fm.passes("dep_canc", fm.score(base, base, events, trials))  # no skill
    over = fm.score(np.array([0.2, 0.2, 0.6]), base, events, trials)
    assert not fm.passes("dep_canc", over)
    few = fm.score(np.array([0.1, 0.01, 0.3]), base, events / 10, trials)
    assert not fm.passes("dep_canc", few)
    loud = fm.score(np.array([0.1, 0.01, 0.9]), np.full(3, 0.5), events, trials)
    assert not fm.passes("dep_canc", loud)  # said 90% where 30% happened
    assert fm.score(np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0)).skill == 0.0
    assert fm.Score(1, 0, 0, 0, 0).calibration == float("inf")
    table = fm.reliability(np.array([0.005, 0.3, 0.31]), events, trials)
    assert [row["units"] for row in table] == [100.0, 200.0]


def test_the_design_matrix() -> None:
    frame = pl.DataFrame(
        {
            "base": [0.01],
            "snow": [2.0],
            "snow_before": [1.0],
            "ice": [0.1],
            "ice_before": [0.0],
            "p_snow": [0.9],
            "p_zr": [0.0],
            "thunder": [0.1],
            "gust": [40.0],
            "wind": [25.0],
            "vis": [0.5],
            "cig": [3.0],
            "tmp": [10.0],
            "hub_snow": [0.0],
            "hub_storm": [0.0],
            "day_snow": [3.0],
            "day_ice": [0.0],
            "day_storm": [0.2],
            "pre_snow": [4.0],
            "pre_ice": [0.0],
            "obs_snow": [9.0],
            "obs_snow_old": [3.0],
            "obs_frz": [1.0],
            "lat": [33.0],
        }
    )
    x = fm.design(frame)
    assert x.shape == (1, len(fm.FEATURES))
    row = dict(zip(fm.FEATURES, x[0], strict=True))
    assert row["gust"] == pytest.approx(2.0)
    assert row["south_snow"] == pytest.approx(np.log1p(2.0))
    assert row["low_vis"] == pytest.approx(2.5 / 3)
    assert row["pre_snow"] == pytest.approx(np.log1p(4.0))
    assert row["obs_snow"] == pytest.approx(np.log1p(9.0))
    assert row["obs_frz"] == pytest.approx(np.log1p(1.0))
    assert fm.leads() == (1, 2, 3)


def _blocks() -> pl.DataFrame:
    days = [date(2024, 1, d) for d in range(1, 21)]
    return pl.DataFrame(
        {
            "apt": ["AAA"] * 20 + ["BBB"] * 20,
            "day": days * 2,
            "block": [0] * 40,
            "n": [100] * 40,
            "canc": [30 if i < 10 else 0 for i in range(20)] + [1] * 20,
            "late": [5] * 40,
        }
    )


def test_usual_rates_shrink_small_airports() -> None:
    rates = fm.base_rates(_blocks().lazy())
    aaa = rates.filter(pl.col("apt") == "AAA").row(0, named=True)
    assert 0.0775 < aaa["canc"] < 0.15
    rough = fm.rough_rates(_blocks().lazy())
    assert (
        rough.filter(pl.col("apt") == "AAA").get_column("rough").item()
        > rough.filter(pl.col("apt") == "BBB").get_column("rough").item()
    )
    per, whole = artifact.base_tables(rates)
    assert per["AAA"]["canc"][0][0] == pytest.approx(round(aaa["canc"], 5))
    assert per["AAA"]["canc"][1][5] == whole["canc"][1][5]  # no flights then: the national rate
    rough_per, rough_whole = artifact.rough_table(rough)
    assert rough_per["BBB"][5] == rough_whole[5]


def test_the_model_file_round_trips(tmp_path: Path) -> None:
    model = fm.Model()
    model.fitted[("dep_canc", 1)] = fm.Fitted(
        -4.0, (0.5,) * len(fm.FEATURES), (0.0,) * len(fm.FEATURES), (1.0,) * len(fm.FEATURES)
    )
    model.published[("AAA", "dep_canc", 1)] = True
    model.published[("AAA", "rough", 2)] = False
    rates = fm.base_rates(_blocks().lazy())
    per, whole = artifact.base_tables(rates)
    made = artifact.Artifact(
        model=model,
        test_first=date(2025, 10, 1),
        test_last=date(2026, 9, 30),
        base={"dep": per, "arr": per},
        national={"dep": whole, "arr": whole},
        rough={"AAA": [0.1] * 12},
        national_rough=[0.02] * 12,
    )
    path = tmp_path / "model.json.gz"
    artifact.write(made, path)
    again = artifact.read(path)
    assert again.model.is_published("AAA", "dep_canc", 1)
    assert not again.model.is_published("AAA", "dep_canc", 2)
    assert again.usual("dep", "canc", "AAA", 0, 1) == per["AAA"]["canc"][0][0]
    assert again.usual("dep", "canc", "ZZZ", 0, 1) == whole["canc"][0][0]
    assert again.usual_rough("AAA", 3) == 0.1
    assert again.usual_rough("ZZZ", 3) == 0.02
    # The file validates against its schema. A file of fewer inputs (the groups the validation
    # year left out) reads with those inputs; one out of their order is refused.
    document = json.loads(gzip.decompress(path.read_bytes()))
    FlightsModel.from_json_bytes(gzip.decompress(path.read_bytes()))
    document["inputs"] = document["inputs"][:-1]
    for fit in document["fits"]:
        for key in ("coef", "mean", "scale"):
            fit[key] = fit[key][:-1]
    fewer = artifact.Artifact.from_bytes(json.dumps(document).encode())
    assert fewer.model.inputs == fm.FEATURES[:-1]
    full = np.zeros((1, len(fm.FEATURES)))
    full[0, -1] = 50.0  # the input left out never moves the chance
    assert fewer.model.chance("dep_canc", 1, full)[0] == pytest.approx(
        fewer.model.chance("dep_canc", 1, np.zeros((1, len(fm.FEATURES))))[0]
    )
    swapped = json.loads(json.dumps(document))
    swapped["inputs"][0], swapped["inputs"][1] = swapped["inputs"][1], swapped["inputs"][0]
    with pytest.raises(ValueError, match="order"):
        artifact.Artifact.from_bytes(json.dumps(swapped).encode())
    document["fits"][0]["coef"] = [1.0]
    with pytest.raises(ValueError, match="coef, mean and scale"):
        artifact.Artifact.from_bytes(json.dumps(document).encode())


def test_own_records_hold_each_airport_to_the_others() -> None:
    # Thirty snow days: AAA cancels a quarter, BBB 3 in 100 and the big CCC a tenth. AAA is
    # clearly worse than its peers every day and BBB clearly better; CCC's peers pooled sit near
    # its own share, so it gets no verdict. Carriers at one airport are held the same way.
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(30)]

    def one(code: str, flights: int, canc: int) -> pl.DataFrame:
        return pl.DataFrame(
            {"apt": [code] * 30, "day": days, "block": [0] * 30, "n": [flights] * 30}
        ).with_columns(pl.lit(canc, dtype=pl.Int64).alias("canc"))

    parts = [one("AAA", 100, 25), one("BBB", 100, 3), one("CCC", 1000, 100)]
    blocks = pl.concat(parts)
    kinds = blocks.select("apt", "day", "block").with_columns(
        pl.lit(int(Kind.SNOW), dtype=pl.Int8).alias("kind")
    )
    lines = records.airport_lines(blocks.lazy(), kinds.lazy())
    assert lines["AAA"][0].verdict is records.Verdict.SOONER
    assert (lines["AAA"][0].worse, lines["AAA"][0].better) == (30, 0)
    assert lines["BBB"][0].verdict is records.Verdict.LONGER
    assert lines["CCC"][0].verdict is records.Verdict.NONE
    assert lines["AAA"][0].share == pytest.approx(0.25)
    carriers = pl.concat(
        [
            part.with_columns(pl.lit("AAA").alias("apt"), pl.lit(code).alias("carrier"))
            for part, code in zip(parts, ("ZZ", "YY", "XX"), strict=True)
        ]
    )
    per = records.carrier_lines(carriers.lazy(), kinds.lazy())
    assert per[("AAA", "ZZ")][0].verdict is records.Verdict.SOONER
    assert per[("AAA", "YY")][0].verdict is records.Verdict.LONGER
    assert per[("AAA", "XX")][0].verdict is records.Verdict.NONE


def test_one_storm_days_blocks_cannot_make_a_verdict() -> None:
    # AAA: 10 snow blocks, all bad, on two days only (enough blocks for the old block count
    # to say "cancels sooner"); BBB: many quiet snow days.
    aaa = pl.DataFrame(
        {
            "apt": ["AAA"] * 10,
            "day": [date(2024, 1, 1 + i // 5) for i in range(10)],
            "block": [i % 5 for i in range(10)],
            "n": [100] * 10,
            "canc": [50] * 10,
        }
    )
    bbb = pl.DataFrame(
        {
            "apt": ["BBB"] * 40,
            "day": [date(2024, 1, 1) + timedelta(days=i) for i in range(40)],
            "block": [0] * 40,
            "n": [100] * 40,
            "canc": [0] * 40,
        }
    )
    blocks = pl.concat([aaa, bbb])
    kinds = blocks.select("apt", "day", "block").with_columns(
        pl.lit(int(Kind.SNOW), dtype=pl.Int8).alias("kind")
    )
    line = records.airport_lines(blocks.lazy(), kinds.lazy())["AAA"][0]
    assert (line.blocks, line.bad, line.days, line.bad_days) == (10, 10, 2, 2)
    # BBB cancelled none those days: at its share AAA expects no cancel, so the test counts
    # neither day (LR-F5); the plain numbers still hold them.
    assert (line.worse, line.better) == (0, 0)
    assert line.verdict is records.Verdict.NONE
    carriers = records.carrier_lines(
        blocks.with_columns(pl.lit("ZZ").alias("carrier")).lazy(), kinds.lazy()
    )
    # A carrier alone at its airport has no peer on any day: no line at all.
    assert ("AAA", "ZZ") not in carriers


def _score(p: float, rows: int, seen: int, trials: int = 100) -> fm.Score:
    chances = np.full(rows, p)
    return fm.score(
        chances,
        np.full(rows, 0.01),
        np.full(rows, float(seen)),
        np.full(rows, float(trials)),
    )


def test_a_high_bin_badly_over_said_fails_the_gate_even_beside_good_ones() -> None:
    # Many good 20-35% blocks, and a 50-75% bin of 4 block-days that saw nothing.
    good = [(0.25, 26)] * 200
    bad = [(0.6, 0)] * 4
    p = np.asarray([c for c, _ in good + bad])
    events = np.asarray([float(e) for _, e in good + bad])
    trials = np.full(len(p), 100.0)
    test = fm.score(p, np.full(len(p), 0.05), events, trials)
    assert test.bad_bins == 1
    assert not fm.passes("dep_canc", test)
    # A single block-day still counts when it has enough flights.
    one = fm.score(p[:-3], np.full(len(p) - 3, 0.05), events[:-3], trials[:-3])
    assert one.bad_bins == 1
    # A small single block-day is left to the pooled check.
    small = trials[:-3].copy()
    small[-1] = fm.SINGLE_FLIGHTS - 1
    few = fm.score(p[:-3], np.full(len(p) - 3, 0.05), events[:-3], small)
    assert few.bad_bins == 0


def _mix(*parts: tuple[float, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Block-days of ``(chance said, cancelled of 100, how many)``."""
    p = np.concatenate([np.full(n, c) for c, _, n in parts])
    events = np.concatenate([np.full(n, float(e)) for _, e, n in parts])
    return p, events, np.full(len(p), 100.0)


def test_a_bin_badly_under_said_fails_the_gate_as_well() -> None:
    # Good 20-35% blocks, and a 10-20% bin that saw two and a half times what it said.
    p, events, trials = _mix((0.25, 26, 200), (0.12, 30, fm.UNDER_ROWS))
    test = fm.score(p, np.full(len(p), 0.05), events, trials)
    assert test.under_bins == 1
    assert fm.CALIBRATION[0] <= test.calibration <= fm.CALIBRATION[1]  # the year's sum hides it
    assert not fm.passes("dep_canc", test)
    # Too few block-days to say: left to the other checks.
    p, events, trials = _mix((0.25, 26, 200), (0.12, 30, fm.UNDER_ROWS - 1))
    assert fm.score(p, np.full(len(p), 0.05), events, trials).under_bins == 0
    # Half again over what was said is still within the bound; under 2% said is not judged.
    p, events, trials = _mix((0.25, 26, 200), (0.12, 17, 10), (0.01, 9, 10))
    test = fm.score(p, np.full(len(p), 0.005), events, trials)
    assert test.under_bins == 0
    assert fm.passes("dep_canc", test)


def test_pooled_bins_said_too_low_take_out_the_worst_airports_first() -> None:
    # Three airports, each with too few 10-20% block-days to fail alone, that pooled saw over
    # twice what was said; and a fourth airport whose chances held.
    parts = [("AAA", 45), ("BBB", 40), ("CCC", 35)]
    p = np.concatenate([np.full(3, 0.15) for _ in parts] + [np.full(50, 0.25)])
    events = np.concatenate([np.full(3, float(e)) for _, e in parts] + [np.full(50, 25.0)])
    trials = np.full(len(p), 100.0)
    codes = np.array([c for c, _ in parts for _ in range(3)] + ["DDD"] * 50)
    for code, _ in parts:
        alone = codes == code
        assert fm.score(p[alone], p[alone], events[alone], trials[alone]).under_bins == 0
    assert fm.under_said(p, events, trials) == [(0.10, 0.20)]
    shown = np.ones(len(p), dtype=bool)
    assert fm.drop_under_said(p, events, trials, codes, shown) == ["AAA", "BBB"]
    assert shown.all()  # the caller's mask is left as it was
    assert fm.drop_under_said(p, events, trials, codes, codes == "DDD") == []


def test_the_day_after_a_storm_needs_its_bins_not_said_too_low() -> None:
    good = (0.3, 27, 100)
    p, events, trials = _mix(good)
    days = np.arange(len(p))
    lower = fm.skill_lower(p, np.full(len(p), 0.01), events, trials, days)
    assert lower > 0
    assert fm.after_storm_ok(fm.score(p, np.full(len(p), 0.01), events, trials), lower)
    # The 2-5% bin saw three times what it said (the R4-S1 after-storm bins).
    p, events, trials = _mix(good, (0.03, 10, 10))
    test = fm.score(p, np.full(len(p), 0.01), events, trials)
    assert fm.CALIBRATION[0] <= test.calibration <= fm.CALIBRATION[1]
    assert test.under_bins == 1
    assert not fm.after_storm_ok(test, 1.0)


def test_the_day_after_a_storm_needs_enough_events_and_a_sure_skill() -> None:
    # LR-F6: 15 rough days with skill +45% pooled are not enough; 50 events or more with a
    # skill sure by days are; a skill carried by one storm day is not sure by days.
    rng = np.random.default_rng(5)

    def rows(count: int, said: float, seen: float) -> tuple[np.ndarray, ...]:
        p = np.full(count, said)
        events = rng.binomial(1, seen, count).astype(float)
        return p, events, np.ones(count)

    p, events, trials = rows(170, 0.2, 0.09)
    events[:] = 0.0
    events[:15] = 1.0
    p[:15] = 0.6  # the model said more on the 15 days that were rough
    base = np.full(170, 16 / 170)
    test = fm.score(p, base, events, trials)
    lower = fm.skill_lower(p, base, events, trials, np.arange(170))
    assert test.events == 15
    assert test.skill > 0
    assert not fm.after_storm_ok(test, lower)  # under 50 events
    p, events, trials = _mix(good := (0.3, 27, 100))
    assert good[2] * good[1] >= fm.AFTER_MIN_EVENTS
    sure = fm.skill_lower(p, np.full(len(p), 0.01), events, trials, np.arange(len(p)))
    assert sure > 0
    # The same skill, all from one day: the day-level bound cannot be sure of it.
    one_day = fm.skill_lower(
        np.r_[np.full(99, 0.05), 0.9],
        np.full(100, 0.05),
        np.r_[np.zeros(99), 1.0],
        np.ones(100),
        np.r_[np.arange(99), 99],
    )
    assert one_day <= 0
    # Reproducible: the seed is fixed.
    again = fm.skill_lower(p, np.full(len(p), 0.01), events, trials, np.arange(len(p)))
    assert again == sure
    assert fm.skill_lower(p[:0], p[:0], p[:0], p[:0], np.arange(0)) == float("-inf")


def test_the_inputs_are_chosen_on_the_validation_year() -> None:
    checks = [
        ("day_", "dep_canc", 1, 0.0120, 0.0122),
        ("day_", "rough", 1, 0.0360, 0.0361),
        ("pre_", "dep_canc", 1, 0.012162, 0.012160),  # worse with them on the main target
        ("pre_", "dep_late", 1, 0.0830, 0.0840),
        ("pre_", "rough", 1, 0.0361, 0.0361),  # a tie is not better
    ]
    inputs, left = train.choose_inputs(checks)
    assert left == ("pre_", "obs_")  # obs_ has no check, so it is not shown to help
    assert all(not name.startswith(("pre_", "obs_")) for name in inputs)
    assert "day_snow" in inputs
    assert inputs == fm.without(("pre_", "obs_"))
    assert fm.columns(inputs) == sorted(fm.columns(inputs))
    every = tuple(g for g in train.VALIDATION_GROUPS)
    better = [(g, "dep_canc", 1, 0.01, 0.02) for g in every]
    assert train.choose_inputs(better) == (fm.FEATURES, ())


def test_the_chosen_inputs_are_scored_together_before_they_are_fitted() -> None:
    # Each group kept on its own check, the set kept only when, scored together on the
    # validation year, it is no worse than every input and than the same without day_*.
    chosen = fm.without(("pre_", "obs_"))
    no_day = tuple(name for name in chosen if not name.startswith("day_"))
    good = [("dep_canc", 1, 0.0120, 0.0121, 0.0122), ("rough", 1, 0.0360, 0.0360, 0.0365)]
    assert train.confirm_inputs(chosen, good) == chosen
    worse = [("dep_canc", 1, 0.0123, 0.0121, 0.0122), ("rough", 1, 0.0360, 0.0362, 0.0365)]
    assert train.confirm_inputs(chosen, worse) == fm.FEATURES  # every input no worse on both
    no_help = [("dep_canc", 1, 0.0123, 0.0124, 0.0120), ("rough", 1, 0.0361, 0.0362, 0.0360)]
    assert train.confirm_inputs(chosen, no_help) == no_day
    mixed = [("dep_canc", 1, 0.0123, 0.0121, 0.0125), ("rough", 1, 0.0360, 0.0362, 0.0365)]
    assert train.confirm_inputs(chosen, mixed) == fm.FEATURES  # none no worse on both


def test_a_model_of_fewer_inputs_fits_and_says_from_the_full_design() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=(400, len(fm.FEATURES)))
    inputs = fm.without(("obs_",))
    keep = fm.columns(inputs)
    trials = np.full(400, 50.0)
    events = np.round(trials * fm.expit(-3 + 0.8 * x[:, 1]))
    model = fm.Model(inputs=inputs)
    model.fitted[("dep_canc", 1)] = fm.fit(x[:, keep], events, trials)
    assert len(model.fitted[("dep_canc", 1)].coef) == len(inputs)
    moved = x.copy()
    moved[:, [fm.FEATURES.index(n) for n in fm.FEATURES if n.startswith("obs_")]] = 9.0
    assert np.allclose(model.chance("dep_canc", 1, x), model.chance("dep_canc", 1, moved))
    with pytest.raises(ValueError, match="order"):
        fm.columns(("snow", "base"))


def test_a_chance_must_hold_in_each_half_and_out_of_selection() -> None:
    strong = _score(0.3, 40, 30)
    weak = _score(0.3, 40, 1)
    assert fm.passes("dep_canc", strong, (strong, strong))
    assert not fm.passes("dep_canc", strong, (strong, weak))
    # Chosen on one half and scored on the other: luck on one half does not carry over.
    sure, even, odd = fm.confirmed("dep_canc", {"AAA": strong}, {"AAA": weak})
    assert (even, odd) == (1, 0)
    assert sure.skill < fm.MIN_TARGET_SKILL
    both, *_ = fm.confirmed("dep_canc", {"AAA": strong}, {"AAA": strong})
    assert both.skill > fm.MIN_TARGET_SKILL
    assert fm.combined(()).units == 0


def test_each_rows_usual_rate_comes_from_the_years_before_its_period() -> None:
    from snowlight.flights import train  # noqa: PLC0415

    # AAA cancels everything in Jan 2025 only; a row in that winter's period must not see it.
    days = [date(2022, 1, 1) + timedelta(days=7 * i) for i in range(200)]
    happened = pl.DataFrame(
        {
            "apt": ["AAA"] * len(days),
            "day": days,
            "block": [0] * len(days),
            "n": [100] * len(days),
            "canc": [100 if d.year == 2025 and d.month == 1 else 0 for d in days],
            "late": [0] * len(days),
        }
    )
    cut = train.Split(test_first=date(2025, 10, 1), test_last=date(2026, 9, 30))
    starts = train.periods(cut, date(2023, 3, 1))
    assert starts == [date(2025, 10, 1), date(2024, 10, 1), date(2023, 10, 1), date(2022, 10, 1)]
    rates = train.by_period(fm.base_rates, happened.lazy(), starts, None)
    january = rates.filter(pl.col("moy") == 1)
    own = january.filter(pl.col("period") == date(2024, 10, 1)).get_column("canc").item()
    after = january.filter(pl.col("period") == date(2025, 10, 1)).get_column("canc").item()
    assert own < 0.01 < after
    row = pl.DataFrame({"day": [date(2025, 1, 5), date(2025, 10, 2), date(2023, 1, 1)]})
    assert row.select(train.period_of(starts)).to_series().to_list() == [
        date(2024, 10, 1),
        date(2025, 10, 1),
        date(2022, 10, 1),
    ]


def _random_blocks(code: str, flights: int, share: float, days: int, seed: int) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    return pl.DataFrame(
        {
            "apt": [code] * days,
            "day": [date(2024, 1, 1) + timedelta(days=i) for i in range(days)],
            "block": [0] * days,
            "n": [flights] * days,
            "canc": rng.binomial(flights, share, days).tolist(),
        }
    )


def _kinds(blocks: pl.DataFrame, kind: Kind = Kind.THUNDER) -> pl.LazyFrame:
    return (
        blocks.select("apt", "day", "block")
        .unique()
        .with_columns(pl.lit(int(kind), dtype=pl.Int8).alias("kind"))
        .lazy()
    )


def _clustered(  # noqa: PLR0913
    code: str, flights: int, share: float, days: int, seed: int, *, carrier: str = "ZZ"
) -> pl.DataFrame:
    """Departures that go a whole block at a time: on a day share/0.5 of the time, half the
    block's flights are cancelled together, else none."""
    rng = np.random.default_rng(seed)
    hit = rng.random(days) < share / 0.5
    return pl.DataFrame(
        {
            "apt": [code] * days,
            "carrier": [carrier] * days,
            "day": [date(2024, 1, 1) + timedelta(days=i) for i in range(days)],
            "block": [0] * days,
            "n": [flights] * days,
            "canc": np.where(hit, flights // 2, 0).tolist(),
        }
    )


def test_a_small_airport_and_a_hub_at_the_same_share_get_no_verdict() -> None:
    # The same share, cancelled at random, beside a large pool of others at that share: the
    # small airport's days go one way or the other on one cancel (most are BETTER), but the
    # pooled shares are not apart, so neither is told it differs.
    told_small = told_hub = 0
    tries = 20
    for seed in range(tries):
        small = _random_blocks("SML", 4, 0.06, 300, seed=3 * seed)
        hub = _random_blocks("HUB", 120, 0.06, 300, seed=3 * seed + 1)
        pool = _random_blocks("OTH", 2000, 0.06, 300, seed=3 * seed + 2)
        blocks = pl.concat([small, hub, pool])
        lines = records.airport_lines(blocks.lazy(), _kinds(blocks))
        told_small += lines["SML"][0].verdict is not records.Verdict.NONE
        told_hub += lines["HUB"][0].verdict is not records.Verdict.NONE
    assert told_small <= 2
    assert told_hub <= 2


def test_a_carrier_at_the_others_share_cancelling_whole_blocks_gets_no_verdict() -> None:
    # Cancels in clusters (half a block on one day, none on the next) at the others' share:
    # most days it is BETTER, a few far WORSE; the pooled shares agree, so no verdict.
    told = 0
    tries = 20
    for seed in range(tries):
        mine = _clustered("AAA", 40, 0.06, 300, seed=2 * seed)
        others = _random_blocks("AAA", 400, 0.06, 300, seed=2 * seed + 1).with_columns(
            pl.lit("YY").alias("carrier")
        )
        blocks = pl.concat([mine, others.select(mine.columns)])
        line = records.carrier_lines(blocks.lazy(), _kinds(blocks))[("AAA", "ZZ")][0]
        assert line.days == 300 - 5  # the July 2024 outage left out
        told += line.verdict is not records.Verdict.NONE
    assert told <= 2


def test_storm_only_weather_at_the_peers_share_gets_no_verdict() -> None:
    # AAA has snow only on 60 big storm days, where AAA, BBB and CCC all cancel 30%; BBB and
    # CCC also have 300 mild snow days at 2%. Pooled over all snow days AAA would read far
    # above the others and BBB and CCC below; held to the same day, all three are like it.
    rows: list[tuple[str, date, int, int, int]] = []
    start = date(2018, 1, 1)
    for i in range(60):
        day = start + timedelta(days=7 * i)
        rows += [(apt, day, block, 40, 12) for apt in ("AAA", "BBB", "CCC") for block in range(5)]
    for i in range(300):
        day = start + timedelta(days=7 * i + 3)
        rows += [(apt, day, block, 50, 1) for apt in ("BBB", "CCC") for block in range(5)]
    blocks = pl.DataFrame(rows, schema=["apt", "day", "block", "n", "canc"], orient="row")
    lines = records.airport_lines(blocks.lazy(), _kinds(blocks, Kind.SNOW))
    for code in ("AAA", "BBB", "CCC"):
        (line,) = lines[code]
        assert line.verdict is records.Verdict.NONE, code
        assert (line.worse, line.better) == (0, 0)
    assert lines["AAA"][0].others_share == pytest.approx(0.30)
    # 360 days, less the COVID-19 span's mild days (13 weeks of 2020).
    assert lines["BBB"][0].days == 360 - 13
    # The others' share shown beside each line is its peers' on its own days at its own
    # departures, so the plain numbers never suggest a difference the days do not hold.
    for code in ("AAA", "BBB", "CCC"):
        (line,) = lines[code]
        assert records.per_mille(line.others_share) == records.per_mille(line.share), code


@pytest.mark.parametrize(
    ("mine", "theirs", "want"), [(0.09, 0.03, "SOONER"), (0.03, 0.09, "LONGER")]
)
def test_shares_three_times_apart_over_hundreds_of_days_get_the_verdict(
    mine: float, theirs: float, want: str
) -> None:
    for seed in range(5):
        own = _random_blocks("AAA", 150, mine, 300, seed=2 * seed)
        pool = pl.concat(
            [_random_blocks(f"O{i}", 80, theirs, 300, seed=50 * seed + i) for i in range(6)]
        )
        blocks = pl.concat([own, pool])
        line = records.airport_lines(blocks.lazy(), _kinds(blocks))["AAA"][0]
        assert line.verdict is records.Verdict[want]
        assert line.others_share == pytest.approx(theirs, rel=0.15)


def test_a_day_counts_worse_or_better_by_two_points_and_half_again() -> None:
    def marks(mine: int, theirs: int) -> tuple[int, int]:
        blocks = pl.DataFrame(
            {
                "apt": ["AAA", "BBB"],
                "day": [date(2024, 1, 2)] * 2,
                "block": [0, 0],
                "n": [1000, 1000],
                "canc": [mine, theirs],
            }
        )
        line = records.airport_lines(blocks.lazy(), _kinds(blocks))["AAA"][0]
        return line.worse, line.better

    assert marks(60, 40) == (1, 0)  # 2 points and 1.5 times
    assert marks(59, 40) == (0, 0)  # under 1.5 times
    assert marks(30, 10) == (1, 0)  # 2 points, 3 times
    assert marks(29, 10) == (0, 0)  # under 2 points
    assert marks(40, 60) == (0, 1)
    assert marks(0, 20) == (0, 1)
    assert marks(0, 19) == (0, 0)


def _exact_tails(q: list[float], hits: int) -> tuple[float, float]:
    """The Poisson-binomial tails by listing every outcome."""
    few = many = 0.0
    for outcome in itertools.product((0, 1), repeat=len(q)):
        chance = math.prod(c if o else 1 - c for o, c in zip(outcome, q, strict=True))
        few += chance if sum(outcome) <= hits else 0.0
        many += chance if sum(outcome) >= hits else 0.0
    return few, many


def test_the_tests_under_the_peers_own_shares() -> None:
    # The Poisson-binomial tails match every outcome listed; at 1 in 2 they are the sign test's.
    q = [0.1, 0.5, 0.7, 0.9, 0.3, 0.6]
    for hits in range(len(q) + 1):
        assert records.poisson_binomial_p(np.array(q), hits) == pytest.approx(_exact_tails(q, hits))
    assert records.poisson_binomial_p(np.full(8, 0.5), 0)[0] == pytest.approx(1 / 256)
    # Each day's chance of WORSE and BETTER at the peers' share matches the binomial by hand,
    # by the same lines as the marks.
    n = np.array([100, 4, 20, 3], dtype=np.int64)
    pn = np.array([1000, 1000, 2000, 50], dtype=np.int64)
    pc = np.array([60, 300, 100, 1], dtype=np.int64)
    worse, better = records.day_chances(n, pn, pc)
    for i in range(len(n)):
        share = pc[i] / pn[i]
        law = [
            math.comb(int(n[i]), k) * share**k * (1 - share) ** (n[i] - k) for k in range(n[i] + 1)
        ]
        ks = np.arange(n[i] + 1, dtype=np.int64)
        w, b = records._marks(
            ks, np.full_like(ks, n[i]), np.full_like(ks, pn[i]), np.full_like(ks, pc[i])
        )
        assert worse[i] == pytest.approx(sum(law[k] for k in ks[w]), abs=1e-12)
        assert better[i] == pytest.approx(sum(law[k] for k in ks[b]), abs=1e-12)
    # The day-clustered check: a gap the day-to-day spread explains is luck; one far outside
    # it is not; a run of no-cancel days on a few departures is held to the binomial spread.
    expected = np.full(100, 2.0)
    share = np.full(100, 0.02)
    assert records.clustered_p(np.full(100, 2, dtype=np.int64), expected, share) == 1.0
    lumpy = np.where(np.arange(100) % 10 == 0, 30, 0).astype(np.int64)
    assert records.clustered_p(lumpy, expected, share) > 0.05
    assert records.clustered_p(np.full(100, 4, dtype=np.int64), expected, share) < 1e-6
    few = np.full(10, 0.15)
    assert records.clustered_p(np.zeros(10, dtype=np.int64), few, np.full(10, 0.05)) > 0.05
    # R6-S1: with day clustering rho each day's chances are the beta-binomial's, by hand.
    rho = 0.25
    size = (1 - rho) / rho
    worse, better = records.day_chances(n, pn, pc, rho)
    for i in range(len(n)):
        share = pc[i] / pn[i]
        a, b = share * size, (1 - share) * size
        law = [
            math.comb(int(n[i]), k)
            * math.exp(
                math.lgamma(k + a)
                + math.lgamma(n[i] - k + b)
                - math.lgamma(n[i] + a + b)
                - math.lgamma(a)
                - math.lgamma(b)
                + math.lgamma(a + b)
            )
            for k in range(n[i] + 1)
        ]
        ks = np.arange(n[i] + 1, dtype=np.int64)
        w, bt = records._marks(
            ks, np.full_like(ks, n[i]), np.full_like(ks, pn[i]), np.full_like(ks, pc[i])
        )
        assert worse[i] == pytest.approx(sum(law[k] for k in ks[w]), abs=1e-9)
        assert better[i] == pytest.approx(sum(law[k] for k in ks[bt]), abs=1e-9)
    # A sample of quiet days that missed the rare big ones: sure under the binomial spread,
    # luck under the clustered spread of its departures.
    quiet = np.full(200, 100, dtype=np.int64)
    quiet_share = np.full(200, 0.05)
    quiet_expected = quiet * quiet_share
    quiet_canc = np.full(200, 4, dtype=np.int64)
    assert records.clustered_p(quiet_canc, quiet_expected, quiet_share) < 0.01
    assert records.clustered_p(quiet_canc, quiet_expected, quiet_share, 0.25, quiet) > 0.05
    # The pooled guard: 1.25 times as computed and as published.
    assert records._apart(0.0626, 0.05)
    assert not records._apart(0.0625, 0.05)  # 62 vs 50 per mille as published
    assert not records._apart(0.062, 0.05)
    assert not records._apart(0.0025, 0.002)  # 3 vs 2 per mille as computed, 2 vs 2 shown
    assert records._apart(0.003, 0.002)
    assert not records._apart(0.0004, 0.0)  # none shown


def _null_world(  # noqa: PLR0913, PLR0917 - the world's shape
    rng: np.random.Generator, lines: int, low: int, high: int, days: int, cluster: float | None
) -> pl.DataFrame:
    """``lines`` airports of ``low`` to ``high`` departures a day beside a big pool, each day's
    share of every airport drawn at the pool's share that day (and day-clustered when
    ``cluster`` is the beta concentration): no airport differs from its peers."""
    shares = rng.beta(0.6, 12, days)
    day = [date(2018, 1, 1) + timedelta(days=i) for i in range(days)]
    rows: list[pl.DataFrame] = []
    for i in range(lines + 1):
        flights = (np.full(days, 3000) if i == lines else rng.integers(low, high + 1, days)).astype(
            np.int64
        )
        each = shares
        if cluster is not None and i < lines:
            each = rng.beta(
                np.maximum(shares * cluster, 1e-6), np.maximum((1 - shares) * cluster, 1e-6)
            )
        rows.append(
            pl.DataFrame(
                {
                    "apt": [f"P{i:03d}"] * days,
                    "day": day,
                    "block": [0] * days,
                    "n": flights,
                    "canc": rng.binomial(flights, each).astype(np.int64),
                }
            )
        )
    return pl.concat(rows)


@pytest.mark.parametrize("cluster", [None, 20.0, 8.0, 3.0])
@pytest.mark.parametrize(("low", "high"), [(3, 12), (12, 60), (60, 400)])
def test_airports_at_their_peers_share_are_seldom_told_they_differ(
    cluster: float | None, low: int, high: int
) -> None:
    # Many airports, small to large, each cancelling at its peers' same-day share (binomial,
    # and day-clustered down to the data's own concentration of about 3, R6-S1): LONGER and
    # SOONER each come out at most 5% of the time (LR-F5).
    told = {records.Verdict.SOONER: 0, records.Verdict.LONGER: 0}
    total = 0
    for seed in range(6):
        rng = np.random.default_rng(1000 * seed + low)
        world = _null_world(rng, 30, low, high, int(rng.integers(60, 400)), cluster)
        for code, lines in records.airport_lines(world.lazy(), _kinds(world)).items():
            if code == "P030":
                continue
            total += 1
            verdict = lines[0].verdict
            if verdict is not records.Verdict.NONE:
                told[verdict] += 1
    assert total == 6 * 30
    assert told[records.Verdict.LONGER] <= 0.05 * total
    assert told[records.Verdict.SOONER] <= 0.05 * total


@pytest.mark.parametrize("cluster", [None, 20.0, 8.0, 3.0])
def test_carriers_at_their_peers_share_are_seldom_told_they_differ(cluster: float | None) -> None:
    told = {records.Verdict.SOONER: 0, records.Verdict.LONGER: 0}
    total = 0
    for seed in range(4):
        rng = np.random.default_rng(77 + seed)
        world = _null_world(rng, 40, 2, 15, int(rng.integers(60, 300)), cluster)
        carriers = world.with_columns(pl.col("apt").alias("carrier"), pl.lit("AAA").alias("apt"))
        for (_, code), lines in records.carrier_lines(carriers.lazy(), _kinds(carriers)).items():
            if code == "P040":
                continue
            total += 1
            verdict = lines[0].verdict
            if verdict is not records.Verdict.NONE:
                told[verdict] += 1
    assert total == 4 * 40
    assert told[records.Verdict.LONGER] <= 0.05 * total
    assert told[records.Verdict.SOONER] <= 0.05 * total


def test_a_small_airport_that_never_cancels_beside_a_few_percent_gets_no_verdict() -> None:
    # The RDD-like case: about 78 departures over 26 fog days, none cancelled, beside peers at
    # 4.9%. At three departures a day no day expects a cancel, so no day is counted.
    days = 26
    small = pl.DataFrame(
        {
            "apt": ["RDD"] * days,
            "day": [date(2024, 1, 1) + timedelta(days=i) for i in range(days)],
            "block": [0] * days,
            "n": [3] * days,
            "canc": [0] * days,
        }
    )
    pool = small.with_columns(
        pl.lit("OTH").alias("apt"),
        pl.lit(2000, dtype=pl.Int64).alias("n"),
        pl.lit(98, dtype=pl.Int64).alias("canc"),
    )
    blocks = pl.concat([small, pool])
    line = records.airport_lines(blocks.lazy(), _kinds(blocks, Kind.FOG))["RDD"][0]
    assert (line.days, line.worse, line.better) == (days, 0, 0)
    assert line.share == 0.0
    assert line.others_share == pytest.approx(0.049)
    assert line.verdict is records.Verdict.NONE


def test_published_words_always_agree_with_the_published_shares() -> None:
    rng = np.random.default_rng(11)
    seen = {records.Verdict.NONE: 0, records.Verdict.SOONER: 0, records.Verdict.LONGER: 0}
    for trial in range(30):
        frames = [
            _clustered(
                f"A{i}",
                int(rng.integers(3, 300)),
                float(rng.uniform(0.005, 0.2)),
                int(rng.integers(5, 200)),
                seed=100 * trial + i,
            ).drop("carrier")
            for i in range(4)
        ]
        blocks = pl.concat(frames)
        for lines in records.airport_lines(blocks.lazy(), _kinds(blocks)).values():
            for line in lines:
                seen[line.verdict] += 1
                share, others = records.per_mille(line.share), records.per_mille(line.others_share)
                if line.verdict is records.Verdict.SOONER:
                    assert line.worse > line.better
                    assert 4 * share >= 5 * others
                    assert share > 0
                if line.verdict is records.Verdict.LONGER:
                    assert line.better > line.worse
                    assert 4 * others >= 5 * share
                    assert others > 0
                if line.worse + line.better < records.MIN_UNTIED:
                    assert line.verdict is records.Verdict.NONE
    assert all(seen.values())


def test_a_hub_at_half_the_others_share_holds_out_longer() -> None:
    found = []
    for seed in range(10):
        hub = _clustered("HUB", 120, 0.03, 320, seed=2 * seed)
        pool = pl.concat(
            [_clustered(f"O{i}", 60 + 40 * i, 0.06, 320, seed=100 * seed + i) for i in range(8)]
        )
        blocks = pl.concat([hub, pool]).drop("carrier")
        found.append(records.airport_lines(blocks.lazy(), _kinds(blocks))["HUB"][0].verdict)
    assert found.count(records.Verdict.LONGER) >= 9


def test_a_small_airport_with_one_cancel_a_block_is_judged_by_its_share() -> None:
    # Twenty departures a day and five cancelled every day: every block "bad" (a quarter), yet
    # beside others at a quarter it gets no verdict; beside others at a twentieth (one cancel
    # expected a day, so each day counts) it is sooner.
    days = 40
    small = pl.DataFrame(
        {
            "apt": ["SML"] * days,
            "day": [date(2024, 1, 1) + timedelta(days=i) for i in range(days)],
            "block": [0] * days,
            "n": [20] * days,
            "canc": [5] * days,
        }
    )
    for share, want in ((0.25, records.Verdict.NONE), (0.05, records.Verdict.SOONER)):
        pool = _random_blocks("OTH", 400, share, days, seed=7).drop("late", strict=False)
        blocks = pl.concat([small, pool.select(small.columns)])
        line = records.airport_lines(blocks.lazy(), _kinds(blocks))["SML"][0]
        assert line.bad_days == days
        assert line.verdict is want


def test_non_weather_days_are_never_counted() -> None:
    # AAA cancels everything in the July 2024 outage and nothing else: never "sooner".
    outage = [date(2024, 7, 19) + timedelta(days=i) for i in range(5)]
    quiet = [date(2024, 8, 1) + timedelta(days=i) for i in range(20)]
    aaa = pl.DataFrame(
        {
            "apt": ["AAA"] * 25,
            "day": outage + quiet,
            "block": [0] * 25,
            "n": [100] * 25,
            "canc": [100] * 5 + [2] * 20,
        }
    )
    bbb = aaa.with_columns(pl.lit("BBB").alias("apt"), pl.lit(2, dtype=pl.Int64).alias("canc"))
    blocks = pl.concat([aaa, bbb])
    line = records.airport_lines(blocks.lazy(), _kinds(blocks))["AAA"][0]
    assert line.days == 20
    assert line.share == pytest.approx(0.02)
    assert line.verdict is records.Verdict.NONE
    per = records.carrier_lines(
        pl.concat(
            [
                blocks.with_columns(pl.lit("ZZ").alias("carrier")),
                blocks.with_columns(pl.lit("YY").alias("carrier")),
            ]
        ).lazy(),
        _kinds(blocks),
    )
    assert per[("AAA", "ZZ")][0].days == 20


def test_the_day_clustering_is_read_from_the_lines_themselves() -> None:
    # R6-S1: each line's moment sums of its day clustering against its peers' shares; the
    # larger of the median over lines (so a few big lines never set it low for the many small)
    # and the pooled estimate (where the big lines weigh most), between 0 and the cap.
    rng = np.random.default_rng(3)
    days = 400
    share = np.full(days, 0.05)
    n = np.full(days, 200, dtype=np.int64)
    for kappa in (3.0, 20.0):
        each = rng.beta(share * kappa, (1 - share) * kappa)
        found = records.line_clustering(n, rng.binomial(n, each).astype(np.int64), share)
        assert found is not None
        assert found[0] / found[1] == pytest.approx(1 / (kappa + 1), abs=0.06)
    plain = records.line_clustering(n, rng.binomial(n, share).astype(np.int64), share)
    assert plain is not None
    assert abs(plain[0] / plain[1]) < 0.01
    assert records.line_clustering(n, np.zeros(days, dtype=np.int64), np.zeros(days)) is None
    assert records.day_clustering([]) == 0.0
    assert records.day_clustering([(-1.0, 10.0), (-2.0, 10.0), (0.0, 10.0)]) == 0.0
    # Three small lines that barely cluster and one big one that clusters hard: the pooled
    # estimate, which the big line sets, wins over the small lines' median.
    small = [(0.1, 10.0), (0.2, 10.0), (0.0, 10.0)]
    assert records.day_clustering(small) == pytest.approx(0.01)
    assert records.day_clustering([*small, (300.0, 1000.0)]) == pytest.approx(300.3 / 1030)
    # Many small lines that cluster and one big one that does not: the median wins.
    assert records.day_clustering([(3.0, 10.0)] * 5 + [(0.0, 1000.0)]) == pytest.approx(0.3)
    assert records.day_clustering([(2.0, 1.0)]) == records.MAX_CLUSTERING
