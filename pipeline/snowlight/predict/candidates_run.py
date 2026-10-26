"""The run behind ``snowlight predict candidates`` (the real labels; internal). See
:mod:`snowlight.predict.candidates_cli` and ``docs/research/candidates-preregistration.md``."""

import argparse
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.output import write_json
from snowlight.predict import backtest_terms, candidates, pool, term_rows, train
from snowlight.predict.backtest import baselines, brier, gates, reliability
from snowlight.predict.candidates_cli import (
    NOT_RUN,
    PLAN_T2,
    PREREGISTERED,
    READINGS,
    SUPPORT,
    TODAY,
    Comparison,
    Context,
    Inputs,
    InputTable,
    Sources,
    Spec,
    Walk,
    World,
    _context,
    against,
    base_dates,
    build_world,
    chance_of,
    compare,
    comparison_json,
    comparison_markdown,
    delay_scores,
    design,
    fold_without,
    morning_inputs,
    moved_dates,
    owner_table,
    per_date,
    read_fold_0500,
    shapes_of,
    shifted_gain,
    walk,
    with_inputs,
)
from snowlight.predict.config import ModelSettings, PredictConfig
from snowlight.predict.geography import REGION_OF
from snowlight.predict.pool import Floats, Ints
from snowlight.predict.situations import SITUATIONS, WeatherClass
from snowlight.predict.terms import Design, Term, fit, predict

C2_DAYS = (date(2023, 2, 28), date(2023, 3, 14), date(2024, 1, 16))


def _log(text: str) -> None:
    print(f"{datetime.now(UTC):%H:%M:%S} {text}", flush=True)  # noqa: T201


def check_runs(extract: Path) -> str:
    """T2 (b): every forecast file the extract read was available by 21:00 local."""
    runs = pl.read_parquet(extract / "runs.parquet").filter(pl.col("error").is_null())
    late = 0
    for night, zone, available in runs.select("day", "zone", "available_at").iter_rows():
        if available is None:
            continue
        snapshot = datetime.combine(night, time(21), tzinfo=ZoneInfo(zone)).replace()
        snapshot = datetime.combine(
            date.fromordinal(night.toordinal() - 1), time(21), tzinfo=ZoneInfo(zone)
        )
        late += int(available > snapshot)
    return f"{runs.height} files read, {late} available after 21:00 local the evening before"


class P8:
    """P8's refits: one world per training date left out, kept for every candidate."""

    def __init__(
        self, make: Callable[[int], World], skip: bool, whole: World | None = None
    ) -> None:
        self.make = make
        self.skip = skip
        self.whole = whole
        """The world with every training date (the briers P8's changes are taken from)."""
        self.worlds: dict[int, World] = {}

    @staticmethod
    def _briers(
        candidate: Spec, baseline: Spec, world: World, context: Context
    ) -> tuple[float, float]:
        mine = walk(candidate, world)
        theirs = walk(baseline, world)
        scored = backtest_terms.scored_from_folds(
            against(mine, theirs), world.test.rows, context.day, context.market,
            context.code, context.northeast,
        )  # fmt: skip
        return backtest_terms.storm_briers(scored)

    def world(self, day: int) -> World:
        if day not in self.worlds:
            _log(f"P8 world without {date.fromordinal(day)}")
            self.worlds[day] = self.make(day)
        return self.worlds[day]

    def run(
        self, candidate: Spec, baseline: Spec, dates: Sequence[int], context: Context
    ) -> backtest_terms.DropTraining | None:
        if self.skip:
            return None
        found: list[tuple[int, float, float]] = []
        for day in dates:
            b, c = self._briers(candidate, baseline, self.world(day), context)
            found.append((day, b, c))
        whole = (
            (math.nan, math.nan)
            if self.whole is None
            else self._briers(candidate, baseline, self.whole, context)
        )
        return backtest_terms.DropTraining(whole, tuple(found))


def date_forward(spec: Spec, world: World) -> tuple[int, float, float]:
    """C2's date-forward diagnostic (never gates): each storm test date's rows predicted by
    the fit on its fold's rows and the same season's earlier test dates."""
    test = world.test
    storm = backtest_terms.WEATHER_OF[test.rows.situation] > 0
    base: list[float] = []
    new: list[float] = []
    ys: list[float] = []
    for season in world.seasons:
        source = world.training[season]
        train_mask = source.has_base & (source.rows.season < season)
        mine = test.has_base & (test.rows.season == season)
        for day in sorted(set(test.day[mine & storm].tolist())):
            earlier = mine & (test.day < day)
            first = design(spec, world, str(season), train_mask, season)
            second = design(spec, world, "test", earlier, season)
            joined = _concat(first, second)
            seasons = np.concatenate(
                [source.rows.season[train_mask], np.full(int(earlier.sum()), season)]
            )
            model = fit(joined, seasons, support=SUPPORT)
            today = mine & (test.day == day) & storm
            p = publish_of(predict(model, design(spec, world, "test", today, season)), world)
            base += test.base.p[today].tolist()
            new += p.tolist()
            ys += test.rows.y[today].tolist()
    y = np.array(ys)
    return len(ys), brier(np.array(base), y), brier(np.array(new), y)


def publish_of(p: Floats, world: World) -> Floats:
    """``p`` as published."""
    return backtest_terms.publish(p, world.settings)


def _concat(a: Design, b: Design) -> Design:
    def both[T: np.generic](
        x: npt.NDArray[T] | None, y: npt.NDArray[T] | None
    ) -> npt.NDArray[T] | None:
        if x is None or y is None:
            return None
        return np.concatenate([x, y])

    return Design(
        offset=np.concatenate([a.offset, b.offset]),
        y=np.concatenate([a.y, b.y]),
        weather=np.concatenate([a.weather, b.weather]),
        levels={t: np.concatenate([a.levels[t], b.levels[t]]) for t in a.levels},
        own=both(a.own, b.own),
        day=both(a.day, b.day),
        extra=both(a.extra, b.extra),
        extra_bounds=a.extra_bounds,
        up_only=both(a.up_only, b.up_only),
    )


def c1_against_b0(world: World) -> str:
    """C1 with C2b's base alone (no terms) against B0 on the storm rows both score (piece
    1's G1, reported)."""
    test = world.test
    published, _raw, moved = world.c1_base("test")
    found_b0 = np.full(len(test.rows), np.nan)
    for season in world.seasons:
        mine = test.rows.season == season
        source = world.training[season]
        b0, _b1 = baselines(source.rows, test.rows.subset(mine), world.places)
        found_b0[mine] = b0
    storm = (backtest_terms.WEATHER_OF[test.rows.situation] > 0) & test.has_base
    keep = storm & ~np.isnan(found_b0) & np.isin(test.rows.season, np.array(world.seasons))
    y = test.rows.y[keep]
    return (
        f"{int(keep.sum())} storm rows: new base {brier(published[keep], y):.5f}, today's base "
        f"{brier(test.base.p[keep], y):.5f}, B0 {brier(found_b0[keep], y):.5f}; the new base "
        f"moves {int((moved & keep).sum())} of them"
    )


@dataclass
class Stack:
    """One run of the cumulative stack under one reading of T2 sentinel (a)."""

    reading: str
    results: list[Comparison] = field(default_factory=list)
    parts: list[list[str]] = field(default_factory=list)
    """Each result's section of the report."""
    keys: list[object] = field(default_factory=list)
    """Each result's (candidate, baseline) models: equal keys are the same comparison."""
    chances: dict[str, Floats] = field(default_factory=dict)
    accepted: list[str] = field(default_factory=list)
    """The candidates that entered the stack, in order."""

    @property
    def final(self) -> str:
        """The final stack: today's model plus every candidate that entered."""
        return " + ".join(["today's model", *self.accepted])

    @property
    def sections(self) -> list[str]:
        """Every result's section, in order."""
        return [line for part in self.parts for line in part]


def run(args: argparse.Namespace) -> int:  # noqa: PLR0915 # pragma: no cover - the real labels
    """Every stage, in order, under both readings of T2 (a), and the report."""
    config = PredictConfig.load(args.config)
    settings = config.model
    work: Path = args.work
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    labels = pl.read_parquet(work / "labels.parquet")
    table = pl.read_parquet(work / "districts.parquet")
    schools = pl.read_parquet(args.directory / "schools.parquet")
    places = train.training_places(table, schools, config.serve.neighbor_miles)
    usable = pool.usable_labels(labels, places)
    rows = pool.rows_from_labels(usable, places, "no_school")
    fold_seasons = sorted(set(rows.season.tolist()))[1:]
    folder = args.folds or work / train.FOLDS
    fold = train.read_fold_set(folder, fold_seasons, places)
    _log("codes")
    every_code = term_rows.forecast_codes(args.codes)
    label_days = set(labels["day"].to_list())
    for frame in fold.usable.values():
        label_days |= set(frame["day"].to_list())
    labels_0500 = pl.read_parquet(args.labels_0500 / "labels.parquet")
    label_days |= set(labels_0500["day"].to_list())
    # The codes of the label dates only: every lookup below reads these.
    codes = every_code.filter(pl.col("day").is_in(sorted(label_days)))
    sources = Sources(
        codes,
        pl.read_parquet(work / "snapshots.parquet"),
        pl.read_parquet(work / "posts.parquet"),
        term_rows.training_neighbors(table, schools, config.serve.neighbor_miles),
    )
    values = pl.read_parquet(args.extract / "values.parquet")
    alerts = pl.read_parquet(args.alerts)
    inputs_table = InputTable.build(values, alerts, table)
    counts = candidates.season_counts(every_code)
    del every_code
    state_of = dict(zip(table["district"], table["state"], strict=True))
    seasons = tuple(config.backtest.test_seasons)
    climates = {
        s: candidates.climate_of(counts, list(range(2018, s)), state_of, REGION_OF) for s in seasons
    }
    _log("world")

    def make(f: train.FoldSet) -> World:
        return build_world(
            usable, f, places, settings, seasons, inputs_table.inputs, sources, climates
        )

    world = make(fold)
    context = _context(world, table, codes)
    p8 = P8(lambda day: make(fold_without(fold, day)), args.no_p8, world)
    shifted = with_inputs(world, lambda f: inputs_table.inputs(f, shift=True))
    runs_note = check_runs(args.extract)
    n = len(world.test.rows)
    _log("today")
    today = walk(TODAY, world, with_delay=True)
    control_spec = Spec("P2 control (piece 3's terms with P2)", piece3=True)
    control = walk(control_spec, world)
    first = date(2016, 2, 16).toordinal()

    def p8_dates(candidate: Walk, baseline: Walk, spec: Spec) -> list[int]:
        found = [first]
        for day in moved_dates(candidate, baseline, world) + (base_dates(world) if spec.c1 else []):
            if day not in found:
                found.append(day)
        return found

    def stack_run(reading: str) -> Stack:  # noqa: PLR0915 - every stage in order
        """The cumulative stack: a candidate enters when ``reading``'s verdict is not harm."""
        mine = Stack(reading)

        def record(found: Comparison, spec: Spec | None, w: Walk | None, base: Spec) -> None:
            mine.results.append(found)
            mine.parts.append([*comparison_markdown(found, spec, w), ""])
            mine.keys.append((found.name, spec, base))
            v = found.verdict_of(reading)
            _log(f"[{reading}] {found.name}: {v.verdict} ({100 * found.gates.gain:+.2f}%)")

        def vetoed(found: Comparison) -> bool:
            return bool(found.verdict_of(reading).harm)

        mine.chances["today's model"] = chance_of(today, n)
        mine.chances["P2 control"] = chance_of(control, n)
        record(
            compare(
                control_spec.name, control, today, TODAY.name, world, context, config,
                drop_training=p8.run(
                    control_spec, TODAY, p8_dates(control, today, control_spec), context
                ),
            ),
            control_spec, control, TODAY,
        )  # fmt: skip
        stack, stack_walk = TODAY, today

        # C2a.
        c2_spec = replace(stack, name="C2a (rain/snow line at 7 AM, a term)", c2=True)
        c2 = walk(c2_spec, world)
        mine.chances["C2a"] = chance_of(c2, n)
        sentinel = shifted_gain(walk(c2_spec, shifted), walk(stack, shifted), shifted, context)
        forward = date_forward(c2_spec, world)
        named = per_date(against(c2, stack_walk), world.test.rows, world.test.day, C2_DAYS)
        c2_found = compare(
            c2_spec.name, c2, stack_walk, stack.name, world, context, config,
            drop_training=p8.run(c2_spec, stack, p8_dates(c2, stack_walk, c2_spec), context),
            sentinel=sentinel, today=None if stack.today else today,
            extras={
                "the three days (date, storm rows, closed, baseline, candidate)": [
                    f"- {d}: {k} rows, {c:.2f} closed, {b:.4f} to {t:.4f}"
                    for d, k, c, b, t in named
                ],
                DATE_FORWARD: (
                    f"{forward[0]} storm rows: baseline {forward[1]:.5f}, date-forward fit "
                    f"{forward[2]:.5f}. {DATE_FORWARD_LABELS}"
                ),
                "inputs on the scored storm rows": _input_counts(world, c2),
                "penalty path, last fold (diagnostic, never gates)": penalty_path(c2_spec, world),
            },
        )  # fmt: skip
        record(c2_found, c2_spec, c2, stack)
        if not vetoed(c2_found):
            stack, stack_walk = c2_spec, c2
            mine.accepted.append("C2a")

        # C3.
        c3_spec = replace(stack, name="C3 (timing, with the delay term)", c3=True)
        c3 = walk(c3_spec, world, with_delay=True)
        mine.chances["C3"] = chance_of(c3, n)
        sentinel = shifted_gain(walk(c3_spec, shifted), walk(stack, shifted), shifted, context)
        stack_delay = walk(stack, world, with_delay=True)
        advisory = backtest_terms.WEATHER_OF[world.test.rows.situation] == int(
            WeatherClass.ADVISORY
        )
        p_stack = chance_of(stack_delay, n)
        p_c3 = chance_of(c3, n)
        scored_rows = ~np.isnan(p_stack) & advisory
        base_delay = delay_scores(p_stack, stack_delay.delay, world, scored_rows, settings)  # type: ignore[arg-type]
        new_delay = delay_scores(p_c3, c3.delay, world, scored_rows, settings)  # type: ignore[arg-type]
        c3_scored = backtest_terms.scored_from_folds(
            against(c3, stack_walk), world.test.rows, context.day, context.market, context.code,
            context.northeast,
        )  # fmt: skip
        b, t = backtest_terms.storm_briers(c3_scored)
        afternoon = [m.extra[-1] for m in c3.models.values() if m.extra]
        c3_found = compare(
            c3_spec.name, c3, stack_walk, stack.name, world, context, config,
            drop_training=p8.run(c3_spec, stack, p8_dates(c3, stack_walk, c3_spec), context),
            sentinel=sentinel, today=None if stack.today else today,
            extra_harm=[f"no-school storm Brier worse ({b:.5f} to {t:.5f})"] if t > b else [],
            extras={
                "delay on advisory test rows (rows, delay Brier, three-way log score)": (
                    f"baseline {base_delay[0]} rows, {base_delay[1]:.5f}, {base_delay[2]:.4f}; "
                    f"C3 {new_delay[0]} rows, {new_delay[1]:.5f}, {new_delay[2]:.4f}"
                ),
                "fitted 'mostly afternoon' weight by fold (sign free)": ", ".join(
                    f"{v:+.3f}" for v in afternoon
                ),
                "inputs on the scored storm rows": _input_counts(world, c3),
                "Kansas 2025-01-06 replay": "not a label night of the extract; not checkable here",
                "penalty path, last fold (diagnostic, never gates)": penalty_path(c3_spec, world),
            },
        )  # fmt: skip
        record(c3_found, c3_spec, c3, stack)
        if not vetoed(c3_found):
            stack, stack_walk = c3_spec, c3
            mine.accepted.append("C3")

        # The C4 stage: the control's terms on the stack, with C4's levels.
        control_stack = replace(
            stack,
            name="the stack with the P2 control's terms" + (" and C3's gate" if stack.c3 else ""),
            piece3=True, gate=stack.c3,
        )  # fmt: skip
        ctrl = walk(control_stack, world)
        c4_spec = replace(
            control_stack, name="C4 (amounts against the place's own nights)", c4=True
        )
        c4 = walk(c4_spec, world)
        mine.chances["control stack"] = chance_of(ctrl, n)
        mine.chances["C4"] = chance_of(c4, n)
        record(
            compare(
                control_stack.name + " (against the stack before it)", ctrl, stack_walk,
                stack.name, world, context, config, today=None if stack.today else today,
            ),
            control_stack, ctrl, stack,
        )  # fmt: skip
        c4_found = compare(
            c4_spec.name, c4, ctrl, control_stack.name, world, context, config,
            drop_training=p8.run(c4_spec, control_stack, p8_dates(c4, ctrl, c4_spec), context),
            today=today,
            extras={
                "advisory table by snow bucket": _advisory_buckets(world, context, ctrl, c4),
                "penalty path, last fold (diagnostic, never gates)": penalty_path(c4_spec, world),
                "control's penalty path, last fold": penalty_path(control_stack, world),
            },
        )  # fmt: skip
        record(c4_found, c4_spec, c4, control_stack)
        c4_entry = compare(
            "C4 stage (the whole stack against the stack before it)", c4, stack_walk, stack.name,
            world, context, config, today=None if stack.today else today,
        )  # fmt: skip
        record(c4_entry, None, None, stack)
        if not vetoed(c4_found) and not vetoed(c4_entry):
            stack, stack_walk = c4_spec, c4
            mine.accepted.append("the C4 stage (the control's terms with C4's levels)")

        # C1 with C2b.
        c1_spec = replace(
            stack, name="C1 with C2b (the level rule and the cold/warm split)", c1=True
        )
        c1 = walk(c1_spec, world)
        mine.chances["C1 with C2b"] = chance_of(c1, n)
        _published, _raw, moved = world.c1_base("test")
        c1_found = compare(
            c1_spec.name, c1, stack_walk, stack.name, world, context, config,
            drop_training=p8.run(c1_spec, stack, p8_dates(c1, stack_walk, c1_spec), context),
            sentinel=shifted_gain(walk(c1_spec, shifted), walk(stack, shifted), shifted, context),
            today=None if stack.today else today,
            extras={
                "the new base alone against B0 (piece 1's G1, reported)": c1_against_b0(world),
                "piece 1's G1 by season and G2, the new base and today's base against B0": (
                    c1_base_gates(world, context, config)
                ),
                "test rows whose base the rule moves": _c1_counts(world, moved),
                "what the owner sees first: C1a's and C2b's cells on every labeled season": (
                    c1_served_levels(world, settings)
                ),
                "test_truth.py for every cell": "deferred to F3: it checks a served model "
                "file's base sentences, and C1 with C2b builds none (its sentence, for example "
                "\"recorded cold advisory days\", waits for the owner).",
                "P8's dates": _p8_note(world),
                "penalty path, last fold (diagnostic, never gates)": penalty_path(c1_spec, world),
            },
        )  # fmt: skip
        record(c1_found, c1_spec, c1, stack)
        if not vetoed(c1_found):
            stack, stack_walk = c1_spec, c1
            mine.accepted.append("C1 with C2b")
        mine.chances["final stack"] = chance_of(stack_walk, n)
        return mine

    stacks = [stack_run(reading) for reading in READINGS]

    # C2c on the 05:00 labels.
    _log("05:00 world")
    usable_0500 = pool.usable_labels(labels_0500, places)
    fold_0500 = read_fold_0500(args.folds_0500, fold_seasons, places)
    morning = pl.read_parquet(args.morning)

    def morning_of(frame: pl.DataFrame) -> Inputs:
        return morning_inputs(frame, morning)

    world_0500 = build_world(
        usable_0500, fold_0500, places, settings, seasons, morning_of, sources, climates
    )
    context_0500 = _context(world_0500, table, codes)
    today_0500 = walk(TODAY, world_0500)
    c2c_spec = Spec("C2c (5 AM airport report, on the 05:00 labels)", c2=True)
    c2c = walk(c2c_spec, world_0500)
    shifted_0500 = with_inputs(
        world_0500, lambda f: morning_inputs(_shift_frame(f, inputs_table), morning)
    )
    c2c_found = compare(
        c2c_spec.name, c2c, today_0500, "today's model on the 05:00 labels", world_0500,
        context_0500, config,
        sentinel=shifted_gain(walk(c2c_spec, shifted_0500), walk(TODAY, shifted_0500), shifted_0500, context_0500),  # noqa: E501
        extras={
            "the three days": [
                f"- {d}: {k} rows, {c:.2f} closed, {b:.4f} to {t:.4f}"
                for d, k, c, b, t in per_date(against(c2c, today_0500), world_0500.test.rows, world_0500.test.day, C2_DAYS)  # noqa: E501
            ],
            "5 AM report coverage (rows with a report at or before 05:00 of the snow-class rows)": (
                morning_coverage(world_0500, c2c)
            ),
            "P8": "not run for C2c (its fold labels are lane F2's 05:00 files)",
            "penalty path, last fold (diagnostic, never gates)": penalty_path(c2c_spec, world_0500),
        },
    )  # fmt: skip
    c2c_sections = [*comparison_markdown(c2c_found, c2c_spec, c2c), ""]
    _log(f"{c2c_found.name}: {c2c_found.verdict.verdict} ({100 * c2c_found.gates.gain:+.2f}%)")

    # The owner table: both stacks' models, each named once.
    first_stack, second = stacks
    chances = dict(first_stack.chances)
    for name, value in second.chances.items():
        if name not in chances or not np.array_equal(chances[name], value, equal_nan=True):
            chances[f"{name} [{second.reading}]"] = value
    names = list(chances)
    owner = [
        f"Every model of the stack under {second.reading} gives the same chance on every row as "
        f"its namesake under {first_stack.reading}, unless it has a column of its own "
        f"(marked [{second.reading}]).",
        "",
        *owner_table(names, [chances[k] for k in names], world, context),
    ]
    lines = [
        "# Tuning candidates: the pre-registered archive test (internal)",
        "",
        "Pre-registration: docs/research/candidates-preregistration.md (unchanged). Per-fold "
        "labels. The archive can veto a candidate; it cannot show one helps.",
        "",
        *departures(stacks),
        "## Verdicts",
        "",
        "Every verdict is provisional: " + "; ".join(NOT_RUN) + ".",
        "",
    ]
    for found in stacks:
        lines += _verdict_table(found)
    lines += _verdict_table(
        Stack(PREREGISTERED, [c2c_found]), title="beside the stack", final=False
    )
    lines += [
        f"T2 (b): {runs_note}.",
        "",
        "## Owner table",
        "",
        *owner,
        f"# The stack, T2 sentinel (a) {PREREGISTERED}",
        "",
        *first_stack.sections,
        f"# The stack, T2 sentinel (a) {PLAN_T2}: the stages whose baseline differs",
        "",
    ]
    extra = second_sections(second, set(first_stack.keys))
    lines += extra or ["None: every stage has the same baseline under both readings.", ""]
    lines += ["# Beside the stack", "", *c2c_sections]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    from snowlight.predict.cli import json_safe  # noqa: PLC0415

    metrics: dict[str, object] = {
        "runs": runs_note,
        "not_run": list(NOT_RUN),
        "readings": {
            found.reading: {
                "comparisons": [comparison_json(r) for r in found.results],
                "final_stack": found.final,
            }
            for found in stacks
        },
        "beside": [comparison_json(c2c_found)],
        "departures": departures(stacks),
    }
    write_json(out / "metrics.json", json_safe(json.loads(json.dumps(metrics, default=str))))
    _log("done")
    return 0


DATE_FORWARD: Final = (
    "date-forward diagnostic (never gates; whole-archive labels for same-season dates)"
)
DATE_FORWARD_LABELS: Final = (
    "Its fit reads each fold's labels plus the same season's earlier test dates, and those "
    "same-season rows carry the whole-archive labels (labels.parquet, station audiences "
    "built from every season), not per-fold labels. No per-fold file is clean for them: the "
    "next season's fold file builds its audiences from the whole test season, its later dates "
    "included. So this diagnostic does not meet the per-fold rule and never gates."
)


def departures(stacks: Sequence[Stack]) -> list[str]:
    """Where this run departs from the plan, written after the scores (the pre-registration
    itself is unchanged), and what differs between the two readings of T2 (a)."""
    first, second = stacks
    differ = []
    seen: set[object] = set()
    pairs = [
        *zip(first.keys, first.results, strict=True),
        *zip(second.keys, second.results, strict=True),
    ]
    for key, found in pairs:
        if key in seen:
            continue
        seen.add(key)
        va, vb = found.verdict_of(PREREGISTERED), found.verdict_of(PLAN_T2)
        if va.verdict != vb.verdict:
            gain = 100 * (found.sentinel or 0.0)
            differ.append(
                f"  - {found.name} (against {found.baseline}): shifted inputs gain {gain:+.3f}% "
                f"against its own {100 * found.gates.gain:+.3f}%; {PREREGISTERED}: "
                f"{va.verdict}; {PLAN_T2}: {vb.verdict} ({'; '.join(vb.harm)})."
            )
    return [
        "## Departures from the plan and checks not run (written after the scores)",
        "",
        "- **T2 sentinel (a).** The pre-registration set its bar at a 2% pooled gain (P1's bar); "
        'plan T2 says "an input shifted by one day must not help", and plan T3 lists a failed '
        "T2 sentinel as a veto. The pre-registered bar is weaker than the plan's rule and the "
        "pre-registration did not record it as a departure. Both readings are computed below, "
        "each with its own cumulative stack, and the lead rules which stands; until then every "
        "verdict the readings disagree on is provisional. Where they disagree:",
        *(differ or ["  - nowhere."]),
        f"  Final stack as pre-registered: {first.final}. Final stack under plan T2: "
        f"{second.final}.",
        "- **C2's 7 AM temperature.** Plan sec. 2.2 names the 7 AM temperature \"plus the "
        'minimum over 5-8 AM". The pre-registration fixed `temp_h07` alone and did not record '
        "this as a departure. The minimum (`temp_h05` to `temp_h08` are in the extract) is not "
        "used: adding it after the scores would be a choice made after seeing them. It stays "
        "for a later pre-registered test or the live shadow.",
        "- **P7 parity** is not run: it waits for F3, which builds the live inputs.",
        "- **T2's later-product sentinel** (drop every alert product issued after 21:00 and "
        "recompute these candidates' alert inputs) is not run on the real data: the product "
        "cache went with the calc-data worktree. What exists is the unit test "
        "`test_dropping_products_after_the_snapshot_changes_nothing_at_it` and calc-data's "
        "real-data check of the labels' classes and start moves across 09:00.",
        "- **C2's date-forward diagnostic** reads whole-archive labels for its same-season "
        "dates (not per-fold); it never gates.",
        "- **C2c's 5 AM reports** were first fetched for the 21:00 labels' district-days only; "
        "this run reads a refetch for every district-day of the 05:00 labels and their fold "
        "files (coverage in C2c's section).",
        "- **P8 for C1 with C2b** refits without 2016-02-16 and the busiest 3 training dates of "
        "every level record its scored rows rest on (a new base moves no training row a term "
        "fit moves, so the term rule finds no dates).",
        "- **C1's `test_truth.py` check** is deferred to F3: it checks a served model file's "
        "base sentences, and C1 with C2b builds none; F3's shadow builds the cells it would log.",
        "",
    ]


def second_sections(second: Stack, seen: set[object]) -> list[str]:
    """The second stack's sections of the comparisons (candidate and baseline models) the
    first stack does not have."""
    return [
        line for key, part in zip(second.keys, second.parts, strict=True) if key not in seen
        for line in part
    ]  # fmt: skip


def _verdict_table(found: Stack, title: str = "", *, final: bool = True) -> list[str]:
    heading = title or f"the stack, T2 sentinel (a) {found.reading}"
    lines = [
        f"### Verdicts, {heading}",
        "",
        "| candidate | baseline | storm Brier gain | against today's model | verdict, "
        f"{PREREGISTERED} | verdict, {PLAN_T2} |",
        "|---|---|---|---|---|---|",
    ]
    for r in found.results:
        versus = "same" if r.today is None else f"{100 * r.today.gain:+.2f}%"
        lines.append(
            f"| {r.name} | {r.baseline} | {100 * r.gates.gain:+.2f}% | {versus} | "
            f"{r.verdict_of(PREREGISTERED).label} | {r.verdict_of(PLAN_T2).label} |"
        )
    lines.append("")
    if final:
        lines += [f"Final stack: {found.final}.", ""]
    return lines


def morning_coverage(world: World, found: Walk) -> str:
    """C2c's input coverage: snow-class rows with a 5 AM report, on the scored test rows and
    in each fold's training rows."""
    test = world.test
    at = np.concatenate([f.rows for f in found.folds]) if found.folds else np.zeros(0, np.int64)
    snowy = np.isin(test.own[at], np.array(candidates.SNOW_CLASSES))
    known = test.inputs.temperature[at] >= 0
    parts = [f"scored test rows {int((snowy & known).sum())} of {int(snowy.sum())}"]
    for season in world.seasons:
        source = world.training.get(season)
        if source is None:
            continue
        keep = source.has_base & (source.rows.season < season)
        snow = keep & np.isin(source.own, np.array(candidates.SNOW_CLASSES))
        have = snow & (source.inputs.temperature >= 0)
        label = f"{season}-{(season + 1) % 100:02d}"
        parts.append(f"{label} fold training {int(have.sum())} of {int(snow.sum())}")
    return (
        "; ".join(parts)
        + ". A row without a report has no airport within 40 km or no routine report in the "
        "90 minutes before 05:00; it enters as unknown temperature (0)."
    )


def c1_base_gates(world: World, context: Context, config: PredictConfig) -> list[str]:
    """Piece 1's G1 by season and G2 for C1 with C2b's base alone (no terms) and for today's
    base, each against B0 on the storm test rows both score (reported, never a verdict)."""
    test = world.test
    published, _raw, _moved = world.c1_base("test")
    found_b0 = np.full(len(test.rows), np.nan)
    for season in world.seasons:
        mine = test.rows.season == season
        source = world.training[season]
        b0, _b1 = baselines(source.rows, test.rows.subset(mine), world.places)
        found_b0[mine] = b0
    storm = (backtest_terms.WEATHER_OF[test.rows.situation] > 0) & test.has_base
    keep = storm & ~np.isnan(found_b0) & np.isin(test.rows.season, np.array(world.seasons))
    clusters = [c for c, k in zip(context.clusters, keep.tolist(), strict=True) if k]
    settings = config.backtest
    judged = {}
    for name, p in (("new base", published), ("today's base", test.base.p)):
        frame = pl.DataFrame(
            {
                "season": test.rows.season[keep],
                "weather": backtest_terms.WEATHER_OF[test.rows.situation[keep]],
                "y": test.rows.y[keep],
                "p": p[keep],
                "b0": found_b0[keep],
                "b1": found_b0[keep],
            }
        )
        bins = reliability(p[keep], test.rows.y[keep], clusters, settings.reliability_bins)
        judged[name] = gates(
            frame, bins, settings.apart, settings.reliability_min_rows,
            g1_min_storm_rows=settings.g1_min_storm_rows, g1_tolerance=settings.g1_tolerance,
        )  # fmt: skip
    new, old = judged["new base"], judged["today's base"]
    lines = [
        "| test season | storm rows | new base | today's base | B0 | new base - B0 | G1 |",
        "|---|---|---|---|---|---|---|",
    ]
    for a, b in zip(new.g1_by_season, old.g1_by_season, strict=True):
        status = ("within" if a.ok else "over") + " tolerance" if a.gated else "reported"
        lines.append(
            f"| {a.season}-{(a.season + 1) % 100:02d} | {a.storm_rows} | {a.brier:.5f} | "
            f"{b.brier:.5f} | {a.brier_b0:.5f} | {a.excess:+.5f} | {status} |"
        )
    for name, item in judged.items():
        lines.append("")
        lines.append(
            f"{name}: pooled G1 {'passes' if item.g1_pooled else 'fails'}, without 2020-21 "
            f"{'passes' if item.g1_pooled_without_apart else 'fails'}, every gated season "
            f"{'within' if item.g1_seasons == item.g1_counted else 'not within'} tolerance; G2 "
            + ("passes" if item.g2 else "fails " + ", ".join(item.g2_failing))
            + " (storm rows, bins of 300 or more rows)."
        )
    return lines


def c1_served_levels(world: World, settings: ModelSettings) -> list[str]:
    """What the owner sees first (plan sec. 2.5): the state and region records C1a would
    serve, and the cold and warm cells C2b would split, on a fit over every labeled season
    (the whole archive's labels), with the thin rule's check."""
    test = world.test
    rows = test.rows
    places = world.places
    weather = backtest_terms.WEATHER_OF[rows.situation]
    alert = weather > 0
    names = {
        0: places.states,
        1: places.regions,
    }
    units = {0: test.units.state, 1: test.units.region, 2: np.zeros(len(rows), np.int64)}
    nation_rate = {
        s: float(rows.y[rows.situation == s].mean())
        for s in sorted(set(rows.situation[alert].tolist()))
    }
    region_days: dict[tuple[int, int], int] = {}
    for region, s in zip(units[1][alert].tolist(), rows.situation[alert].tolist(), strict=True):
        region_days[(region, s)] = region_days.get((region, s), 0) + 1
    lines = [
        "C1a's cells (a state, else a region, serves its own record with 30 labeled days on 3 "
        "or more dates, no date over half):",
        "",
        "| level | place | situation | labeled days | dates | busiest date | record | the "
        "nation's record | today's mean chance on its storm test rows |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    served = 0
    thin = 0
    p_today = test.base.p
    for tier in (0, 1):
        for unit in sorted(set(units[tier][alert].tolist())):
            if unit < 0:
                continue
            for s in sorted(set(rows.situation[alert & (units[tier] == unit)].tolist())):
                mine = alert & (units[tier] == unit) & (rows.situation == s)
                days, counts = np.unique(test.day[mine], return_counts=True)
                n = int(mine.sum())
                if not pool.level_supported(n, days.size, int(counts.max())):
                    continue
                served += 1
                region = int(units[1][mine][0]) if tier == 0 else unit
                thin += int(region_days.get((region, s), 0) < settings.level_min_days)
                on_test = mine & ~np.isnan(p_today)
                shown = f"{float(np.mean(p_today[on_test])):.2f}" if on_test.any() else "-"
                lines.append(
                    f"| {candidates.TIERS[tier]} | {names[tier][unit]} | {SITUATIONS[s].key} | "
                    f"{n} | {days.size} | {int(counts.max())} | "
                    f"{float(np.clip(rows.y[mine].mean(), settings.floor, settings.ceiling)):.2f}"
                    f" | {nation_rate[s]:.2f} | {shown} |"
                )
    lines += [
        "",
        f"{served} cells served; {thin} of them in a region with fewer than "
        f"{settings.level_min_days} labeled days of the situation (the thin rule, E3b). A cell "
        "C1a serves needs 30 labeled days, so its region always has the thin rule's "
        f'{settings.level_min_days}: C1a turns no cell\'s "Few local records" flag on or off. '
        "C2b's split moves a rate without changing the level a base names, so the flag's "
        "count on alert days is today's.",
        "",
    ]
    return lines + _split_cells(world, settings, units, names)


def _split_cells(
    world: World,
    settings: ModelSettings,
    units: dict[int, Ints],
    names: dict[int, tuple[str, ...]],
) -> list[str]:
    """C2b's cells on every labeled season (:func:`c1_served_levels`)."""
    test = world.test
    rows = test.rows
    weather = backtest_terms.WEATHER_OF[rows.situation]
    lines = [
        "C2b's cells (snow classes, kind known; every level whose days of that kind have level "
        "support; a row takes the finest of state, region and nation):",
        "",
        "| level | place | situation | kind | its days | its dates | its record | the "
        "level's record | shrunk (strength 8) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    kinds = test.inputs.kind
    snow = np.isin(weather, np.array(candidates.SNOW_CLASSES))
    for tier in (0, 1, 2):
        for unit in sorted(set(units[tier][snow].tolist())):
            if unit < 0:
                continue
            for s in sorted(set(rows.situation[snow & (units[tier] == unit)].tolist())):
                whole = snow & (units[tier] == unit) & (rows.situation == s)
                r = float(np.clip(rows.y[whole].mean(), settings.floor, settings.ceiling))
                for k, word in (
                    (candidates.KIND_COLD, "cold"),
                    (candidates.KIND_WARM, "warm or mixed"),
                ):
                    mine = whole & (kinds == k)
                    if not mine.any():
                        continue
                    days, counts = np.unique(test.day[mine], return_counts=True)
                    n = int(mine.sum())
                    if not pool.level_supported(n, days.size, int(counts.max())):
                        continue
                    y = float(rows.y[mine].sum())
                    shrunk = (y + candidates.SPLIT_STRENGTH * r) / (n + candidates.SPLIT_STRENGTH)
                    place = names[tier][unit] if tier in names else "nation"
                    lines.append(
                        f"| {candidates.TIERS[tier]} | {place} | {SITUATIONS[s].key} | {word} | "
                        f"{n} | {days.size} | {y / n:.2f} | {r:.2f} | {shrunk:.2f} |"
                    )
    lines += [
        "",
        "These records are the archive's captured days, mostly big storm days (T4): a level here "
        "is mostly which days each place's lists were captured, not how readily it closes.",
    ]
    return lines


def _p8_note(world: World) -> str:
    dates = base_dates(world)
    shown = ", ".join(date.fromordinal(d).isoformat() for d in dates) or "none"
    return (
        "2016-02-16 and the busiest 3 training dates of every level record the scored rows "
        f"rest on: {shown}."
    )


def _shift_frame(frame: pl.DataFrame, table: InputTable) -> pl.DataFrame:  # pragma: no cover
    """``frame`` with each row's day moved to its district's next label night."""
    days = [table.shifted(d, day) for d, day in frame.select("district", "day").iter_rows()]
    return frame.with_columns(pl.Series("day", days, dtype=pl.Date))


def _c1_counts(world: World, moved: npt.NDArray[np.bool_]) -> str:
    served, split = world.c1_detail["test"]
    storm = backtest_terms.WEATHER_OF[world.test.rows.situation] > 0
    keep = storm & world.test.has_base & np.isin(world.test.rows.season, np.array(world.seasons))
    return (
        f"{int((moved & keep).sum())} scored storm rows: a state or region record served on "
        f"{int((served & keep).sum())}, the cold/warm split moved {int((split & keep).sum())}"
    )


def penalty_path(spec: Spec, world: World) -> list[str]:
    """The last fold's fit at every penalty of the grid, P2 applied (a diagnostic: it shows
    which way the training rows lean, never a verdict)."""
    from snowlight.predict.terms import PENALTIES, fit_with  # noqa: PLC0415

    season = max(world.seasons)
    source = world.training[season]
    keep = source.has_base & (source.rows.season < season)
    found = design(spec, world, str(season), keep, season)
    lines = ["| penalty | " + " | ".join([*spec.columns(), "snow terms"]) + " |",
             "|---|" + "---|" * (len(spec.columns()) + 1)]  # fmt: skip
    for penalty in PENALTIES:
        model = fit_with(found, penalty, shapes_of(spec), SUPPORT)
        snow = ", ".join(
            f"{t.value} {'/'.join(f'{model.fits[t].value(k):+.2f}' for k in range(6))}"
            for t in (Term.SNOW_ADVISORY, Term.SNOW_STORM)
        ) if spec.piece3 else "off"  # fmt: skip
        weights = " | ".join(f"{v:+.3f}" for v in model.extra)
        lines.append(f"| {penalty:g} | {weights}{' | ' if weights else ''}{snow} |")
    return lines


def _input_counts(world: World, found: Walk) -> str:
    test = world.test
    at = np.concatenate([f.rows for f in found.folds])
    snowy = np.isin(test.own[at], np.array(candidates.SNOW_CLASSES))
    inputs = test.inputs.subset(at)
    named = (
        ("temperature known", inputs.temperature >= 0),
        ("cold", inputs.temperature == candidates.COLD),
        ("near", inputs.temperature == candidates.NEAR),
        ("warm", inputs.temperature == candidates.WARM),
        ("mixed", inputs.mixed),
        ("snow forecast", inputs.snow),
        ("done overnight", inputs.timing == candidates.DONE_OVERNIGHT),
        ("ends early", inputs.timing == candidates.ENDS_EARLY),
        ("afternoon", inputs.timing == candidates.AFTERNOON),
        ("school day", inputs.timing == candidates.SCHOOL_DAY),
        ("alert begun by 21:00", inputs.gate),
    )
    parts = [f"{int(snowy.sum())} snow-class rows"]
    parts += [f"{name} {int((snowy & mask).sum())}" for name, mask in named]
    return "; ".join(parts)


def _advisory_buckets(world: World, context: Context, before: Walk, after: Walk) -> list[str]:
    """Addendum g's advisory table: chance before and after by snow bucket."""
    n = len(world.test.rows)
    p0 = chance_of(before, n)
    p1 = chance_of(after, n)
    weather = backtest_terms.WEATHER_OF[world.test.rows.situation]
    keep = (weather == int(WeatherClass.ADVISORY)) & ~np.isnan(p0) & ~np.isnan(p1)
    buckets = np.array(
        [
            backtest_terms.forecast_stratum(1, int(c), False).split(" | ")[1]
            for c in context.code.tolist()
        ],
        dtype=object,
    )
    lines = ["| snow bucket | rows | closed | before | after |", "|---|---|---|---|---|"]
    for bucket in sorted(set(buckets[keep].tolist())):
        mine = keep & (buckets == bucket)
        y = world.test.rows.y[mine]
        lines.append(
            f"| {bucket} | {int(mine.sum())} | {float(y.mean()):.2f} | "
            f"{float(p0[mine].mean()):.2f} | {float(p1[mine].mean()):.2f} |"
        )
    return lines
