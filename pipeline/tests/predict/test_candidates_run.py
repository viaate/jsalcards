"""The candidates' archive test on a made-up world: the stages' walk-forward, the checks and
verdicts, the inputs table, the owner table and the report.

Every district, day and outcome here is made up for the tests; nothing comes from a real list
or a real storm.
"""

import dataclasses
import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from scipy import sparse  # type: ignore[import-untyped]

from snowlight.predict import backtest_terms, candidates, candidates_cli, candidates_run, train
from snowlight.predict.backtest import FoldRows
from snowlight.predict.backtest_terms import Base
from snowlight.predict.candidates import Units
from snowlight.predict.candidates_cli import (
    TODAY,
    Context,
    Inputs,
    InputTable,
    RowSet,
    Spec,
    World,
)
from snowlight.predict.config import PredictConfig
from snowlight.predict.pool import Places, Rows
from snowlight.predict.situations import SITUATIONS, WeatherClass
from snowlight.predict.terms import TERM_ORDER, UNKNOWN, Term

ADVISORY = next(
    i for i, s in enumerate(SITUATIONS) if s.weather == WeatherClass.ADVISORY and not s.after
)
QUIET = next(i for i, s in enumerate(SITUATIONS) if s.weather == WeatherClass.NONE and not s.after)
DISTRICTS = tuple(f"d{i}" for i in range(6))


def _places() -> Places:
    return Places(
        districts=DISTRICTS,
        region=np.zeros(6, np.int64),
        state=np.array([0, 0, 0, 1, 1, 1], np.int64),
        county=np.arange(6, dtype=np.int64),
        neighbors=sparse.csr_matrix((6, 6)),
        regions=("northeast",),
        states=("NY", "CT"),
        counties=tuple(f"c{i}" for i in range(6)),
    )


def _row_set(seasons: list[int], seed: int, days_per_season: int = 4) -> RowSet:
    rng = np.random.default_rng(seed)
    district: list[int] = []
    situation: list[int] = []
    season_of: list[int] = []
    day: list[date] = []
    for season in seasons:
        for k in range(days_per_season):
            when = date(season + 1, 1, 10) + timedelta(days=7 * k)
            for d in range(6):
                district.append(d)
                situation.append(QUIET if (d + k) % 5 == 0 else ADVISORY)
                season_of.append(season)
                day.append(when)
    n = len(district)
    temperature = rng.integers(-1, 3, n).astype(np.int64)
    mixed = rng.random(n) < 0.3
    timing = rng.integers(-1, 4, n).astype(np.int64)
    warm = temperature == candidates.WARM
    p = np.where(warm, 0.35, 0.75)
    y = (rng.random(n) < p).astype(float)
    outcome = np.where(y == 1, "no_school", np.where(rng.random(n) < 0.3, "delayed", "open"))
    rows = Rows(
        np.array(district, np.int64), np.array(situation, np.int64),
        np.array(season_of, np.int64), y,
    )  # fmt: skip
    counted = np.array([int(SITUATIONS[s].weather) for s in situation], np.int64)
    base_p = np.full(n, 0.6)
    frame = pl.DataFrame(
        {
            "district": [DISTRICTS[d] for d in district],
            "day": day,
            "outcome": outcome.tolist(),
            "cluster": ["New York DMA" if d < 3 else "Hartford DMA" for d in district],
        }
    )
    levels = {t: np.full(n, UNKNOWN, np.int64) for t in TERM_ORDER}
    snow = rng.integers(0, 6, n).astype(np.int64)
    levels[Term.SNOW_ADVISORY] = snow
    levels[Term.SNOW_STORM] = snow.copy()
    return RowSet(
        frame=frame,
        rows=rows,
        base=Base(base_p, base_p.copy(), counted),
        q=np.full(n, 0.3),
        levels=levels,
        inputs=Inputs(temperature, mixed, np.ones(n, np.bool_), timing, rng.random(n) < 0.5),
        day=np.array([d.toordinal() for d in day], np.int64),
        units=Units(np.array([0, 0, 0, 1, 1, 1] * (n // 6), np.int64), np.zeros(n, np.int64)),
    )


def _world() -> World:
    config = PredictConfig.load()
    climate = candidates.Climate({}, {}, {}, np.array([50.0, 30.0, 10.0, 7.0, 3.0]))
    training = {2023: _row_set([2020, 2021, 2022], 1, 6), 2024: _row_set([2020, 2021, 2022, 2023], 2, 6)}  # fmt: skip # noqa: E501
    return World(
        _row_set([2023, 2024], 3), training, (2023, 2024), _places(), config.model,
        {2023: climate, 2024: climate},
    )  # fmt: skip


def _context(world: World) -> Context:
    frame = world.test.frame
    n = frame.height
    return Context(
        clusters=list(zip(frame["day"].to_list(), frame["cluster"].to_list(), strict=True)),
        day=world.test.day,
        market=frame["cluster"].to_list(),
        code=np.full(n, 3, np.int64),
        northeast=np.ones(n, np.bool_),
        region=["northeast"] * n,
        neighbor=np.zeros(n, np.bool_),
    )


@pytest.fixture(scope="module")
def world() -> World:
    return _world()


def test_today_s_model_is_the_base_itself(world: World) -> None:
    found = candidates_cli.walk(TODAY, world, with_delay=True)
    assert [f.season for f in found.folds] == [2023, 2024]
    for fold in found.folds:
        assert np.array_equal(fold.p_terms, world.test.base.p[fold.rows])
    assert found.delay is not None
    assert np.allclose(found.delay, 0.3)


def test_c2_takes_away_on_warm_days_and_leaves_quiet_days(world: World) -> None:
    spec = Spec("C2a", c2=True)
    today = candidates_cli.walk(TODAY, world)
    found = candidates_cli.walk(spec, world)
    model = found.models[2024]
    assert model.extra[0] + model.extra[1] < 0  # warm closes less here
    assert model.extra[3] >= 0  # cold and mixed only adds
    folds = candidates_cli.against(found, today)
    assert candidates_cli.no_alert_changed(folds, world.test.rows) == 0
    config = PredictConfig.load()
    context = _context(world)
    result = candidates_cli.compare("C2a", found, today, "today", world, context, config)
    assert result.verdict.verdict in {"no archive evidence", "archive support", "harm (veto)"}
    text = "\n".join(candidates_cli.comparison_markdown(result, spec, found))
    assert "## C2a" in text
    assert "warm_32" in text
    assert candidates_cli.comparison_json(result)["name"] == "C2a"
    moved = candidates_cli.moved_dates(found, today, world)
    assert moved
    assert all(isinstance(d, int) for d in moved)


def test_every_stage_runs(world: World) -> None:
    for spec in (
        Spec("C3", c3=True),
        Spec("control", piece3=True),
        Spec("control with gate", piece3=True, gate=True, c3=True),
        Spec("C4", piece3=True, c4=True),
        Spec("C1", c1=True),
    ):
        found = candidates_cli.walk(spec, world, with_delay=spec.c3)
        for fold in found.folds:
            assert np.all((fold.p_terms >= 0.01) & (fold.p_terms <= 0.99))
    published, raw, moved = world.c1_base("test")
    served, split = world.c1_detail["test"]
    assert moved.tolist() == (served | split).tolist()
    assert served.any()
    assert np.allclose(published, np.round(published, 2))
    assert not np.isnan(raw).any()


def test_against_refuses_different_rows(world: World) -> None:
    today = candidates_cli.walk(TODAY, world)
    shorter = candidates_cli.Walk(today.folds[:1], today.models, today.training)
    with pytest.raises(ValueError, match=r"zip|rows"):
        candidates_cli.against(today, shorter)
    other = candidates_cli.Walk([today.folds[1], today.folds[0]], today.models, today.training)
    with pytest.raises(ValueError, match="different rows"):
        candidates_cli.against(today, other)


def test_the_verdict_rules() -> None:
    gates = backtest_terms.TermGates(10, 0.1, 0.09, (), 0, (), True, 0, math.nan, math.nan)
    y = np.array([1.0, 0.0, 1.0, 0.0])
    scored = backtest_terms.Scored(
        y, np.array([0.5, 0.5, 0.5, 0.5]), np.array([0.6, 0.4, 0.6, 0.4]),
        np.array([1, 1, 2, 3]), ("a", "a", "b", "c"), np.ones(4, np.int64),
    )  # fmt: skip
    checks = backtest_terms.run_checks(scored, draws=50)
    found = candidates_cli.judge_verdict("x", gates, checks, scored, 0, None)
    assert found.verdict == "no archive evidence"
    assert "P8 not run" in found.support
    harmed = candidates_cli.judge_verdict("x", gates, checks, scored, 3, 0.05, ["extra"])
    assert harmed.verdict == "harm (veto)"
    assert len(harmed.harm) == 3
    assert candidates_cli.gain_without_raises(scored) > 0  # the lowered rows alone gain


def test_delay_scores_and_chances(world: World) -> None:
    today = candidates_cli.walk(TODAY, world, with_delay=True)
    p = candidates_cli.chance_of(today, len(world.test.rows))
    assert today.delay is not None
    rows, delay_brier, log = candidates_cli.delay_scores(
        p, today.delay, world, ~np.isnan(p), world.settings
    )
    assert rows == int((~np.isnan(p)).sum())
    assert 0 <= delay_brier <= 1
    assert log > 0
    named = candidates_cli.per_date(
        today.folds, world.test.rows, world.test.day, [date(2024, 1, 10)]
    )
    assert named[0][1] > 0


def test_the_owner_table_and_the_diagnostics(world: World) -> None:
    context = _context(world)
    today = candidates_cli.walk(TODAY, world)
    c2 = candidates_cli.walk(Spec("C2a", c2=True), world)
    n = len(world.test.rows)
    lines = candidates_cli.owner_table(
        ["today", "C2a"], [candidates_cli.chance_of(today, n), candidates_cli.chance_of(c2, n)],
        world, context,
    )  # fmt: skip
    assert any(line.startswith("| advisory |") for line in lines)
    assert any(line.startswith("| northeast |") for line in lines)
    path = candidates_run.penalty_path(Spec("C2a", c2=True), world)
    assert len(path) == 2 + 8
    snow = candidates_run.penalty_path(Spec("C4", piece3=True, c4=True), world)
    assert "snow_advisory" in snow[-1]
    rows, before, after = candidates_run.date_forward(Spec("C2a", c2=True), world)
    assert rows > 0
    assert 0 <= before <= 1
    assert 0 <= after <= 1
    shifted = candidates_cli.with_inputs(world, lambda f: _flip(world, f))
    gain = candidates_cli.shifted_gain(
        candidates_cli.walk(Spec("C2a", c2=True), shifted), candidates_cli.walk(TODAY, shifted),
        shifted, context,
    )  # fmt: skip
    assert math.isfinite(gain)
    assert "rows" in candidates_run._input_counts(world, c2)
    assert "|" in candidates_run._advisory_buckets(world, context, today, c2)[0]


def _flip(world: World, frame: pl.DataFrame) -> Inputs:
    found = world.test if frame.height == world.test.frame.height else None
    source = found or next(r for r in world.training.values() if r.frame.height == frame.height)
    inputs = source.inputs
    return Inputs(inputs.temperature[::-1].copy(), inputs.mixed, inputs.snow, inputs.timing, inputs.gate)  # fmt: skip # noqa: E501


def test_the_input_table_reads_a_district_day_as_of_21() -> None:
    values = pl.DataFrame(
        {
            "district": ["d0", "d0"],
            "day": [date(2023, 2, 28), date(2023, 3, 14)],
            "zone": ["America/New_York"] * 2,
            "temp_h07": [34.5, 25.0],
            "snow_window": [1.0, 6.0],
            "qpf_e06": [0.2, 0.1], "qpf_e12": [0.3, 0.2], "qpf_e18": [0.1, 0.2],
            "snow_e06": [0.5, 1.0], "snow_e12": [0.5, 2.0], "snow_e18": [0.0, 3.0],
            "snow_e24": [0.0, 0.5],
        }
    )  # fmt: skip
    alerts = pl.DataFrame(
        {
            "district": ["d0"],
            "day": [date(2023, 2, 28)],
            "start": [datetime(2023, 2, 28, 1, 0, tzinfo=UTC)],
            "began": [None],
            "end": [datetime(2023, 2, 28, 11, 0, tzinfo=UTC)],
            **{w: [False] for w in candidates.MIX_WORDS},
        },
        schema_overrides={"began": pl.Datetime("us", "UTC")},
    )
    table = pl.DataFrame({"district": ["d0", "d1"], "time_zone": ["America/New_York", None]})
    found = InputTable.build(values, alerts, table)
    # Warm, mixed by amounts (0.6 in of liquid, 1 in of snow), the alert ends at 6 AM.
    assert found.one("d0", date(2023, 2, 28)) == (
        candidates.WARM, True, True, candidates.ENDS_EARLY, True,
    )  # fmt: skip
    assert found.one("d0", date(2023, 3, 14))[:3] == (candidates.COLD, False, True)
    assert found.shifted("d0", date(2023, 2, 28)) == date(2023, 3, 14)
    assert found.shifted("d0", date(2023, 3, 14)) == date(2023, 2, 28)
    assert found.shifted("d9", date(2023, 3, 14)) == date(2023, 3, 14)
    frame = pl.DataFrame({"district": ["d0", "d1"], "day": [date(2023, 2, 28), date(2023, 2, 28)]})
    plain = found.inputs(frame)
    assert plain.temperature.tolist() == [candidates.WARM, UNKNOWN]
    shifted = found.inputs(frame, shift=True)
    assert shifted.temperature.tolist() == [candidates.COLD, UNKNOWN]
    assert found.inputs(frame.head(0)).temperature.size == 0
    assert plain.kind.tolist() == [candidates.KIND_WARM, candidates.KIND_UNKNOWN]
    assert plain.subset(np.array([True, False])).temperature.tolist() == [candidates.WARM]


def test_morning_inputs_read_the_5_am_report() -> None:
    morning = pl.DataFrame(
        {
            "district": ["d0", "d1"], "day": [date(2023, 2, 28)] * 2, "tmpf": [33.0, 20.0],
            "rain": [True, False], "sleet": [False, False], "freezing": [False, False],
            "drizzle": [False, False], "mix": [False, False],
        }
    )  # fmt: skip
    frame = pl.DataFrame({"district": ["d0", "d1", "d2"], "day": [date(2023, 2, 28)] * 3})
    found = candidates_cli.morning_inputs(frame, morning)
    assert found.temperature.tolist() == [candidates.NEAR, candidates.COLD, UNKNOWN]
    assert found.mixed.tolist() == [True, False, False]
    assert found.snow.all()


def test_fold_files(tmp_path: object) -> None:
    from pathlib import Path  # noqa: PLC0415

    folder = Path(str(tmp_path))
    places = _places()
    frame = pl.DataFrame(
        {
            "district": ["d0", "d1", "d1"],
            "day": [date(2021, 1, 5), date(2021, 1, 5), date(2021, 1, 6)],
            "season": [2020, 2020, 2020],
            "outcome": ["no_school", "open", "delayed"],
            "weather": [1, 1, 1],
            "after": [False, False, False],
        },
        schema_overrides={"weather": pl.Int8, "season": pl.Int32},
    )
    frame.write_parquet(folder / "labels-2021.parquet")
    found = candidates_cli.read_fold_0500(folder, [2021, 2022], places)
    assert list(found.usable) == [2021]
    assert len(found.training[2021].rows) == 3
    assert len(found.training[2021].delay_rows) == 2
    without = candidates_cli.fold_without(found, date(2021, 1, 5).toordinal())
    assert len(without.training[2021].rows) == 1
    assert len(without.training[2021].delay_rows) == 1
    assert isinstance(without, train.FoldSet)
    assert isinstance(found.training[2021], FoldRows)


def test_the_command_and_its_report_pieces(world: World, tmp_path: object) -> None:
    from pathlib import Path  # noqa: PLC0415

    from snowlight.cli import build_parser  # noqa: PLC0415

    args = build_parser().parse_args(
        ["predict", "candidates", "--codes", "c", "--extract", "e", "--alerts", "a",
         "--morning", "m", "--labels-0500", "l", "--folds-0500", "f", "--out", "o", "--no-p8"]
    )  # fmt: skip
    assert args.no_p8
    assert args.handler is candidates_cli.run_candidates
    table = pl.DataFrame({"district": list(DISTRICTS), "state": ["NY"] * 3 + ["CT"] * 3})
    codes = pl.DataFrame(
        {"district": ["d0"], "day": [date(2024, 1, 10)], "code": [2]},
        schema_overrides={"code": pl.Int8},
    )
    context = candidates_cli._context(world, table, codes)
    assert context.northeast.all()
    assert sorted(set(context.code.tolist())) == [-1, 2]
    today = candidates_cli.walk(TODAY, world)
    config = PredictConfig.load()
    found = candidates_cli.compare(
        "same", today, today, "today", world, context, config,
        extras={"a list": ["- one"], "a number": 3},
    )  # fmt: skip
    text = "\n".join(candidates_cli.comparison_markdown(found, None, None))
    assert "**a list**" in text
    assert "**a number**: 3" in text
    assert found.verdict.verdict == "no archive evidence"
    folder = Path(str(tmp_path))
    runs = pl.DataFrame(
        {
            "day": [date(2023, 2, 28), date(2023, 2, 28)],
            "zone": ["America/New_York"] * 2,
            "available_at": [
                datetime(2023, 2, 28, 1, 59, tzinfo=UTC), datetime(2023, 2, 28, 2, 1, tzinfo=UTC),
            ],
            "error": [None, None],
        },
        schema_overrides={"error": pl.String},
    )  # fmt: skip
    runs.write_parquet(folder / "runs.parquet")
    assert candidates_run.check_runs(folder) == (
        "2 files read, 1 available after 21:00 local the evening before"
    )
    p8 = candidates_run.P8(lambda _day: world, skip=False, whole=world)
    dropped = p8.run(Spec("C2a", c2=True), TODAY, [date(2024, 1, 10).toordinal()], context)
    assert dropped is not None
    assert len(dropped.by_date) == 1
    assert dropped.brier == dropped.by_date[0][1:]
    assert candidates_run.P8(lambda _day: world, skip=True).run(TODAY, TODAY, [1], context) is None


def test_the_level_rule_reports(world: World) -> None:
    candidates_cli.walk(Spec("C1", c1=True), world)
    assert "storm rows" in candidates_run.c1_against_b0(world)
    _p, _raw, moved = world.c1_base("test")
    assert "a state or region record served" in candidates_run._c1_counts(world, moved)


def _verdict_inputs(
    gain_base: float = 0.1, gain_new: float = 0.1
) -> tuple[backtest_terms.TermGates, backtest_terms.Checks, backtest_terms.Scored]:
    gates = backtest_terms.TermGates(
        10, gain_base, gain_new, (), 0, (), True, 0, math.nan, math.nan
    )
    y = np.array([1.0, 0.0, 1.0, 0.0])
    same = np.array([0.5, 0.5, 0.5, 0.5])
    scored = backtest_terms.Scored(
        y, same, same.copy(), np.array([1, 1, 2, 3]), ("a", "a", "b", "c"), np.ones(4, np.int64)
    )
    return gates, backtest_terms.run_checks(scored, draws=50), scored


def test_the_shifted_input_sentinel_under_both_readings() -> None:
    # C3's case: the candidate gains nothing, its shifted inputs gain 0.023%.
    gates, checks, scored = _verdict_inputs()
    sentinel = 0.000227
    pre = candidates_cli.judge_verdict("C3", gates, checks, scored, 0, sentinel)
    plan = candidates_cli.judge_verdict(
        "C3", gates, checks, scored, 0, sentinel, reading=candidates_cli.PLAN_T2
    )
    assert pre.verdict == "no archive evidence"
    assert plan.verdict == "harm (veto)"
    assert plan.harm == ("T2 sentinel (a), plan T2: shifted inputs gain +0.023%",)
    assert plan.reading == candidates_cli.PLAN_T2
    assert pre.label == "no archive evidence (provisional)"
    assert pre.not_run == candidates_cli.NOT_RUN
    assert any("P7" in item for item in pre.not_run)
    assert any("later-product" in item for item in pre.not_run)
    assert candidates_cli.sentinel_fails(0.0, candidates_cli.PLAN_T2) is False
    assert candidates_cli.sentinel_fails(-0.003, candidates_cli.PLAN_T2) is False
    assert candidates_cli.sentinel_fails(1e-12, candidates_cli.PLAN_T2) is False  # float noise
    assert candidates_cli.sentinel_fails(0.019, candidates_cli.PREREGISTERED) is False
    assert candidates_cli.sentinel_fails(0.02, candidates_cli.PREREGISTERED) is True
    assert candidates_cli.sentinel_fails(None, candidates_cli.PLAN_T2) is False
    with pytest.raises(ValueError, match="reading"):
        candidates_cli.sentinel_fails(0.1, "neither")
    done = candidates_cli.Verdict("x", "no archive evidence", (), (), not_run=())
    assert done.label == "no archive evidence"


def test_harm_against_today_s_model_vetoes_too() -> None:
    gates, checks, scored = _verdict_inputs()
    today = candidates_cli.AgainstToday(-0.03, -0.03, False, (0.01, 0.005, 0.02), ("worse",))
    found = candidates_cli.judge_verdict("x", gates, checks, scored, 0, None, today=today)
    assert found.verdict == "harm (veto)"
    assert found.harm == ("against today's model: worse",)


def test_a_comparison_reports_both_readings_and_today_s_model(world: World) -> None:
    context = _context(world)
    config = PredictConfig.load()
    today = candidates_cli.walk(TODAY, world)
    spec = Spec("C2a", c2=True)
    c2 = candidates_cli.walk(spec, world)
    c3_spec = Spec("C3", c2=True, c3=True)
    c3 = candidates_cli.walk(c3_spec, world)
    found = candidates_cli.compare(
        "C3", c3, c2, "C2a", world, context, config, sentinel=0.5, today=today
    )
    assert found.today is not None
    assert found.plan_verdict is not None
    assert found.verdict_of(candidates_cli.PLAN_T2) is found.plan_verdict
    assert found.verdict_of(candidates_cli.PREREGISTERED) is found.verdict
    assert any("T2 sentinel (a), plan T2" in h for h in found.plan_verdict.harm)
    text = "\n".join(candidates_cli.comparison_markdown(found, c3_spec, c3))
    assert "Against today's model: P1" in text
    assert "as plan T2 states it" in text
    assert "as pre-registered" in text
    assert "(provisional)" in text
    assert "pre-registered: fails; plan T2: fails" in text
    assert "Not run, so every verdict here is provisional" in text
    numbers = candidates_cli.comparison_json(found)
    assert numbers["verdict_plan_t2"] is not None
    assert numbers["sentinel_readings"] == {"pre-registered": True, "plan T2": True}
    assert numbers["against_today"] is not None
    same = candidates_cli.compare("C2a", c2, today, "today", world, context, config)
    assert same.today is None
    assert "the baseline is today's model" in "\n".join(
        candidates_cli.comparison_markdown(same, spec, c2)
    )
    assert "not applicable" in candidates_cli._sentinel_line(same)
    # C3's real case: its shifted inputs help a little; the readings disagree.
    small = candidates_cli.compare(
        "C3", c3, c2, "C2a", world, context, config, sentinel=0.000227, today=today
    )
    pre = candidates_run.Stack(
        candidates_cli.PREREGISTERED, [same, small], [["## C2a", "a"], ["## C3", "b"]],
        ["c2", "c3"], accepted=["C2a"],
    )  # fmt: skip
    plan = candidates_run.Stack(
        candidates_cli.PLAN_T2, [same, small], [["## C2a", "a"], ["## C3", "c"]],
        ["c2", "c3 on another stack"], accepted=["C2a"],
    )  # fmt: skip
    assert pre.sections == ["## C2a", "a", "## C3", "b"]
    assert pre.final == "today's model + C2a"
    notes = "\n".join(candidates_run.departures([pre, plan]))
    assert "T2 sentinel (a)" in notes
    assert "  - C3 (against C2a): shifted inputs gain +0.023%" in notes
    assert notes.count("  - C3 (against C2a)") == 2  # the two comparisons, each once
    assert "minimum over 5-8 AM" in notes
    assert "P7 parity" in notes
    table = candidates_run._verdict_table(pre)
    assert any("(provisional)" in line for line in table)
    assert "Final stack: today's model + C2a." in table
    assert not any(
        "Final stack" in line for line in candidates_run._verdict_table(pre, final=False)
    )
    assert candidates_run.second_sections(plan, set(pre.keys)) == ["## C3", "c"]
    assert "  - nowhere." in candidates_run.departures(
        [candidates_run.Stack("a", [same], [[]], ["k"]), candidates_run.Stack("b")]
    )


def test_the_new_base_s_p8_dates_and_reports(world: World) -> None:
    context = _context(world)
    config = PredictConfig.load()
    candidates_cli.walk(Spec("C1", c1=True), world)
    dates = candidates_cli.base_dates(world)
    assert dates
    every = {int(d) for r in world.training.values() for d in r.day.tolist()}
    assert set(dates) <= every
    assert "2016-02-16" in candidates_run._p8_note(world)
    gates = candidates_run.c1_base_gates(world, context, config)
    assert gates[0].startswith("| test season |")
    assert any(line.startswith("new base: pooled G1") for line in gates)
    assert any(line.startswith("today's base: pooled G1") for line in gates)
    # Every season of the larger fold as the "all seasons" rows: NY has its 30 days there.
    every_season = dataclasses.replace(world, test=world.training[2024])
    levels = candidates_run.c1_served_levels(every_season, config.model)
    assert any(line.startswith("| state | NY |") for line in levels)
    assert any("0 of them in a region with fewer than" in line for line in levels)
    assert any(line.startswith("C2b's cells") for line in levels)


def test_the_owner_table_lists_every_changed_cell(world: World) -> None:
    context = _context(world)
    today = candidates_cli.walk(TODAY, world)
    n = len(world.test.rows)
    p = candidates_cli.chance_of(today, n)
    lines = candidates_cli.owner_table(["today", "same", "up"], [p, p, np.clip(p + 0.1, 0, 1)],
                                       world, context)  # fmt: skip
    at = lines.index("### Every cell whose mean chance differs from today's (at two places)")
    changed = lines[at + 2 :]
    assert any("up 0.60 to 0.70" in line for line in changed)
    assert not any("same" in line for line in changed)
    quiet = candidates_cli.owner_table(["today", "same"], [p, p], world, context)
    assert "- none" in quiet


def test_c2c_coverage_counts_rows_with_a_report(world: World) -> None:
    c2 = candidates_cli.walk(Spec("C2a", c2=True), world)
    text = candidates_run.morning_coverage(world, c2)
    assert text.startswith("scored test rows ")
    assert "2023-24 fold training" in text
    assert "40 km" in text
