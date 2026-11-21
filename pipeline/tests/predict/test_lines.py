"""Each district's own part in shadow (each-school P6a): the prior-neutral base, the own fit,
R-KYY and M5y, the shadow arms a pass writes, the record's one reader, and the proof that
nothing served changes. SYNTHETIC rows, counts and districts only.
"""

import ast
import functools
import json
import math
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import pytest
from pydantic import ValidationError

from predict import test_forecast_adjust as fa_test
from predict import world
from predict.test_frozen import TIMES, Clock, _finished_day, adjusting_pass
from predict.test_publish import MemoryHost
from snowlight.live import evidence
from snowlight.predict import anchor_labels, backtest_lines, cli, frozen, lines, record
from snowlight.predict.anchor import LiveLabels, LiveRow
from snowlight.predict.config import (
    EACH_SCHOOL_SHA256,
    LIVE_SCORE_SHA256,
    PIPELINE_ROOT,
    PredictConfig,
    each_school_sha256,
    live_score_sha256,
)
from snowlight.predict.lines import OwnFit, OwnRow, Shadow
from snowlight.predict.record import Call, Cause, Scope, SourceKind

PACKAGE = PIPELINE_ROOT / "snowlight"

# --- the prior-neutral base (3.2) -------------------------------------------------------------

PLANTED = [
    (0.10, 0.0), (0.10, 0.7744), (0.03, 1.0), (0.45, 2.25), (0.90, 0.25), (0.01, 1.5),
    (0.5, 0.5), (0.2, 0.05), (0.99, 1.0),
]  # fmt: skip


@pytest.mark.parametrize(("base", "v0"), PLANTED)
def test_a_unit_at_its_prior_gets_the_base_exactly(base: float, v0: float) -> None:
    p = float(lines.served(base, v0, 0.0, v0))
    assert abs(p - base) < 1e-9
    assert round(p, 2) == round(base, 2)


def test_a_well_read_unit_moves_by_what_its_record_says_as_an_average() -> None:
    # each-school 3.2's own numbers (r5/base_probe.out): 10% base, s_own 0.88, variance 0.05
    v0 = 0.88**2
    found = [round(float(lines.served(0.10, v0, m, 0.05)) * 100, 2) for m in (0.0, 0.5, -0.5)]
    assert found == [7.83, 12.26, 4.91]
    assert round(float(lines.served(0.10, v0, 0.0, v0)) * 100, 2) == 10.00


@pytest.mark.parametrize("m", [-1.2, -0.3, -0.01, 0.0, 0.01, 0.4, 1.5])
def test_own_s_points_have_the_sign_of_its_mean_and_the_parts_sum_to_the_chance(m: float) -> None:
    base, v0, v = 0.12, 0.64, 0.1
    points, rest = lines.own_points(base, v0, m, v)
    assert points == 0 if m == 0 else math.copysign(1, points) == math.copysign(1, m)
    assert abs(base + rest + points - float(lines.served(base, v0, m, v))) < 1e-12


def test_the_folded_base_applies_own_to_the_class_level_first() -> None:
    """Lead ruling LR23's fixture: class base 3 (and one at 8), a 40% day, own about -11
    points, the sign rule failing: the base's points stay in 1..99 and the forecast's share
    (the chance less the base) is what is left, so the why adds up by construction."""
    v0, v, m = 0.3, 0.25, -0.51
    chance = float(lines.served(0.40, v0, m, v))
    points, _rest = lines.own_points(0.40, v0, m, v)
    assert round(chance * 100) == 29
    assert round(points * 100) == -11
    for level, expected in ((0.03, 2), (0.08, 5)):
        p0, base = lines.folded_base(level, v0, m, v)
        assert base == expected
        assert 1 <= base <= 99
        assert 0.01 <= p0 <= 0.99
        forecast = round(chance * 100) - base
        assert forecast >= 0
        assert base + forecast == 29


@pytest.mark.parametrize("said_open", [False, True])
def test_the_folded_base_is_clamped_to_1_and_99_percent(said_open: bool) -> None:
    """Lead ruling LR26's two fixtures: class 3%, own spread V0 1.0, own -1.5 (its bound); a
    day with no forecast line (the chance is the folded base) and a said-open day (the floor
    of 1%): both keep a base of at least 1 point that adds up to the chance."""
    unclamped = float(lines.served(0.03, 1.0, -1.5, 1.0))
    assert unclamped < 0.01  # under the clamp: the corner LR26 closes
    p0, base = lines.folded_base(0.03, 1.0, -1.5, 1.0)
    assert (p0, base) == (0.01, 1)
    chance = 1 if said_open else base
    assert base + (chance - base) == chance >= 1


# --- the own fit (M5o) ------------------------------------------------------------------------


def synthetic(
    spread: float, *, units: int = 300, mornings: int = 50, per: int = 30, seed: int = 1
) -> tuple[list[OwnRow], np.ndarray[Any, Any]]:
    """A SYNTHETIC world: each morning a storm level of its own, its districts' offsets, and each
    district's own tendency drawn N(0, spread^2)."""
    rng = np.random.default_rng(seed)
    own = rng.normal(0.0, spread, units)
    rows: list[OwnRow] = []
    for j in range(mornings):
        level = rng.normal(-1.0, 1.2)
        day = date(2024, 1, 1) + timedelta(days=j)
        for u in rng.choice(units, per, replace=False):
            offset = float(rng.normal(0.0, 0.5))
            p = 1 / (1 + math.exp(-(level + offset + own[u])))
            rows.append(
                OwnRow(
                    f"99{u:05d}",
                    day,
                    f"{day}|m|advisory",
                    "advisory",
                    offset,
                    bool(rng.uniform() < p),
                )
            )
    return rows, own


def test_a_world_with_no_spread_fits_none_and_a_planted_spread_is_recovered() -> None:
    none, _ = synthetic(0.0)
    assert lines.fit_own(none).spread == 0.0
    assert lines.fit_own(none).units == {}
    rows, own = synthetic(0.9, mornings=80)
    fit = lines.fit_own(rows)
    assert 0.4 < fit.spread <= lines.OWN_BOUND
    means = np.array([fit.posterior(f"99{u:05d}")[0] for u in range(len(own))])
    assert float(np.corrcoef(means, own)[0, 1]) > 0.5
    assert all(abs(m) <= lines.OWN_BOUND and 0 < v <= fit.spread**2 for m, v in fit.units.values())


def test_a_group_with_one_outcome_says_nothing_and_the_level_never_enters() -> None:
    rows, _ = synthetic(0.9)
    fit = lines.fit_own(rows)
    # a whole market-morning closed (or open) adds nothing; nor does moving every row of a
    # group by the same amount (the storm-picked level drops out)
    day = date(2024, 6, 1)
    closed = [
        OwnRow(f"99{u:05d}", day, f"{day}|m|warning", "warning", 0.0, True) for u in range(40)
    ]
    with_closed = lines.fit_own([*rows, *closed])
    assert with_closed.spread == fit.spread
    assert with_closed.units == fit.units
    moved = [
        replace(r, offset=r.offset + (2.0 if r.group.endswith("advisory") else 0.0)) for r in rows
    ]
    shifted = lines.fit_own(moved)
    assert shifted.spread == fit.spread
    assert set(shifted.units) == set(fit.units)
    assert (
        max(
            abs(a - b)
            for u in fit.units
            for a, b in zip(shifted.units[u], fit.units[u], strict=True)
        )
        < 1e-6
    )


def test_rows_of_the_served_day_and_later_never_reach_the_fit() -> None:
    rows, _ = synthetic(0.9)
    served_day = date(2024, 2, 1)
    planted = [
        OwnRow("9900001", d, f"{d}|m|advisory", "advisory", 0.0, k % 2 == 0)
        for d in (served_day, served_day + timedelta(days=1))
        for k in range(6)
    ]
    kept = lines.drop_served([*rows, *planted], served_day)
    assert kept == lines.drop_served(rows, served_day)
    assert lines.fit_own(kept).units == lines.fit_own(lines.drop_served(rows, served_day)).units


# --- the shadow arms ---------------------------------------------------------------------------


FIT_AT: Final = datetime(2026, 11, 16, 19, 31, tzinfo=UTC)
"""A planted fit's time in the tests that only read its lines (a fixed clock, never now)."""


def _row(unit: str, p: float, **change: Any) -> dict[str, object]:
    return {"l": unit, "s": 1, "c": "warning", "pr": p, **change}


def test_the_shadow_arms_are_the_base_at_the_prior_and_move_only_with_evidence(
    tmp_path: Path,
) -> None:
    own = OwnFit(0.8, {"2900001": (0.6, 0.1), "2900002": (-0.6, 0.1)})
    shadow = lines.with_fit(Shadow(folder=tmp_path), own, at=FIT_AT)
    assert shadow.arms == ("m5o", "m5y") == lines.WRITTEN
    rows = [
        _row("2900001", 0.4), _row("2900002", 0.4), _row("2900003", 0.123456789),
        _row("2900004", 0.4, sa=1), _row("2900005", 0.4, c="cold"), _row("2900006", 0.4, s=0),
        {"l": "2900007", "s": 1, "c": "warning"},
    ]  # fmt: skip
    found = {line["l"]: line["es"] for line in shadow.lines(rows)}
    assert set(found) == {"2900001", "2900002", "2900003"}
    assert found["2900003"] == [frozen.es_round(0.123456789), None]
    up, down = found["2900001"][0], found["2900002"][0]  # type: ignore[index]
    assert up > 0.4 > down
    assert up == frozen.es_round(float(lines.served(0.4, 0.64, 0.6, 0.1)))


def test_each_pre_registered_value_equals_the_code_constant_it_registers() -> None:
    """R5-S2 (critic r5-1): the hashed each_school block and the code read the same values;
    a budget, rounding, clock or prior changed on one side alone fails here."""
    block = PredictConfig.load().each_school
    hour, minute = (int(part) for part in block.fit_hour_utc.split(":"))
    registered = {
        "es_budget_xz": (block.es_budget_xz, frozen.ES_DAY_BUDGET_XZ),
        "es_decimals": (block.es_decimals, frozen.ES_DECIMALS),
        "es_coarse": (tuple(block.es_coarse), frozen.ES_COARSE),
        "fit_budget_seconds": (block.fit_budget_seconds, lines.FIT_BUDGET),
        "fit_hour_utc": ((hour, minute), lines.SWITCH_HOUR),
        "fit_max_age_hours": (timedelta(hours=block.fit_max_age_hours), lines.MAX_AGE),
        "own_bound": (block.own_bound, lines.OWN_BOUND),
        "own_prior_scale": (block.own_prior_scale, lines.OWN_SCALE),
        "own_spread_step": (block.own_spread_step, lines.SPREAD_STEP),
        "quadrature_points": (block.quadrature_points, lines.POINTS),
        "take_up_days": (block.take_up_days, lines.TAKE_UP_DAYS),
        "arms": (
            tuple(arm for arm, on in block.arms.items() if on == "on"),
            lines.WRITTEN,
        ),
        "g1": ((block.g1_log_loss, block.g1_brier), backtest_lines.LIMITS),
        "named_nats": (block.named_nats, backtest_lines.NAMED),
        "group_min": (block.group_min, backtest_lines.GROUP_MIN),
        "sign_units": (block.sign_units, backtest_lines.SIGN_UNITS),
        "sign_p": (block.sign_p, backtest_lines.SIGN_P),
    }
    differ = {name: pair for name, pair in registered.items() if pair[0] != pair[1]}
    assert differ == {}
    assert list(block.arms) == list(lines.ARMS)  # the registered order is the written order


def test_mp_and_m5g_stay_off_and_the_config_refuses_them_on() -> None:
    assert {arm for arm, off in lines.ARMS.items() if off is not None} == {"mp", "m5g"}
    assert "mp" not in lines.WRITTEN
    assert "m5g" not in lines.WRITTEN
    config = PredictConfig.load()
    assert config.each_school.arms == {"m5o": "on", "m5y": "on", "mp": "off", "m5g": "off"}
    for arm in ("mp", "m5g"):
        body = config.each_school.model_dump()
        body["arms"] = {**body["arms"], arm: "on"}
        with pytest.raises(ValidationError, match=rf"each_school\.arms\.{arm} is off only"):
            type(config.each_school).model_validate(body)
    body = config.each_school.model_dump()
    body["arms"] = {**body["arms"], "m3": "on"}
    with pytest.raises(ValidationError, match=r"each_school\.arms are"):
        type(config.each_school).model_validate(body)


def test_the_registered_block_is_the_code_s_numbers() -> None:
    block = PredictConfig.load().each_school
    assert block.own_bound == lines.OWN_BOUND
    assert block.own_prior_scale == lines.OWN_SCALE
    assert block.own_spread_step == lines.SPREAD_STEP
    assert block.quadrature_points == lines.POINTS
    assert block.fit_hour_utc == "{:02d}:{:02d}".format(*lines.SWITCH_HOUR)
    assert timedelta(hours=block.fit_max_age_hours) == lines.MAX_AGE
    assert block.fit_budget_seconds == lines.FIT_BUDGET
    assert block.es_decimals == frozen.ES_DECIMALS
    assert tuple(block.es_coarse) == frozen.ES_COARSE
    assert block.es_budget_xz == frozen.ES_DAY_BUDGET_XZ
    assert (block.g1_log_loss, block.g1_brier) == backtest_lines.LIMITS
    assert block.group_min == backtest_lines.GROUP_MIN
    assert block.named_nats == backtest_lines.NAMED


def test_the_each_school_hash_is_pinned_moves_with_every_key_but_go_and_not_the_live_score() -> (
    None
):
    config = PredictConfig.load()
    assert each_school_sha256(config) == EACH_SCHOOL_SHA256
    assert live_score_sha256(config) == LIVE_SCORE_SHA256
    go = config.model_copy(
        update={"each_school": config.each_school.model_copy(update={"go": {"p7y_unarmed": True}})}
    )
    assert each_school_sha256(go) == EACH_SCHOOL_SHA256
    for key, value in (
        ("own_bound", 1.4), ("shuffle_times", 999), ("ky_gap_points", 1.5),
        ("starts", {"p7y": date(2026, 11, 20)}), ("shadow", "off"),
    ):  # fmt: skip
        moved = config.model_copy(
            update={"each_school": config.each_school.model_copy(update={key: value})}
        )
        assert each_school_sha256(moved) != EACH_SCHOOL_SHA256, key
        assert live_score_sha256(moved) == LIVE_SCORE_SHA256


# --- the nightly fit -------------------------------------------------------------------------


def _labels(day: date, rows: Sequence[tuple[str, str]]) -> LiveLabels:
    return LiveLabels(
        rows=tuple(
            LiveRow(day=day, district=u, market="m1", tier="A", label=label, weather="snow_warning")  # type: ignore[arg-type]
            for u, label in rows
        ),
        found=True,
    )


WEATHER = {"advisory": 1, "snow_warning": 5}


def write_reads(  # noqa: PLR0913 - the day and its rows, lists and trials
    folder: Path,
    day: date,
    rows: Sequence[tuple[str, str]],
    *,
    weather: str = "snow_warning",
    after: bool = False,
    sources: Sequence[str] = ("list-a",),
    trials: Sequence[tuple[str, bool]] = (),
) -> Path:
    """A SYNTHETIC L1 labeled day (``rows/<day>.json`` and ``trials/<day>.jsonl``): each
    ``(district, label)`` read whole by ``sources``, and each ``(source, named)`` trial."""
    body = {
        "schema_version": 1,
        "day": day.isoformat(),
        "rows": [
            {
                "district": u, "label": label, "tier": "A", "weather": WEATHER[weather],
                "market": "m1", "after": after, "sources": list(sources),
            }
            for u, label in rows
        ],
    }  # fmt: skip
    (folder / "rows").mkdir(parents=True, exist_ok=True)
    (folder / "trials").mkdir(parents=True, exist_ok=True)
    (folder / "rows" / f"{day.isoformat()}.json").write_text(json.dumps(body))
    (folder / "trials" / f"{day.isoformat()}.jsonl").write_text(
        "".join(
            json.dumps({"district": "2900001", "source": s, "tier": "A", "named": n, "weather": 5})
            + "\n"
            for s, n in trials
        )
    )
    return folder


def an_anchor() -> Any:
    """The anchor of a run with no live label (its priors' levels, tau and delay share)."""
    from snowlight.predict import anchor  # noqa: PLC0415
    from snowlight.predict.exposure import Exposure  # noqa: PLC0415

    settings = anchor.AnchorSettings.of(PredictConfig.load())
    return anchor.fit(settings, Exposure((), {}, {}, {}, {}, {}), LiveLabels(), {})


def _shadow(tmp_path: Path, **changes: Any) -> Shadow:
    from snowlight.predict import anchor  # noqa: PLC0415

    settings = anchor.AnchorSettings.of(PredictConfig.load())
    base: dict[str, Any] = {
        "folder": tmp_path / "es",
        "frozen_folder": tmp_path,
        "class_of": settings.class_of,
    }
    return Shadow(**{**base, **changes})


def test_the_nightly_fit_runs_once_after_19_30_utc_or_when_older_than_36_hours(
    tmp_path: Path,
) -> None:
    said: list[str] = []
    shadow = _shadow(tmp_path, say=said.append)
    found = an_anchor()
    at = datetime(2026, 11, 16, 19, 29, tzinfo=UTC)
    assert shadow.due(at)  # none yet
    assert shadow.refresh(at, found)
    assert not shadow.refresh(at + timedelta(minutes=0), found)
    assert shadow.refresh(at + timedelta(minutes=1), found)  # 19:30 has come
    assert not shadow.refresh(at + timedelta(hours=3), found)
    assert shadow.refresh(at + timedelta(hours=1 + 36, minutes=1), found)
    assert len(said) == 3
    assert said[0].startswith("predict lines: fit 2026-11-16 19:29Z in ")
    assert "s_own 0.00" in said[0]
    assert "m5y off: rows K need each district's class days (not built)" in said[0]
    # kept: a new process reads the last fit back and is not due
    again = _shadow(tmp_path)
    assert not again.due(at + timedelta(hours=1 + 36, minutes=2))
    assert again.fit == shadow.fit


def test_a_fit_that_fails_says_one_line_and_is_tried_once_a_window(tmp_path: Path) -> None:
    """A failing nightly fit (no anchor, a broken store, a frozen day that does not read) is
    tried at most once between two 19:30 UTC, in this process or the next."""
    said: list[str] = []
    shadow = _shadow(tmp_path, say=said.append)
    at = datetime(2026, 11, 16, 20, tzinfo=UTC)
    tried = 0
    real = lines.fit_live

    def broken(*_args: Any, **_kwargs: Any) -> OwnFit:
        nonlocal tried
        tried += 1
        raise RuntimeError("planted")

    lines.fit_live = broken
    try:
        for minutes in range(0, 23 * 60, 30):  # every pass until the next 19:30
            assert not shadow.refresh(at + timedelta(minutes=minutes), an_anchor())
        assert tried == 1
        assert said == [
            "predict lines: the nightly fit: RuntimeError: the last kept, tried again from "
            "2026-11-17 19:30Z"
        ]
        later = _shadow(tmp_path, say=said.append)  # the next process keeps the window
        assert not later.refresh(at + timedelta(hours=3), an_anchor())
        assert tried == 1
        assert not later.refresh(datetime(2026, 11, 17, 19, 30, tzinfo=UTC), an_anchor())
        assert tried == 2
    finally:
        lines.fit_live = real
    assert later.refresh(datetime(2026, 11, 18, 19, 31, tzinfo=UTC), an_anchor())
    assert not (tmp_path / "es" / lines.FAILED_NAME).exists()
    assert shadow.lines([_row("2900001", 0.4)]) == []  # the first one never had a fit
    # no anchor this pass is a failure of the same kind, said once
    none = _shadow(tmp_path / "none", say=said.append)
    assert not none.refresh(at, None)
    assert said[-1].startswith("predict lines: the nightly fit: ValueError: the last kept")


@pytest.mark.parametrize(
    "body",
    [
        {"schema": lines.FIT_SCHEMA, "units": [], "spread": 0.0, "rows": 0, "groups": 0},
        {"schema": lines.FIT_SCHEMA, "units": {"1": 3}, "spread": "x"},
        {"schema": lines.FIT_SCHEMA, "ledger": [[1, 2]], "lists": {}, "units": {}},
        [1, 2, 3],
    ],
)
def test_a_kept_fit_of_the_wrong_shape_is_no_fit_and_never_raises(
    tmp_path: Path, body: object
) -> None:
    (tmp_path / "es").mkdir()
    (tmp_path / "es" / lines.FIT_NAME).write_text(json.dumps(body))
    said: list[str] = []
    shadow = _shadow(tmp_path, say=said.append)
    assert shadow.lines([_row("2900001", 0.4)]) == []
    assert shadow.due(datetime(2026, 11, 16, 20, tzinfo=UTC))
    assert shadow.refresh(datetime(2026, 11, 16, 20, tzinfo=UTC), an_anchor())
    assert len(said) == 1
    assert said[0].startswith("predict lines: fit ")


def _frozen_unit(folder: Path) -> tuple[frozen.FrozenDay, str, str]:
    data = _finished_day(folder)
    day = frozen.parse_day(data)
    served_rows = [
        r
        for r in day.rows
        if r.freeze == lines.FIT_FREEZE and r.served and r.klass in lines.CLASSES
    ]
    assert served_rows
    return day, served_rows[0].leaid, str(served_rows[0].klass)


def test_each_labeled_day_enters_the_ledger_once_from_its_20_07_freeze(tmp_path: Path) -> None:
    folder = tmp_path / "frozen"
    day, unit, klass = _frozen_unit(folder)
    weather = "advisory" if klass == "advisory" else "snow_warning"
    reads = write_reads(
        tmp_path / "reads", day.day, [(unit, "unnamed"), ("9999999", "no_school")],
        weather=weather, sources=("list-b", "list-a"),
        trials=[("list-a", True), ("list-a", False), ("list-b", True)],
    )  # fmt: skip
    shadow = _shadow(folder, reads=reads)
    now = datetime.combine(day.day + timedelta(days=1), datetime.min.time(), UTC)
    assert shadow.refresh(now.replace(hour=20), an_anchor())
    assert shadow.entered == {day.day.isoformat(): "taken"}
    [row] = shadow.ledger
    p = next(
        r.p_raw for r in day.rows if r.freeze == lines.FIT_FREEZE and r.leaid == unit and r.served
    )
    assert p is not None
    assert (row.unit, row.closed, row.label, row.klass) == (unit, False, "unnamed", klass)
    assert row.lists == ("list-a", "list-b")
    assert row.offset == pytest.approx(math.log(p / (1 - p)))
    assert shadow.lists == {"list-a": ["A", 1, 2], "list-b": ["A", 1, 1]}
    # the next night takes nothing again; a day whose frozen day was released is absent, and
    # one the folder lacks waits while the evidence step may restore it (then too old: absent)
    write_reads(reads, day.day - timedelta(days=3), [(unit, "no_school")], weather=weather)
    index = frozen.load_index(folder)
    index.done[(day.day - timedelta(days=3)).isoformat()] = "2026-01-05T00:00:00+00:00"
    frozen.save_index(folder, index)
    write_reads(reads, day.day - timedelta(days=1), [(unit, "no_school")], weather=weather)
    assert shadow.refresh(now.replace(hour=20) + timedelta(days=1), an_anchor())
    assert len(shadow.ledger) == 1
    assert shadow.entered[(day.day - timedelta(days=3)).isoformat()] == "absent"
    assert (day.day - timedelta(days=1)).isoformat() not in shadow.entered  # missing: waits
    shadow.refresh(now + timedelta(days=frozen.RESTORE_DAYS + 2), an_anchor())
    assert shadow.entered[(day.day - timedelta(days=1)).isoformat()] == "absent"
    # a labeled row of the served day is not taken up
    late = _shadow(folder, folder=tmp_path / "late", reads=reads)
    assert late.refresh(
        datetime.combine(day.day, datetime.min.time(), UTC).replace(hour=20), an_anchor()
    )
    assert late.ledger == []
    assert day.day.isoformat() not in late.entered


def test_a_pass_takes_up_at_most_its_days_and_the_backlog_over_passes(tmp_path: Path) -> None:
    folder = tmp_path / "frozen"
    day, unit, klass = _frozen_unit(folder)
    weather = "advisory" if klass == "advisory" else "snow_warning"
    reads = write_reads(tmp_path / "reads", day.day, [(unit, "no_school")], weather=weather)
    calls: list[date] = []
    real = frozen.freeze_lines

    def counted(where: Path, which: date, *args: Any) -> Any:
        calls.append(which)
        return real(where, which, *args)

    frozen.freeze_lines = counted  # type: ignore[assignment]
    try:
        shadow = _shadow(folder, reads=reads, take_up=0)
        now = datetime.combine(day.day + timedelta(days=1), datetime.min.time(), UTC)
        assert shadow.refresh(now.replace(hour=20), an_anchor())
        assert calls == []
        assert shadow.ledger == []
        shadow.take_up = 1
        assert not shadow.refresh(now.replace(hour=20, minute=30), an_anchor())  # not due
        assert calls == [day.day]
        assert len(shadow.ledger) == 1
    finally:
        frozen.freeze_lines = real
    kept = _shadow(folder, reads=reads)
    kept.load()
    assert len(kept.ledger) == 1
    # a fresh process's first pass reads the kept ledger before it takes any day up: the day
    # it holds is not read again (no freeze parsed, nothing thrown away)
    calls.clear()
    frozen.freeze_lines = counted  # type: ignore[assignment]
    try:
        fresh = _shadow(folder, reads=reads)
        assert not fresh.refresh(now.replace(hour=20, minute=40), an_anchor())  # not due
    finally:
        frozen.freeze_lines = real
    assert calls == []
    assert len(fresh.ledger) == 1
    assert fresh.entered == {day.day.isoformat(): "taken"}


def test_the_fit_s_pass_takes_up_one_day_at_most(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pass that makes the fit takes up one labeled day at most (the backlog over the next
    passes), so the nightly step stays in its budget with a margin (r4 worst case 7.4 s)."""
    asked: list[int] = []

    def take_up(_self: Shadow, _now: datetime, most: int) -> int:
        asked.append(most)
        return 0

    monkeypatch.setattr(Shadow, "_take_up", take_up)
    shadow = _shadow(tmp_path, take_up=2)
    now = datetime(2026, 11, 16, 20, tzinfo=UTC)
    assert shadow.refresh(now, an_anchor())  # due: no fit yet
    assert not shadow.refresh(now.replace(minute=30), an_anchor())  # not due
    assert asked == [1, 2]
    assert not _shadow(tmp_path / "none", take_up=0).refresh(now, None)
    assert asked == [1, 2, 0]


def test_the_ledger_keeps_two_school_years_and_at_most_its_rows_dropping_oldest_days_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each-school P6a: the ledger is windowed, so the nightly step and ``fit.json`` stay in
    their budgets across winters: rows of the served day's school year and the one before,
    and past :data:`lines.LEDGER_ROWS` its oldest days go whole; the days stay entered."""

    def rows(day: date, n: int) -> list[OwnRow]:
        return [OwnRow(f"29{k:05d}", day, f"{day}|m|advisory", "advisory", 0.0, False)
                for k in range(n)]  # fmt: skip

    old = rows(date(2024, 12, 9), 3)  # 2024-25: two years back, out
    last = rows(date(2025, 12, 9), 4)  # 2025-26
    first = rows(date(2026, 11, 10), 5)  # 2026-27, the served year
    later = rows(date(2026, 11, 12), 5)
    # each day's list trials go with its rows (a list's sensitivity reads the window's days)
    trials = {
        "2024-12-09": {"a": ["A", 3, 3]},
        "2025-12-09": {"a": ["A", 1, 4], "b": ["B", 0, 2]},
        "2026-11-10": {"a": ["A", 2, 2]},
        "2026-11-12": {"b": ["B", 1, 1]},
    }
    shadow = _shadow(tmp_path, ledger=[*old, *last, *first, *later], day_lists=trials)
    shadow.entered = {"2024-12-09": "taken"}
    served = date(2026, 11, 16)
    assert lines.school_year(served, 1) == "2025-26"
    assert shadow.window(served) == 3
    assert shadow.ledger == [*last, *first, *later]
    assert shadow.lists == {"a": ["A", 3, 6], "b": ["B", 1, 3]}
    monkeypatch.setattr(lines, "LEDGER_ROWS", 10)
    assert shadow.window(served) == 4  # 14 rows: the oldest day (4 rows) goes whole
    assert shadow.ledger == [*first, *later]
    assert shadow.lists == {"a": ["A", 2, 2], "b": ["B", 1, 1]}
    monkeypatch.setattr(lines, "LEDGER_ROWS", 7)
    assert shadow.window(served) == 5  # never part of a day: 5 rows of 10 are left
    assert shadow.ledger == later
    assert shadow.lists == {"b": ["B", 1, 1]}
    assert set(shadow.day_lists) == {"2026-11-12"}
    assert shadow.entered == {"2024-12-09": "taken"}
    # and the window's trials are what the kept fit gives back
    shadow.save()
    again = _shadow(tmp_path)
    again.load()
    assert (again.day_lists, again.lists) == (shadow.day_lists, shadow.lists)


def test_r_kyy_pulls_nothing_while_rows_k_are_not_built(tmp_path: Path) -> None:
    def never() -> Any:
        raise AssertionError("R-KYY opened the store with no rows K to fit")

    said: list[str] = []
    shadow = _shadow(tmp_path, kyy_store=never, say=said.append)
    assert shadow.refresh(datetime(2026, 11, 16, 20, tzinfo=UTC), an_anchor())
    assert "m5y off: rows K need each district's class days (not built)" in said[0]


# --- the own part measures what it claims (r4 3 rules 2, 4, 10, 11; r4 9 steps 1, 2) ------


def live_world(  # noqa: PLR0913 - the world's knobs
    spread: float,
    *,
    units: int = 300,
    groups: int = 1500,
    per: int = 3,
    tau: float = 0.6,
    poor: float | None = None,
    seed: int = 2,
) -> list[OwnRow]:
    """A SYNTHETIC live world under the anchor's model: each market-day its effect
    ``N(0, tau^2)``, each district's own tendency ``N(0, spread^2)``; a closing is named by
    its list at the list's sensitivity (0.95; ``poor`` for the first third of districts' list),
    every other row ``unnamed``."""
    rng = np.random.default_rng(seed)
    own = rng.normal(0.0, spread, units)
    picked = np.array([rng.choice(units, per, replace=False) for _ in range(groups)])
    e = np.repeat(rng.normal(0.0, tau, groups), per)
    who = picked.ravel()
    base = rng.uniform(0.05, 0.6, who.size)
    x = lines.solve_fast(base, np.full(who.size, tau * tau))
    closed = rng.uniform(size=who.size) < 1 / (1 + np.exp(-(x + e + own[who])))
    lowered = (who < units // 3) if poor is not None else np.zeros(who.size, dtype=bool)
    named = rng.uniform(size=who.size) < np.where(lowered, poor or 0.0, 0.95)
    rows: list[OwnRow] = []
    for k, u in enumerate(who):
        day = date(2026, 1, 1) + timedelta(days=int(k // per))
        label = "no_school" if closed[k] and named[k] else "unnamed"
        rows.append(
            OwnRow(
                f"99{u:05d}", day, f"{day}|m{k // per}|advisory", "advisory",
                math.log(base[k] / (1 - base[k])), label == "no_school", label, "A",
                ("poor" if lowered[k] else "good",),
            )
        )  # fmt: skip
    return rows


def _terms(**lists: float) -> lines.LiveTerms:
    return lines.LiveTerms(
        tau={"advisory": 0.6, "warning": 0.6},
        q={"advisory": 0.0, "warning": 0.0},
        tier_prior={"A": (9.0, 1.0), "B": (5.0, 5.0)},
        tier_b=frozenset(),
        lists=lists,
    )


def _delay_world(seed: int, *, silent: bool, q: float = 0.25) -> list[OwnRow]:
    """SYNTHETIC: no own tendency, 300 districts, 1,500 market-mornings of 3; a district not
    closed is delayed with chance 0.25; every list names a closing or a delay with chance
    0.95, except (``silent``) list ``n``, the first third's, which never posts delays."""
    rng = np.random.default_rng(seed)
    units, groups, per, tau = 300, 1500, 3, 0.6
    who = np.array([rng.choice(units, per, replace=False) for _ in range(groups)]).ravel()
    e = np.repeat(rng.normal(0.0, tau, groups), per)
    base = rng.uniform(0.05, 0.6, who.size)
    x = lines.solve_fast(base, np.full(who.size, tau * tau))
    closed = rng.uniform(size=who.size) < 1 / (1 + np.exp(-(x + e)))
    delay = (~closed) & (rng.uniform(size=who.size) < q)
    third = who < units // 3
    named = rng.uniform(size=who.size) < 0.95
    rows = []
    for k, u in enumerate(who):
        day = date(2026, 1, 1) + timedelta(days=int(k // per))
        posts = not (silent and third[k])
        label = (
            "no_school" if closed[k] and named[k]
            else "delayed" if delay[k] and named[k] and posts
            else "unnamed"
        )  # fmt: skip
        rows.append(OwnRow(
            f"99{u:05d}", day, f"{day}|m{k // per}|advisory", "advisory",
            math.log(base[k] / (1 - base[k])), label == "no_school", label, "A",
            ("n",) if third[k] else ("l",),
        ))  # fmt: skip
    return rows


def test_a_list_that_never_posts_delays_takes_no_delay_share() -> None:
    """Honesty rule 3: a list that never names a delay says nothing about one, so its unnamed
    rows take no delay share (``q_of`` 0), and its districts read as they do in the world where
    every list posts delays (the same ``s_own`` and mean own part for the third on it, where
    one delay share for every list moves that third's mean by 0.01 to 0.015); a list that
    posts delays keeps its class's ``q``."""
    terms = lines.LiveTerms(
        tau={"advisory": 0.6}, q={"advisory": 0.5}, tier_prior={"A": (9.0, 1.0)},
        tier_b=frozenset(), lists={"l": 0.95, "n": 0.95}, delays=frozenset({"l"}),
    )  # fmt: skip
    row = OwnRow("9900001", date(2026, 1, 6), "g", "advisory", 0.0, False, "unnamed", "A", ("n",))
    assert terms.q_of(row) == 0.0
    assert terms.q_of(replace(row, lists=("l",))) == 0.5
    assert replace(terms, delays=None).q_of(row) == 0.5

    def third(fit: OwnFit) -> float:
        return float(np.mean([m for u, (m, _) in fit.units.items() if int(u[2:]) < 100] or [0]))

    for seed in (2, 4):  # two worlds whose noise moves the fit, so the third's mean can move
        rows = _delay_world(seed, silent=True, q=0.5)
        assert lines.posting_delays(rows) == {"l"}
        fit = lines.fit_live(rows, replace(terms, delays=lines.posting_delays(rows)))
        one_q = lines.fit_live(rows, replace(terms, delays=None))
        control = lines.fit_live(
            _delay_world(seed, silent=False, q=0.5), replace(terms, delays=None)
        )
        assert fit.spread == pytest.approx(control.spread, abs=0.01)
        assert third(fit) == pytest.approx(third(control), abs=0.003)
        assert abs(third(one_q) - third(control)) > 0.008  # what rule 3 fixes


def test_the_live_fit_reports_rows_on_lists_with_no_trials_and_runs_11g_on_them(
    tmp_path: Path,
) -> None:
    """Honesty rule 2's open door: a list with no co-listing trials sits at its tier's prior
    mean. The fit line and ``fit.json`` count the rows the fit read on such a list, each
    unit's share of them and the units on no other list, and 11(g) runs the own part
    against each unit's list sensitivity and no-trial share."""
    terms = lines.LiveTerms(
        tau={"advisory": 0.6}, q={"advisory": 0.0}, tier_prior={"A": (9.0, 1.0)},
        tier_b=frozenset(), lists={"l": 0.7, "n": 0.9}, trials={"l": 10, "n": 0},
    )  # fmt: skip
    day = date(2026, 1, 6)
    rows = [
        OwnRow("2900001", day, "g1", "advisory", 0.0, True, "no_school", "A", ("n",)),
        OwnRow("2900001", day, "g2", "advisory", 0.0, False, "unnamed", "A", ("l",)),
        OwnRow("2900002", day, "g1", "advisory", 0.0, False, "unnamed", "A", ("n",)),
        OwnRow("2900003", day, "g2", "advisory", 0.0, False, "unnamed", "A", ("l",)),
        OwnRow("2900004", day, "g2", "advisory", 0.0, False, "unnamed", "A", ()),
    ]
    assert terms.no_trial(rows[0])
    assert not terms.no_trial(rows[1])
    assert terms.no_trial(rows[4])
    own = OwnFit(0.5, {u: (0.1 * k, 0.01) for k, u in enumerate(sorted({r.unit for r in rows}))})
    checks = lines.live_checks(rows, terms, own)
    assert (checks.rows, checks.no_trial_rows) == (5, 3)
    assert checks.open_units == ("2900002", "2900004")
    assert checks.share == {"2900001": 0.5, "2900002": 1.0, "2900003": 0.0, "2900004": 1.0}
    assert set(checks.misattribution) == {"list sensitivity", "no-trial share"}
    assert checks.misattribution["no-trial share"][0] == 4
    body = checks.as_json()
    assert body["no_trial_rows"] == 3
    assert body["open_units"] == ["2900002", "2900004"]
    # the nightly fit says them in its line and keeps them in fit.json
    said: list[str] = []
    shadow = _shadow(tmp_path, say=said.append)
    assert shadow.refresh(datetime(2026, 11, 16, 19, 31, tzinfo=UTC), an_anchor())
    assert "0 rows on a list with no trials (0 districts on no other), 11(g) flags none" in said[0]
    kept = json.loads((tmp_path / "es" / lines.FIT_NAME).read_bytes())
    assert kept["checks"]["no_trial_rows"] == 0


def test_tier_b_rows_enter_only_for_the_class_whose_fit_lets_them_in() -> None:
    """Addendum B1.5 per class: with the warning fit's tier B rule met and the advisory fit's
    not, a tier B warning row enters and a tier B advisory row does not."""
    found = an_anchor()
    fits = dict(found.fits)
    fits["warning"] = replace(fits["warning"], tier_b=True)
    fits["advisory"] = replace(fits["advisory"], tier_b=False)
    terms = lines.LiveTerms.of(replace(found, fits=fits), {})
    assert terms.tier_b == {"warning"}
    row = OwnRow("2900001", date(2026, 1, 6), "g", "warning", 0.0, True, "no_school", "B")
    assert terms.uses(row)
    assert not terms.uses(replace(row, klass="advisory"))
    assert terms.uses(replace(row, klass="advisory", tier="A"))


def test_a_world_with_no_tendency_whose_lists_miss_closings_reads_no_district_holding_out() -> None:
    """Honesty rule 2: an ``unnamed`` row enters only as ``1 - s (p + (1 - p) q)``. A third of
    the districts' list names half their closings; with each list's sensitivity the fit finds
    no spread in most worlds (a variance at its boundary is above 0 in some), moves no
    district's chance by a point (r4 11(a)'s limit), and the poorly read third does not read
    as holding out. Read as certain opens (sensitivity 1), the same worlds call them holdouts."""
    spreads: list[float] = []
    for seed in range(5):
        rows = live_world(0.0, poor=0.5, seed=seed)
        fit = lines.fit_live(rows, _terms(good=0.95, poor=0.5))
        spreads.append(fit.spread)
        moved = [
            100 * abs(float(lines.served(0.3, fit.spread**2, m, v)) - 0.3)
            for m, v in fit.units.values()
        ] or [0.0]
        assert float(np.median(moved)) < 1.0  # r4 11(a): under 1 point for the median unit...
        assert float(np.quantile(moved, 0.99)) < 3.0
        low = [m for u, (m, _) in fit.units.items() if int(u[2:]) < 100]
        rest = [m for u, (m, _) in fit.units.items() if int(u[2:]) >= 100]
        if low and rest:
            assert abs(sum(low) / len(low) - sum(rest) / len(rest)) < 0.02
        certain = lines.fit_live(rows, _terms(good=1.0, poor=1.0))
        assert certain.spread > 0.2
        held_out = [m for u, (m, _) in certain.units.items() if int(u[2:]) < 100]
        assert sum(held_out) / len(held_out) < -0.1
    assert sorted(spreads)[2] < 0.05


def test_each_list_s_sensitivity_is_its_tier_prior_and_its_own_trials() -> None:
    terms = lines.LiveTerms.of(an_anchor(), {"a": ["A", 9, 10], "b": ["B", 1, 10]})
    from snowlight.predict import anchor  # noqa: PLC0415

    a0, b0 = anchor.AnchorSettings.of(PredictConfig.load()).tier_a_prior
    assert terms.lists["a"] == pytest.approx((a0 + 9) / (a0 + b0 + 10))
    row = OwnRow("2900001", SERVED, "g", "advisory", 0.0, False, "unnamed", "A", ("a", "b"))
    assert terms.s_of(row) == max(terms.lists.values())
    assert terms.s_of(replace(row, lists=())) == pytest.approx(a0 / (a0 + b0))
    assert terms.uses(row)
    assert not terms.uses(replace(row, tier="B"))  # tier B only under the anchor's rule
    assert set(terms.tau) == set(terms.q) == set(lines.CLASSES)


@pytest.mark.parametrize(("per", "groups"), [(2, 6000), (3, 4000), (6, 2000)])
def test_small_group_archive_worlds_recover_a_planted_spread(per: int, groups: int) -> None:
    """r4 9: the exact conditional likelihood within market-morning has no incidental-parameter
    bias. A planted spread of 0.5 in groups of 2, 3 and 6 is recovered within 0.1 (a fixed
    effect per group read about 1.0 in groups of 2)."""
    rng = np.random.default_rng(per)
    own = rng.normal(0.0, 0.5, 300)
    rows: list[OwnRow] = []
    for j in range(groups):
        level = rng.normal(-0.5, 1.5)
        day = date(2020, 1, 1) + timedelta(days=j)
        for u in rng.choice(300, per, replace=False):
            offset = float(rng.normal(0.0, 0.5))
            p = 1 / (1 + math.exp(-(level + offset + own[u])))
            rows.append(
                OwnRow(f"99{u:05d}", day, f"{day}|m|advisory", "advisory", offset,
                       bool(rng.uniform() < p))
            )  # fmt: skip
    assert abs(lines.fit_own(rows).spread - 0.5) <= 0.1


@pytest.mark.parametrize("per", [2, 3, 6])
def test_small_group_live_worlds_recover_a_planted_spread(per: int) -> None:
    fit = lines.fit_live(live_world(0.5, per=per, groups=9000 // per), _terms(good=0.95))
    assert abs(fit.spread - 0.5) <= 0.1


def test_one_storm_cannot_carry_more_than_its_share() -> None:
    """r4 9 step 2: the new parts' rows carry the anchor's storm weights, so a storm holds at
    most its class's ``max_date_share`` of the information, the start counted in."""
    from snowlight.predict import anchor  # noqa: PLC0415

    settings = anchor.AnchorSettings.of(PredictConfig.load())
    tempering = lines.Tempering.of(
        settings, {k: settings.priors[k].alpha_mean for k in lines.CLASSES}
    )
    rows = [
        OwnRow(f"99{u:05d}", date(2026, 11, 13), f"2026-11-13|m{u % 40}|warning", "warning",
               0.0, u % 2 == 0)
        for u in range(2000)
    ] + [
        OwnRow(f"99{u:05d}", date(2025, 1, 6) + timedelta(days=14 * k),
               f"{date(2025, 1, 6) + timedelta(days=14 * k)}|m{u}|warning", "warning", 0.0, False)
        for k in range(6)
        for u in range(3)
    ]  # fmt: skip
    weights = lines.group_weights(rows, tempering)
    c = tempering.c["warning"]
    sizes: dict[str, int] = {}
    for row in rows:
        sizes[row.group] = sizes.get(row.group, 0) + 1
    big = sum(weights[g] * n / (n + c) for g, n in sizes.items() if g.startswith("2026-11-13"))
    whole = tempering.start["warning"] + sum(weights[g] * n / (n + c) for g, n in sizes.items())
    assert big / whole == pytest.approx(tempering.cap["warning"], rel=1e-6)
    assert all(weights[g] == 1.0 for g in sizes if not g.startswith("2026-11-13"))
    assert lines.group_weights(rows, None) == dict.fromkeys(sizes, 1.0)


def test_a_planted_0900002_row_never_reaches_a_fit_and_the_line_counts_rule_4() -> None:
    config = PredictConfig.load()
    excluded = frozenset(config.each_school.own_excluded)
    assert "0900002" in excluded
    assert all(len(unit) == 7 and unit.isdigit() for unit in excluded)
    rows, _ = synthetic(0.9)
    planted = [OwnRow("0900002", r.day, r.group, r.klass, r.offset + 3.0, True) for r in rows[::30]]
    fit = lines.fit_own([*rows, *planted], excluded=excluded)
    assert "0900002" not in fit.units
    assert fit.excluded == len(planted)
    assert fit.units == lines.fit_own(rows, excluded=excluded).units
    live = [replace(r, label="no_school", lists=("good",)) for r in planted]
    assert "0900002" not in lines.fit_live(live, _terms(good=0.9), excluded=excluded).units
    folds = backtest_lines.walk_forward([*rows, *planted], 2023, excluded=excluded)
    assert all("0900002" not in fit.units for _, fit in folds.values())
    labeled = _labels(SERVED, [("0900002", "no_school"), ("2900001", "no_school")]).rows
    frozen_rows = [{"l": u, "s": 1, "c": "warning", "pr": 0.3} for u in ("0900002", "2900001")]
    taken = lines.live_rows(
        labeled, frozen_rows, class_of={"snow_warning": "warning"}.get, excluded=excluded
    )
    assert [r.unit for r in taken] == ["2900001"]


def test_day_after_rows_and_rows_of_another_class_never_enter_the_ledger() -> None:
    """Rule 10: day-after rows wait for R10; the bus switch's rule: L1's class of the day is the
    row's served class."""
    found = _labels(SERVED, [("2900001", "no_school"), ("2900002", "no_school")]).rows
    after = replace(found[0], weather="advisory_after")
    other = replace(found[1], weather="advisory")
    frozen_rows = [{"l": u, "s": 1, "c": "warning", "pr": 0.3} for u in ("2900001", "2900002")]
    class_of = {"snow_warning": "warning", "advisory": "advisory", "advisory_after": "advisory"}
    assert lines.live_rows([after, other], frozen_rows, class_of=class_of.get) == []
    assert [r.unit for r in lines.live_rows(found, frozen_rows, class_of=class_of.get)] == [
        "2900001",
        "2900002",
    ]


# --- R-KYY and M5y ----------------------------------------------------------------------------


def _count(unit: str, year: str, days: int, *, other: int | None = 0) -> record.YearCount:
    return record.YearCount(
        version=1, unit=unit, year=year, code="W", days=days, not_weather=other,
        unconfirmed=0 if other is not None else None, source_kind=SourceKind.PAST_RECORDS,
        sources=("ky-trend-2025-26",), covid=year in {"2019-20", "2020-21"}, disaster=None,
    )  # fmt: skip


def _past(day: date, unit: str) -> record.PastDay:
    return record.PastDay(
        version=1, day=day, unit=unit, weather=None, klass="unknown", after=None,
        after_weather=None, situation=None, call=Call.CLOSED, source_kind=SourceKind.PAST_RECORDS,
        source_complete=False, closings_only=True, scope=Scope.WHOLE, cause=Cause.WEATHER,
        weather_day=True, fit_usable=False, reasons=(), tropical=None,
        sources=("ky-summary-2024-25",), code="W",
    )  # fmt: skip


KY = [f"21{n:05d}" for n in range(40)]


def _kept(
    extra_counts: Sequence[record.YearCount] = (), extra_days: Sequence[record.PastDay] = ()
) -> dict[str, bytes]:
    rng = np.random.default_rng(3)
    lean = {u: float(rng.normal(0, 0.6)) for u in KY}
    counts = [
        _count(u, f"{y}-{(y + 1) % 100:02d}", int(rng.poisson(4 * math.exp(lean[u]))))
        for u in KY
        for y in range(2015, 2026)
    ]
    days = [_past(date(2025, 1, 6 + k), u) for k, u in enumerate(KY[:5])]
    return {
        "past/ky-trend-2025-26/v1/counts": record.lines_bytes([*counts, *extra_counts], "t"),
        "past/ky-summary-2024-25/v1/days": record.lines_bytes([*days, *extra_days], "t"),
        "past/nc-summary-2024-25/v1/counts": record.lines_bytes(
            [_count("3700001", "2024-25", 9)], "t"
        ),
        "2026-11-13": b"",
    }


SERVED = date(2026, 11, 17)


class _Store:
    """An evidence store holding the record kind's keys ``found()`` and no other kind."""

    def __init__(self, found: Callable[[], Mapping[str, bytes]]) -> None:
        self.found = found

    def pull(
        self, kind: str, _since: date | None = None, *, capability: object = None
    ) -> dict[str, bytes]:
        if kind == evidence.RECORD and capability is not lines._READ:
            raise evidence.RecordRefusedError("planted: no capability")
        return dict(self.found()) if kind == evidence.RECORD else {}


def _store_of(found: Callable[[], Mapping[str, bytes]]) -> Callable[[], Any]:
    """lines.Shadow's ``kyy_store``: opens a store holding ``found()``."""

    @contextmanager
    def opened() -> Iterator[_Store]:
        yield _Store(found)

    return opened


def lines_rows_k(rows: Sequence[OwnRow]) -> Callable[[], Any]:
    """lines.py's private rows K maker (``lines._rows_k``) replaced, through monkeypatch, by one
    made in lines.py's own namespace that yields ``rows`` (lead ruling LR-P6A-6: the fit
    refuses a maker made anywhere else)."""
    made: Callable[[], Any] = eval(  # noqa: S307 - the test's maker, made as lines.py's own
        "lambda: lambda _inputs: rows", vars(lines) | {"rows": rows}
    )
    return made


def test_r_kyy_reads_kentucky_w_counts_and_dated_days_of_years_before_the_served_one() -> None:
    inputs = lines.read_kyy(_kept(), SERVED)
    assert inputs.before == "2026-27"
    assert {u for u, _ in inputs.counts} == set(KY)
    assert max(y for _, y in inputs.counts) == "2025-26"
    assert not any(y in {"2019-20", "2020-21"} for _, y in inputs.counts)  # COVID years left out
    # the gate fold's window: no count before 2021-22, the same years the gate's t reads
    assert min(y for _, y in inputs.counts) == lines.KY_FIRST == "2021-22"
    assert inputs.counts == backtest_lines._ky_window(inputs.counts, inputs.before)
    early = {"past/ky-early/v1/counts": record.lines_bytes([_count(KY[0], "2018-19", 7)], "t")}
    assert lines.read_kyy(early, SERVED).counts == {}
    assert len(inputs.dated) == 5
    # the days known to be the weather's
    one = lines.read_kyy(
        {"past/ky-one/v1/counts": record.lines_bytes([_count(KY[0], "2023-24", 5, other=2)], "t")},
        SERVED,
    )
    assert one.counts == {(KY[0], "2023-24"): 3}


def test_a_planted_2026_27_count_and_dated_day_change_no_t_no_beta_and_no_served_chance(
    tmp_path: Path,
) -> None:
    """Lead ruling LR24: R-KYY's window. A 2026-27 YearCount and a 2026-27 dated W row dated
    before the served day change nothing."""
    exposure = dict.fromkeys(KY, 10.0)
    plain = lines.read_kyy(_kept(), SERVED)
    planted = lines.read_kyy(
        _kept([_count(KY[1], "2026-27", 30)], [_past(date(2026, 11, 13), KY[1])]), SERVED
    )
    assert planted == plain
    t_plain = lines.fit_tendency(plain.counts, exposure)
    assert lines.fit_tendency(planted.counts, exposure) == t_plain
    rows_k = _rows_k(t_plain)
    slope = lines.fit_slope(rows_k, t_plain.units)
    assert lines.fit_slope(rows_k, lines.fit_tendency(planted.counts, exposure).units) == slope
    fit = lines.ky_fit(t_plain, slope)
    shadow = lines.with_fit(Shadow(folder=tmp_path), OwnFit(0.0, {}), fit, at=FIT_AT)
    before = shadow.lines([_row(KY[1], 0.3)])
    shadow2 = lines.with_fit(
        Shadow(folder=tmp_path),
        OwnFit(0.0, {}),
        lines.ky_fit(lines.fit_tendency(planted.counts, exposure), slope),
        at=FIT_AT,
    )
    assert shadow2.lines([_row(KY[1], 0.3)]) == before


def _rows_k(tendency: lines.Tendency, seed: int = 9, beta: float = 1.0) -> list[OwnRow]:
    """SYNTHETIC rows K: each dated morning, every Kentucky district of the class, listed with
    a chance that rises with its count tendency."""
    rng = np.random.default_rng(seed)
    rows: list[OwnRow] = []
    for j in range(40):
        day = date(2026, 1, 5) + timedelta(days=j)
        for u in KY:
            t = tendency.units[u][0]
            p = 1 / (1 + math.exp(-(-1.0 + beta * t)))
            rows.append(
                OwnRow(u, day, f"{day}|ky|advisory", "advisory", 0.0, bool(rng.uniform() < p))
            )
    return rows


def test_m5y_s_slope_reads_the_count_tendency_and_writes_kentucky_only(tmp_path: Path) -> None:
    inputs = lines.read_kyy(_kept(), SERVED)
    tendency = lines.fit_tendency(inputs.counts, dict.fromkeys(KY, 10.0))
    assert tendency.s_t > 0
    slope = lines.fit_slope(_rows_k(tendency, beta=1.2), tendency.units)
    assert slope.beta is not None
    assert 0.6 < slope.beta < 2.0
    fit = lines.ky_fit(tendency, slope)
    assert fit.v0 == pytest.approx((slope.beta**2 + slope.var) * tendency.s_t**2)
    shadow = lines.with_fit(Shadow(folder=tmp_path), OwnFit(0.0, {}), fit, at=FIT_AT)
    found = {
        line["l"]: line["es"] for line in shadow.lines([_row(KY[0], 0.3), _row("2900001", 0.3)])
    }
    assert found["2900001"] == [0.3, None]
    assert found[KY[0]][1] is not None  # type: ignore[index]
    # no rows K of a known class (the record's dated days are unknown until the backfill)
    off = lines.fit_slope([], tendency.units)
    assert off.beta is None
    assert off.why == "no rows K of a known class"
    assert lines.ky_fit(tendency, off).units == {}


def test_m5y_writes_nothing_at_head_and_says_why(tmp_path: Path) -> None:
    said: list[str] = []
    shadow = _shadow(
        tmp_path, kyy_store=_store_of(_kept), exposure=dict.fromkeys(KY, 10.0), say=said.append
    )
    assert shadow.refresh(datetime(2026, 11, 16, 20, tzinfo=UTC), an_anchor())
    assert "m5y off: rows K need each district's class days (not built)" in said[0]
    assert shadow.lines([_row(KY[0], 0.3)]) == [{"l": KY[0], "es": [0.3, None]}]


def test_a_test_year_row_in_the_gate_fold_s_fit_window_changes_no_fit() -> None:
    exposure = dict.fromkeys(KY, 10.0)
    counts = dict(lines.read_kyy(_kept(), SERVED).counts)
    tendency = lines.fit_tendency(counts, exposure)
    rows_k = [
        replace(r, day=r.day.replace(year=2025 if r.day.month < 7 else 2024))
        for r in _rows_k(tendency)
    ]  # 2024-25's rows
    gate = backtest_lines.ky_gate(counts, rows_k, exposure)
    assert gate.beta is not None
    # a 2025-26 (test year) count and a 2025-26 row K planted change no fitted beta and no t
    # of the fit; nor does a count outside the registered window (2021-22 to 2023-24)
    moved = {**counts, (KY[2], "2025-26"): 99, (KY[3], "2018-19"): 99}
    test_row = OwnRow(KY[2], date(2025, 12, 1), "2025-12-01|ky|advisory", "advisory", 0.0, True)
    planted = backtest_lines.ky_gate(moved, [*rows_k, test_row], exposure)
    assert planted.beta == gate.beta
    window = backtest_lines._ky_window
    assert {y for _, y in window(counts, "2024-25")} == {"2021-22", "2022-23", "2023-24"}
    assert lines.fit_tendency(window(moved, "2024-25"), exposure) == lines.fit_tendency(
        window(counts, "2024-25"), exposure
    )
    # G1(a)'s set and the mean-chance gap are computed on the test year
    assert all(unit in KY for unit in gate.g1_units)
    assert isinstance(gate.gap_points, float)


def test_the_2024_25_cross_fit_reaches_no_gate_switch_or_served_chance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lead ruling LR24: the cross-fit is R-KYY's one later-year read, reported only."""
    exposure = dict.fromkeys(KY, 10.0)
    counts = dict(lines.read_kyy(_kept(), SERVED).counts)
    rows_k = _rows_k(lines.fit_tendency(counts, exposure))
    reported = backtest_lines.ky_cross_fit(counts, rows_k, exposure)
    assert reported.rows >= 0

    def never(*_args: object, **_kwargs: object) -> backtest_lines.KyFold:
        raise AssertionError("the cross-fit reached a gate or a served chance")

    monkeypatch.setattr(backtest_lines, "ky_cross_fit", never)
    backtest_lines.ky_gate(counts, rows_k, exposure)
    monkeypatch.setattr(lines, "_rows_k", lines_rows_k(rows_k))
    shadow = _shadow(tmp_path, kyy_store=_store_of(_kept), exposure=exposure)
    assert shadow.refresh(datetime(2026, 11, 16, 20, tzinfo=UTC), an_anchor())
    shadow.lines([_row(KY[0], 0.3)])
    for name in ("lines.py", "cli.py", "serve.py", "frozen.py"):
        assert "ky_cross_fit" not in (PACKAGE / "predict" / name).read_text() or name == "lines.py"
    tree = ast.parse((PACKAGE / "predict" / "lines.py").read_text())
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "ky_cross_fit" not in calls


# --- the record's one reader (10.5, LR19, LR21) -----------------------------------------------


def _served_and_later(rows: Sequence[OwnRow], served: date) -> list[OwnRow]:
    """SYNTHETIC rows of the served day and the day after, in groups of three of their own with
    the first of each closed (named by its list) and the others open: rows a fit that read
    them would move by."""
    return [
        replace(
            r, day=served + timedelta(days=(k // 3) % 2), closed=k % 3 == 0,
            group=f"{served}|planted{k // 3}|{r.klass}",
            label="no_school" if k % 3 == 0 else "unnamed",
        )
        for k, r in enumerate(rows)
    ]  # fmt: skip


def test_the_nightly_fit_reads_no_row_of_the_served_day_or_later_from_its_ledger_or_rows_k(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5-S2: rows of the served day and the day after planted in a kept fit.json ledger, and
    in R-KYY's rows K, change no unit and no spread of the nightly fit (each of _fit's two
    drop_served calls)."""
    now = datetime(2026, 11, 16, 20, tzinfo=UTC)
    exposure = dict.fromkeys(KY, 10.0)
    ledger = live_world(0.3, units=60, groups=200)
    rows_k = _rows_k(lines.fit_tendency(dict(lines.read_kyy(_kept(), SERVED).counts), exposure))

    def fitted(name: str, planted: bool) -> Shadow:
        kept = _shadow(tmp_path / name, ledger=list(ledger), loaded=True)
        if planted:
            kept.ledger += _served_and_later(ledger[:300], now.date())
        kept.save()  # the kept fit.json's ledger
        k_rows = [*rows_k, *(_served_and_later(rows_k[:200], now.date()) if planted else [])]
        monkeypatch.setattr(lines, "_rows_k", lines_rows_k(k_rows))
        shadow = _shadow(tmp_path / name, kyy_store=_store_of(_kept), exposure=exposure)
        shadow.load()
        assert len(shadow.ledger) == len(kept.ledger)  # the planted rows are in the ledger read
        assert shadow.refresh(now, an_anchor())
        return shadow

    plain, planted = fitted("plain", planted=False), fitted("planted", planted=True)
    assert plain.own is not None
    assert planted.own is not None
    assert plain.ky is not None
    assert planted.ky is not None
    assert plain.own.rows == len(ledger)  # every row before the served day read
    assert plain.ky.units  # M5y's units, from rows K, so a planted row K would move them
    assert (planted.own.rows, planted.own.groups) == (plain.own.rows, plain.own.groups)
    assert planted.own.units == plain.own.units
    assert planted.own.spread == plain.own.spread
    assert planted.ky.units == plain.ky.units
    assert planted.ky.v0 == plain.ky.v0


RECORD_MODULE = "snowlight.predict.record"
EVIDENCE = "snowlight.live.evidence"
OWNERS = frozenset({"predict/record.py", "predict/state_records.py", "live/evidence.py"})
"""The record itself, its state-records step and the store that defines its kind."""
PASS_CODE = frozenset({"one_pass", "make_pass", "_make_shadow", "shadow_or_none", "_record_frozen"})
"""cli.py's pass code, held to the serving modules' rule: it touches the record nowhere. It
hands the shadow a store opener (``_make_shadow.kyy_store``), not a pull: the record comes out
of a store only by its kind written out or through :func:`lines.store_past`, each a touch."""
READ_NAMES: Final = frozenset(name for names in lines.READS.values() if names for name in names)
"""lines.py's named reads of the record (``store_past``, ``read_kyy``): a call to, an import
of or any other use of one is a touch, in every module."""
SHADOW_STORE: Final = "kyy_store"
"""lines.Shadow's field that opens the store for R-KYY: each use of the attribute, in every
module, is a touch (only ``Shadow._fit`` opens it)."""
ROWS_K: Final = "_rows_k"
"""lines.py's private rows K maker, the one consumer of R-KYY's rows (lead ruling LR-P6A-6):
each use of the name, as a name, an attribute or a string, is a touch in every module."""
SHADOW_ROWS: Final = frozenset({"rows_k", ROWS_K})
"""A keyword argument of one of these names (a consumer of R-KYY's rows handed to the shadow,
as the field lines.Shadow no longer has) is a touch in every module."""
STORE_READS: Final = frozenset({"pull", "pull_all", "held", "versions", "items"})
"""The evidence store's reads by kind (``EvidenceStore`` and ``EvidenceDatabase``): a call
of one whose kind is not a named constant or a string is a touch, and so is each use of one
not called in place (a bound method kept, passed or returned: an alias or a partial).
``EvidenceDatabase.read`` and ``parts`` take an :class:`evidence.Item`, whose kind is set
where it is made: by ``items`` (here) or by ``Item(...)`` (:data:`ITEM_MAKERS`)."""
ITEM_MAKERS: Final = frozenset({"Item"})
"""The store's item, made by a kind not written out (a store read by hand), is a touch."""
STORE_SQL: Final = frozenset({"_ITEMS", "_HELD", "_PARTS"})
"""The store's own statements: a use of one, or a string reading its ``items`` or ``parts``
table, is a touch."""
OPAQUE: Final = frozenset({"vars", "eval", "exec", "compile", "attrgetter", "methodcaller"})
"""Calls that reach an attribute or run code by a name not written out: each is a touch."""
OPAQUE_ATTRS: Final = frozenset({"__dict__", "__getattribute__"})
LOADERS: Final = frozenset({"import_module", "__import__", "find_spec"})
"""Dynamic imports: one of the record module, or of a module not named by a plain string,
is a touch."""
NAMED: Final = frozenset({"RECORD", SHADOW_STORE, ROWS_K, *READ_NAMES, *STORE_SQL})
"""Names that are a touch wherever they are written, as an attribute or a string."""
RECORD_FILES: Final = frozenset({record.RECORD_PATH.name, record.COUNTS_NAME})
"""The files the record module writes (``record.parquet`` and its yearly counts): a string
holding one's name is a touch."""
HARMLESS: Final = frozenset({"len", "bool", "str", "repr", "tuple", "list", "set", "sorted"})
"""Builtins that keep no callable they are given (a bound read passed to one is no alias)."""


def _resolved(node: ast.ImportFrom, package: str) -> str:
    if not node.level:
        return node.module or ""
    parts = package.split(".")[: len(package.split(".")) - node.level + 1]
    return ".".join([*parts, *([node.module] if node.module else [])])


def _folded(node: ast.AST) -> str | None:
    """A string expression's value when it is made of string constants alone (a constant, a
    sum, an f-string of them, or ``"".join`` of them), else ``None``."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _folded(node.left), _folded(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts = [_folded(v.value if isinstance(v, ast.FormattedValue) else v) for v in node.values]
        return None if any(p is None for p in parts) else "".join(p or "" for p in parts)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and isinstance(node.args[0], (ast.List, ast.Tuple))
        and (glue := _folded(node.func.value)) is not None
    ):
        parts = [_folded(e) for e in node.args[0].elts]
        return None if any(p is None for p in parts) else glue.join(p or "" for p in parts)
    return None


def _names_the_record(value: str) -> bool:
    """Whether a string names the record: its kind, one of :data:`NAMED`, its module, one of
    its files (:data:`RECORD_FILES`) or the store's tables read by hand."""
    lowered = value.lower()
    return (
        value == evidence.RECORD
        or value in NAMED
        or value.startswith(RECORD_MODULE)
        or any(name in value for name in RECORD_FILES)
        or "from items" in lowered
        or "from parts" in lowered
    )


def _string_touches(node: ast.AST, parent: ast.AST | None) -> int:
    """A string that names the record (:func:`_names_the_record`), counted once where it is
    made whole: a constant, or a sum or f-string none of whose parts names it alone. A string
    statement (a docstring) does nothing and is not counted."""
    if isinstance(parent, ast.Expr) and isinstance(node, ast.Constant):
        return 0
    if not isinstance(node, (ast.Constant, ast.BinOp, ast.JoinedStr, ast.Call)):
        return 0
    value = _folded(node)
    if value is None or not _names_the_record(value):
        return 0
    if isinstance(node, ast.Constant):
        return 1
    parts = [p for p in ast.iter_child_nodes(node) if not isinstance(p, ast.operator)]
    parts = [v.value if isinstance(v, ast.FormattedValue) else v for v in parts]
    if isinstance(node, ast.Call):
        parts = list(node.args[0].elts)  # type: ignore[attr-defined]
    return int(not any((v := _folded(p)) is not None and _names_the_record(v) for p in parts))


def _dynamic_kind(node: ast.expr) -> bool:
    """Whether a store read's kind argument may be the record without naming it: anything but
    a string made of constants (one naming the record counts by itself) or a named constant
    (an upper-case name or attribute; ``RECORD`` counts by itself)."""
    if _folded(node) is not None:
        return False
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_dynamic_kind(e) for e in node.elts)
    if isinstance(node, ast.IfExp):
        return _dynamic_kind(node.body) or _dynamic_kind(node.orelse)
    if isinstance(node, ast.Attribute):
        return not node.attr.isupper()
    if isinstance(node, ast.Name):
        return not node.id.isupper()
    return True


def _name_of(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _call_touches(node: ast.Call, makers: set[str]) -> int:
    """A call's touches of the record: a store read (:data:`STORE_READS`) or a store item made
    (:data:`ITEM_MAKERS`, the store's own or bound from it in ``makers``) by a kind not
    written out, or a ``**`` of arguments in one; a dynamic import that may reach the record;
    a ``getattr`` of a name not written out, or of one of :data:`NAMED` or a store read; and
    each opaque call (:data:`OPAQUE`)."""
    name = _name_of(node.func)
    first = node.args[0] if node.args else None
    kinds = [*node.args[:1], *(k.value for k in node.keywords if k.arg in {"kind", "kinds"})]
    spread = sum(1 for k in node.keywords if k.arg is None)
    if name in STORE_READS and isinstance(node.func, ast.Attribute):
        return sum(1 for k in kinds if _dynamic_kind(k)) + spread
    store_item = isinstance(node.func, ast.Attribute) and node.func.attr in ITEM_MAKERS
    store_item = store_item and _name_of(node.func.value) == "evidence"  # type: ignore[attr-defined]
    if store_item or (isinstance(node.func, ast.Name) and name in makers):
        return sum(1 for k in kinds if _dynamic_kind(k)) + spread
    if name in LOADERS and first is not None:
        found = _folded(first)
        return 1 if found is None else int(found.startswith(RECORD_MODULE))
    if name in {"getattr", "hasattr", "setattr", "delattr"} and len(node.args) >= 2:
        found = _folded(node.args[1])
        return 1 if found is None else int(found in NAMED or found in STORE_READS)
    if isinstance(node.func, ast.Name) and name in OPAQUE:
        return 1
    return int(isinstance(node.func, ast.Attribute) and name in {"attrgetter", "methodcaller"})


def _import_touches(node: ast.AST, package: str, aliases: set[str], makers: set[str]) -> int:
    """An import's touches of the record: of the record module or one of its names (relative
    ones too), of the store's ``RECORD`` or of one of lines.py's named reads; each name so
    bound joins ``aliases``. The store's item maker so imported joins ``makers``."""
    found = 0
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == RECORD_MODULE or alias.name.startswith(RECORD_MODULE + "."):
                found += 1
                aliases.add(alias.asname or alias.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        module = _resolved(node, package)
        for alias in node.names:
            if module == EVIDENCE and alias.name in ITEM_MAKERS:
                makers.add(alias.asname or alias.name)
            if (
                module == RECORD_MODULE
                or (module == "snowlight.predict" and alias.name == "record")
                or (module == EVIDENCE and alias.name in {"RECORD", *STORE_SQL})
                or alias.name in READ_NAMES
            ):
                found += 1
                aliases.add(alias.asname or alias.name)
    return found


def _bound_read(node: ast.Attribute, parent: ast.AST | None) -> bool:
    """Whether a store read's attribute is used but not called in place, so that its bound
    method may be kept, passed or returned. Not so: an attribute stored to, one read further
    (``x.held.y``, ``x.held[k]``), and one only tested, compared, formatted or given to a
    builtin that keeps no callable (:data:`HARMLESS`)."""
    if node.attr not in STORE_READS or not isinstance(node.ctx, ast.Load):
        return False
    if isinstance(parent, ast.Call):
        harmless = isinstance(parent.func, ast.Name) and parent.func.id in HARMLESS
        kept = parent.func is not node and not harmless
    elif isinstance(parent, ast.Attribute):
        kept = parent.attr.startswith("__")  # x.pull.__call__ is the method itself
    elif isinstance(parent, ast.Subscript):
        kept = parent.value is not node
    elif isinstance(parent, (ast.FormattedValue, ast.Compare, ast.UnaryOp)):
        kept = False
    elif isinstance(parent, (ast.If, ast.While, ast.Assert, ast.IfExp)):
        kept = parent.test is not node
    elif isinstance(parent, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        kept = parent.value is node
    else:
        kept = True
    return kept


def _use_touches(
    node: ast.AST, parent: ast.AST | None, ctx: tuple[set[str], frozenset[str]]
) -> int:
    """A use's touch of the record: a name bound by such an import (not shadowed by a local),
    a use of one of lines.py's named reads, an attribute in :data:`NAMED` or opaque
    (:data:`OPAQUE_ATTRS`), a bound store read (:func:`_bound_read`), or a string that names
    the record (:func:`_string_touches`)."""
    aliases, local = ctx
    if isinstance(node, ast.Name):
        named = node.id in aliases or node.id in READ_NAMES or node.id == ROWS_K
        return int(node.id not in local and named)
    if isinstance(node, ast.Attribute):
        named = node.attr in NAMED or node.attr in OPAQUE_ATTRS
        return int(named) + int(_bound_read(node, parent))
    return _string_touches(node, parent)


def record_touches(source: str, package: str) -> Counter[str]:
    """Every touch of the record in a module, by scope (its top-level function,
    ``Class.method``, a top-level function's nested ``outer.inner``, or ``<module>``). The
    record is reached only by naming it, so each way of naming it is counted wherever it is
    written: (1) an import of the record module or of one of its names, of the store's
    ``RECORD`` or statements, or of one of lines.py's named reads, and each use of a name so
    bound; (2) an attribute ``RECORD``, ``kyy_store``, ``_rows_k``, a named read or a store
    statement, a name ``_rows_k``, and a keyword argument ``rows_k`` or ``_rows_k``; (3)
    a string that names the record (its kind, those names, its module, its file, or the
    store's tables), however it is put together from constants; (4) a store read, or a store
    item made, by a kind not written out; (5) a store read's bound method kept, passed or
    returned (an alias or a partial); (6) a dynamic import, ``getattr`` or other opaque access
    that may reach any of these."""
    tree = ast.parse(source)
    found: Counter[str] = Counter()
    aliases: set[str] = set()
    makers: set[str] = set()

    def bound(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        args = fn.args
        names = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
        names |= {a.arg for a in (args.vararg, args.kwarg) if a is not None}
        return names | {
            n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
        }

    def visit(node: ast.AST, scope: str, local: frozenset[str] = frozenset()) -> None:
        for child in ast.iter_child_nodes(node):
            inner, mine = scope, local
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = child.name if scope == "<module>" else f"{scope}.{child.name}"
                if scope != "<module>" and inner.count(".") > 1:
                    inner = scope  # deeper nesting counts as its outer function's
                if not isinstance(child, ast.ClassDef):
                    mine = local | bound(child)  # a local of that name is not the record
            touches = _import_touches(child, package, aliases, makers)
            touches += _use_touches(child, node, (aliases, local))
            if isinstance(child, ast.Call):
                touches += _call_touches(child, makers)
                touches += sum(1 for k in child.keywords if k.arg in SHADOW_ROWS)
            if touches:
                found[scope] += touches
            visit(child, inner, mine)

    visit(tree, "<module>")
    return found


@functools.cache
def _cached_touches(source: str, package: str) -> tuple[tuple[str, int], ...]:
    """:func:`record_touches` once per source (the plants change one module each)."""
    return tuple(record_touches(source, package).items())


def package_touches(changed: Mapping[str, str] | None = None) -> dict[str, dict[str, int]]:
    """Every module's touches of the record outside its owners (``changed``: sources planted
    in place of the files')."""
    found: dict[str, dict[str, int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        name = str(path.relative_to(PACKAGE))
        if name in OWNERS:
            continue
        source = (changed or {}).get(name, path.read_text())
        package = ".".join(("snowlight", *path.relative_to(PACKAGE).parts[:-1]))
        touched = dict(_cached_touches(source, package))
        if touched:
            found[name] = dict(sorted(touched.items()))
    return found


PINNED: Final = {
    "predict/lines.py": {"<module>": 3, "Shadow._fit": 6, "read_kyy": 5, "store_past": 4},
    "predict/cli.py": {"<module>": 1, "make_pass": 1, "register": 1},
    "live/cli.py": {
        "RedactingFormatter.format": 1, "_pull": 1, "run_evidence": 2, "run_rehearse": 1,
    },
    "classify/parse.py": {"_vocabulary": 1},
    "live/guards.py": {"Rules.digest": 1},
    "live/publish.py": {
        "LiveHold.to_json_bytes": 1, "LivePublisher._take_hold": 1, "LivePublisher._upload": 1,
        "LivePublisher.publish": 1, "holds": 1,
    },
    "places/cli.py": {"_pinned": 2},
    "predict/alert_streams.py": {"Words.as_json": 1},
    "predict/drill.py": {"measure": 1},
    "predict/forecast_history.py": {"run_values": 1},
    "predict/frozen.py": {"DayEntry.as_json": 1},
    "predict/learn.py": {"_decide": 2},
    "predict/live_labels.py": {"label_live_day": 1},
    "predict/live_read.py": {"label_read_day": 2},
    "predict/live_switch.py": {"counts_line": 1},
    "predict/serve.py": {"Read.fields": 1, "_kept": 1, "read_of": 1},
    "predict/standing.py": {"build": 1, "guard": 9},
    "replays/cli.py": {"load_reader": 2, "replace_workers": 1},
    "schemas/predictions.py": {
        "Forecast._check_why": 2, "PastRecord": 1, "RecordReason": 1, "Why._check": 1,
    },
    "schemas/standing.py": {"StandingFile._check": 7},
    "schemas/stats.py": {"ReadAuditDay._check": 1},
    "social/post.py": {"Run.send": 1},
    "sources/stations/adapters.py": {"load_adapter": 1, "module_exists": 1},
    "sources/stations/archive.py": {"plan_follow": 1},
    "sources/stations/blox.py": {"_newsticker_xml": 1},
    "sources/stations/cbs_owned.py": {"_short_export": 1, "_short_newsticker": 1},
    "sources/stations/gray.py": {"parse_export": 1},
    "sources/stations/gray_files.py": {"_newsticker_xml": 1},
    "sources/stations/http.py": {"PoliteClient.robots_for": 1},
    "sources/stations/lockwood.py": {"parse": 1},
    "sources/stations/typed.py": {"entries_beside": 1, "read_typed": 1},
}  # fmt: skip
"""Every touch of the record outside its owners, by module and scope, pinned. The record's
reads: lines.py's import and the two names of its reads in :data:`lines.READS` (``<module>``),
its two named reads (``store_past`` imports the store's kind, names it and its past prefix's
reader; ``read_kyy`` its five calls), ``Shadow._fit``'s one R-KYY read (``self.kyy_store`` is
checked and opened, ``read_kyy(store_past(store), ...)`` reads it, and its private rows K
maker ``_rows_k`` is asked for and checked as lines.py's own), and cli.py's import
and its registering of the each-school record command. Everything else is a use that cannot
be told from the record by reading the code, each pinned where it is: the evidence command's
pull of the kind an operator names (live/cli.py ``_pull``, ``run_evidence``); a string equal
to the record's kind or ``RECORD`` that is a field of the served schema, a key of the served
document or a station page's tag (schemas, drill.py, sources/stations); a data field named
``held`` or ``items`` used as a value (live/publish.py, learn.py, live_read.py and the
others; cli.py's ``make_pass`` keeps the boundaries catalog's ``held``; the why's steps, WHY-
TRANSPARENT: serve.py's forecast step ``held`` state, standing.py's and schemas/standing.py's
``held``, ``record`` and ``record_full`` columns of the standing file (``record_full``: the
complete records from a state's calendar file, records-mo, never the evidence record), the
committed model's ``y``, ``yd`` and
``n`` read by ``getattr`` per class, and the why's ``held`` check); and ``getattr``,
``vars``, ``__dict__``, dynamic imports and ``held`` calls on other objects with a name not
written out."""


def test_only_lines_reads_the_record_and_only_through_its_named_reads() -> None:
    assert set(lines.READS) == {"R-P1", "R-P7P", "R-P7Y", "R-KYY"}
    assert lines.READS["R-KYY"] == ("store_past", "read_kyy")
    found = package_touches()
    assert found == PINNED
    assert {s for s in found["predict/lines.py"] if s != "<module>"} == {"Shadow._fit", *READ_NAMES}
    # the pass code reads nothing of the record: the shadow gets a store opener, not a pull
    passing = {
        scope: n for scope, n in found["predict/cli.py"].items()
        if scope.split(".")[0] in PASS_CODE
    }  # fmt: skip
    assert passing == {"make_pass": 1}  # the boundaries catalog's held field, a value


def test_the_shadow_holds_no_pull_of_the_record_and_the_frozen_reads_take_no_kind() -> None:
    """No field of lines.Shadow returns the record when called: R-KYY's way in is a store
    opener (``kyy_store``), and reading the record from a store takes its kind or
    ``store_past``, each counted. frozen.py's store reads take no kind (a flag picks one of its
    two kinds), so no caller can hand them the record's."""
    import dataclasses  # noqa: PLC0415
    import inspect  # noqa: PLC0415

    fields = {f.name: str(f.type) for f in dataclasses.fields(Shadow)}
    assert "kept" not in fields
    assert not hasattr(Shadow(), "kept")
    callables = {name for name, kind in fields.items() if "Callable" in kind}
    assert callables == {"kyy_store", "say"}
    assert "rows_k" not in fields  # R-KYY's rows go to lines.py's private maker alone
    assert "AbstractContextManager" in fields["kyy_store"]
    assert "Mapping[str, bytes]" not in "".join(fields[name] for name in callables)
    for read in (frozen._store_days, frozen.restore):
        params = inspect.signature(read).parameters
        assert "kind" not in params
        assert params["es"].kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(TypeError):
        frozen._store_days(None, date(2026, 11, 1), evidence.RECORD)  # type: ignore[arg-type, call-arg]


# --- the record's run-time guard (lead ruling LR-P6A-1) ------------------------------------

RECORD_JOB: Final = {"GITHUB_WORKFLOW": "each-school record", "GITHUB_RUN_ID": "79"}
PREDICT_JOB: Final = {"GITHUB_WORKFLOW": "predict", "GITHUB_RUN_ID": "78"}
NOW_STORE: Final = datetime(2026, 11, 16, 12, tzinfo=UTC)


def _record_api() -> Any:
    """A fake D1 whose two databases keep the record kind (SYNTHETIC): a day and R-KYY's past
    keys, as the record job keeps them."""
    from predict.test_frozen import FakeD1  # noqa: PLC0415

    api = FakeD1()
    offers = [evidence.Offer(evidence.RECORD, key, data) for key, data in _kept().items()]
    store = evidence.EvidenceStore(api, RECORD_JOB, lambda: NOW_STORE)
    assert all(r.kept == len(offers) for r in store.push(offers, (evidence.RECORD,)))
    return api


def _routes(store: evidence.EvidenceStore) -> dict[str, Callable[[], object]]:
    """Every way the critics named to ask the store for the record from outside lines.py."""
    database = store.databases()[0]
    fake: Any = database.api
    raw = fake.dbs[database.database()]  # the fake's own rows, below the store
    row = raw.execute("SELECT * FROM items WHERE kind = ?", (evidence.RECORD,)).fetchone()
    names = [c[0] for c in raw.execute("SELECT * FROM items").description]
    found = dict(zip(names, row, strict=True))
    forged = evidence.Item(
        kind=str(found["kind"]), key=str(found["key"]), sha256=str(found["sha256"]),
        bytes=int(found["bytes"]), packed=int(found["packed"]), parts=int(found["parts"]),
        codec=str(found["codec"]), kept_at=str(found["kept_at"]),
    )  # fmt: skip
    disguised = replace(forged, kind=evidence.FROZEN)
    read = store.pull
    later = functools.partial(store.pull, evidence.RECORD)
    shadow = Shadow(kyy_store=_opener(store))

    def opened() -> object:
        assert shadow.kyy_store is not None
        with shadow.kyy_store() as opened_store:
            return opened_store.pull(evidence.RECORD)

    return {
        "pull": lambda: store.pull(evidence.RECORD),
        "pull from the past keys": lambda: store.pull(evidence.RECORD, date.max),
        "bound pull": lambda: read("rec" + "ord"),
        "partial": later,
        "pull_all": lambda: store.pull_all(evidence.RECORD),
        "versions": lambda: store.versions(evidence.RECORD),
        "held": lambda: store.held([evidence.RECORD]),
        "the capability taken out": lambda: store.pull(evidence.RECORD, capability=lines._READ),
        "items": lambda: database.items([evidence.RECORD]),
        "items beside another kind": lambda: database.items([evidence.FROZEN, evidence.RECORD]),
        "database held": lambda: database.held([evidence.RECORD]),
        "read(item)": lambda: database.read(forged),
        "parts(item)": lambda: database.parts(forged),
        "read(item) named another kind": lambda: database.read(disguised),
        "a read sent past the store": lambda: database.run([(evidence._ITEMS, (evidence.RECORD,))]),
        "shadow opener": opened,
        "store_past": lambda: lines.store_past(store, lines._READ),
        "store_past with no capability": lambda: lines.store_past(store, None),
    }


def _opener(store: evidence.EvidenceStore) -> Callable[[], Any]:
    @contextmanager
    def opened() -> Iterator[evidence.EvidenceStore]:
        yield store

    return opened


ROUTES: Final = (
    "pull", "pull from the past keys", "bound pull", "partial", "pull_all", "versions", "held",
    "the capability taken out", "items", "items beside another kind", "database held",
    "read(item)", "parts(item)", "read(item) named another kind", "a read sent past the store",
    "shadow opener", "store_past", "store_past with no capability",
)  # fmt: skip


@pytest.mark.parametrize("route", ROUTES)
def test_every_read_of_the_record_from_outside_lines_raises(route: str) -> None:
    """LR-P6A-1: the store refuses the record kind at run time to every route a critic named
    (a planted record kept in both databases), whatever job's store it is."""
    api = _record_api()
    for env in (PREDICT_JOB, RECORD_JOB):
        routes = _routes(evidence.EvidenceStore(api, env, lambda: NOW_STORE))
        assert set(routes) == set(ROUTES)
        with pytest.raises(evidence.RecordRefusedError):
            routes[route]()


class _LookAlike(str):
    """A str subclass that denies being any kind (critic r5 X1)."""

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        return False

    def __ne__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return str.__hash__(self)


def test_a_kind_that_is_not_exactly_a_str_is_refused() -> None:
    """R5-S1: the guard refuses any kind that is not exactly a str, so a look-alike of the
    record's kind reads nothing, from any store read, and a plain str of the same kind is
    still refused."""
    store = evidence.EvidenceStore(_record_api(), PREDICT_JOB, lambda: NOW_STORE)
    database = store.databases()[0]
    sneaky = _LookAlike(evidence.RECORD)
    assert sneaky not in (evidence.RECORD,)  # the look-alike gets past an `in` check
    reads: list[Callable[[], object]] = [
        lambda: store.pull(sneaky),
        lambda: store.pull(sneaky, date.max),
        lambda: store.pull_all(sneaky),
        lambda: store.versions(sneaky),
        lambda: store.held([sneaky]),
        lambda: database.items([sneaky]),
        lambda: database.held([sneaky]),
        lambda: store.pull(_LookAlike(evidence.FROZEN)),
    ]
    for read in reads:
        with pytest.raises(evidence.RecordRefusedError):
            read()
    assert store.pull(evidence.FROZEN) == {}  # a plain str of another kind reads as before
    with pytest.raises(evidence.RecordRefusedError):
        store.pull(str(sneaky))


RUN_PLANTS: Final = ("serve", "learn", "anchor")


@pytest.mark.parametrize("module", RUN_PLANTS)
def test_no_pass_module_hands_the_shadow_a_consumer_of_r_kyy_s_rows(
    module: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LR-P6A-6, at run time: the critic's plant, run as code of serve.py, learn.py and
    anchor.py (a planted record kept in the store, SYNTHETIC), raises: the shadow takes no
    consumer of R-KYY's rows. Through lines.py's private maker replaced from that module, the
    fit refuses it: the consumer gets nothing and no record row is read."""
    import importlib  # noqa: PLC0415

    namespace = vars(importlib.import_module(f"snowlight.predict.{module}"))
    store = evidence.EvidenceStore(_record_api(), PREDICT_JOB, lambda: NOW_STORE)
    got: list[object] = []
    plant = (
        "lines.Shadow(folder=folder, kyy_store=opener, rows_k=got.append, loaded=True)"
        ".refresh(now, anchor)"
    )
    now = datetime(2026, 11, 16, 20, tzinfo=UTC)
    names = {"lines": lines, "opener": _opener(store), "got": got, "now": now}
    names |= {"anchor": an_anchor(), "folder": tmp_path / "es"}
    with pytest.raises(TypeError, match="rows_k"):
        eval(plant, namespace | names)  # noqa: S307 - the plant, as that module's code
    maker = eval("lambda: lambda i: got.append(i) or []", namespace | names)  # noqa: S307
    assert maker.__module__ == f"snowlight.predict.{module}"
    monkeypatch.setattr(lines, "_rows_k", maker)
    said: list[str] = []
    shadow = Shadow(folder=tmp_path / "es", kyy_store=_opener(store), say=said.append)
    shadow.ledger = live_world(0.3, units=60, groups=200)
    shadow.loaded = True
    with record_rows_read(monkeypatch) as read:
        assert shadow.refresh(now, an_anchor())
    assert got == []
    assert read == []
    assert "m5y off: rows K refused: not snowlight.predict.lines's own" in said[0]


def test_the_capability_is_one_object_made_once_never_copied_or_pickled() -> None:
    import copy  # noqa: PLC0415
    import pickle  # noqa: PLC0415

    with pytest.raises(TypeError):
        lines._RecordRead()
    with pytest.raises(TypeError):
        type(lines._READ)()
    assert copy.copy(lines._READ) is lines._READ
    assert copy.deepcopy(lines._READ) is lines._READ
    with pytest.raises(TypeError):
        pickle.dumps(lines._READ)
    assert not hasattr(lines._READ, "__dict__")


def test_the_frozen_reads_raise_when_pointed_at_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """frozen._store_days and frozen.restore take no kind (a flag picks one of frozen.py's two);
    pointed at the record all the same, by planting its kind as theirs, they raise."""
    api = _record_api()
    store = evidence.EvidenceStore(api, PREDICT_JOB, lambda: NOW_STORE)
    assert frozen._store_days(store, date(2026, 11, 1)) == {}  # its own kinds: nothing kept
    for name in ("FROZEN", "FROZEN_ES"):
        with monkeypatch.context() as planted:
            planted.setattr(evidence, name, evidence.RECORD)  # frozen.py reads it at the call
            with pytest.raises(evidence.RecordRefusedError):
                frozen._store_days(store, date(2026, 11, 1), es=name == "FROZEN_ES")
            with pytest.raises(evidence.RecordRefusedError):
                frozen.restore(tmp_path / "frozen", store, NOW_STORE, es=name == "FROZEN_ES")
    with pytest.raises(TypeError):
        frozen._store_days(store, date(2026, 11, 1), kind=evidence.RECORD)  # type: ignore[call-arg]


def test_lines_reads_r_kyy_s_past_keys_with_its_capability_and_nothing_else() -> None:
    """The one admitted read: Shadow._fit's store_past, from lines.py with lines.py's
    capability, reads the past keys alone (never a day of the record)."""
    store = evidence.EvidenceStore(_record_api(), PREDICT_JOB, lambda: NOW_STORE)
    read = vars(lines)["store_past"]
    found = eval("read(store, _READ)", vars(lines) | {"read": read, "store": store})  # noqa: S307
    assert set(found) == {k for k in _kept() if k.startswith(record.PAST_PREFIX)}


@contextmanager
def record_rows_read(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """The keys of every record-kind item whose bytes are read while the block runs: every
    store read of an item's bytes goes through evidence.unpack."""
    keys: list[str] = []
    unpack = evidence.unpack

    def watched(item: evidence.Item, parts: Sequence[str]) -> bytes:
        if item.kind == evidence.RECORD:
            keys.append(item.key)
        return unpack(item, parts)

    with monkeypatch.context() as watching:
        watching.setattr(evidence, "unpack", watched)
        yield keys


def _with_store_shadow(api: Any) -> Callable[[Path | None, Clock, MemoryHost], cli.Pass]:
    """The due shadow (the nightly fit runs in the passes) with R-KYY's store the planted one."""

    def make(folder: Path | None, clock: Clock, host: MemoryHost) -> cli.Pass:
        run = _with_due_shadow(folder, clock, host)
        if isinstance(run.es, Shadow):
            store = evidence.EvidenceStore(api, PREDICT_JOB, lambda: NOW_STORE)
            run.es = replace(run.es, kyy_store=_opener(store))
        return run

    return make


def test_serve_learn_and_anchor_passes_read_no_record_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LR-P6A-1, at run time: with the record kept in the store (SYNTHETIC), the serve passes
    (the frozen record and the nightly fit in them), the predict job's evidence steps, a learn
    run and the anchor read no record row; the one record read is the nightly fit's R-KYY pull
    of the past keys."""
    from predict.test_frozen import _passes  # noqa: PLC0415

    monkeypatch.setattr(lines, "_rows_k", lines_rows_k([]))
    from predict.test_learn import Host, learn_run  # noqa: PLC0415
    from snowlight.predict.anchor_labels import serving_anchor  # noqa: PLC0415
    from snowlight.predict.live_labels import NoLiveSource  # noqa: PLC0415

    api = _record_api()
    past = {k for k in _kept() if k.startswith(record.PAST_PREFIX)}
    with record_rows_read(monkeypatch) as read:
        off = _passes(adjusting_pass, tmp_path / "off")
        assert read == []
        on = _passes(_with_store_shadow(api), tmp_path / "on")
        assert set(read) == past  # the fit's R-KYY pull, past keys only
        assert on == off
        read.clear()
        store = evidence.EvidenceStore(api, PREDICT_JOB, lambda: NOW_STORE)
        cli.restore_frozen(store, tmp_path / "on", NOW_STORE)
        assert cli.keep_evidence(store, {}, {}, NOW_STORE, frozen_folder=tmp_path / "on") == 0
        cli.note_frozen(store, tmp_path / "on", NOW_STORE)
        now = world.utc("2026-10-20T15:00:00")
        assert cli.learn_once(learn_run(Host(), NoLiveSource(), now, world.CONFIG)) == 0
        serving_anchor(world.CONFIG, world.model(), folder=tmp_path / "reads")
        assert read == []
    kept = json.loads((tmp_path / "on" / "es" / lines.FIT_NAME).read_bytes())
    assert kept["m5y"]["why"] != "R-KYY's pull failed (RecordRefusedError)"


def _planted(name: str, change: Callable[[str], str]) -> dict[str, dict[str, int]]:
    planted = change((PACKAGE / name).read_text())
    assert planted != (PACKAGE / name).read_text(), "the plant did not apply"
    return package_touches({name: planted})


def _add(code: str) -> Callable[[str], str]:
    return lambda s: s + "\n\n" + code + "\n"


def _swap(old: str, new: str) -> Callable[[str], str]:
    def change(s: str) -> str:
        assert s.count(old) == 1, old
        return s.replace(old, new)

    return change


_FREEZE_PATH = "        self.load()\n        if self.own is None:\n            return []"
_FREEZE_STEP = "    if run.frozen is None:\n        return\n    try:\n        ugcs"


@pytest.mark.parametrize(
    ("name", "change"),
    [
        # A: a plain import in a serving module
        ("predict/serve.py", _add("from snowlight.predict import record")),
        # B: a serving module pulls the record kind from the store
        (
            "predict/serve.py",
            _add(
                "from snowlight.live.evidence import RECORD\n\n\n"
                "def sneak(store):\n    return store.pull(RECORD)"
            ),
        ),
        # C: a module-level alias of a record reader in lines.py
        ("predict/lines.py", _add("_SNEAK = record_kind.kept_rows")),
        # D: an extra pull inside the allowed store_past
        (
            "predict/lines.py",
            _swap(
                "    found: dict[str, bytes] = store.pull(RECORD, date.max, capability=capability)",
                "    store.pull(RECORD, date.min)\n"
                "    found: dict[str, bytes] = store.pull(RECORD, date.max, capability=capability)",
            ),
        ),
        # E: a relative import in the anchor
        ("predict/anchor.py", _add("from . import record as _r")),
        # F: cli.py's pass code reads the record
        (
            "predict/cli.py",
            _swap(
                '    if config.each_school.shadow != "on":\n        return None',
                '    if config.each_school.shadow != "on":\n        return None\n'
                "    record.kept_rows({}, None)",
            ),
        ),
        # G: an attribute read of the store's kind anywhere
        ("predict/anchor.py", _add("def sneak(evidence):\n    return evidence.RECORD")),
        # H: a serving module calls lines.py's R-KYY pull
        (
            "predict/serve.py",
            _add(
                "def sneak(store):\n    from snowlight.predict import lines as _l\n"
                "    return _l.store_past(store)"
            ),
        ),
        # I: a serving module pulls the kind by its string
        ("predict/serve.py", _add("def sneak(store):\n    return store.pull('record')")),
        # J: a getattr of the store's kind by a built name
        (
            "predict/anchor.py",
            _add(
                "def sneak(store):\n    from snowlight.live import evidence as e\n"
                "    return store.pull(getattr(e, 'REC' + 'ORD'), None)"
            ),
        ),
        # K: lines.py's freeze path calls R-KYY's pull
        (
            "predict/lines.py",
            _swap(
                _FREEZE_PATH,
                _FREEZE_PATH.replace(
                    "self.load()\n", "self.load()\n        store_past(self.kyy_store)\n"
                ),
            ),
        ),
        # K2: lines.py's freeze path keeps the store opener
        (
            "predict/lines.py",
            _swap(
                _FREEZE_PATH,
                _FREEZE_PATH.replace(
                    "self.load()\n", "self.load()\n        _sneak = self.kyy_store\n"
                ),
            ),
        ),
        # L: a learning module calls lines.py's R-KYY reader
        (
            "predict/learn.py",
            _add(
                "def sneak(kept):\n    from snowlight.predict.lines import read_kyy\n"
                "    return read_kyy(kept, None)"
            ),
        ),
        # M: a dynamic import of the record module by a built name
        (
            "predict/serve.py",
            _add(
                "def sneak():\n    import importlib\n"
                "    return importlib.import_module('snowlight.predict.rec' + 'ord').kept_rows"
            ),
        ),
        # N: a module constant holding the kind's string, pulled by name
        (
            "predict/anchor.py",
            _add("SNEAK = 'record'\n\n\ndef sneak(store):\n    return store.pull(SNEAK)"),
        ),
        # O: a pull of a kind held in a variable
        ("predict/serve.py", _add("def sneak(store, kind):\n    return store.held((kind,))")),
        # P: a serving module opens the shadow's store (round 3's shadow.kept())
        ("predict/serve.py", _add("def sneak(shadow):\n    return shadow.kyy_store()")),
        # P2: cli.py reads through the pass's shadow (round 3's run.es.kept())
        ("predict/cli.py", _add("def _record_sneak(run):\n    return run.es.kyy_store()")),
        # P10: cli.py's pass code opens the shadow's store
        (
            "predict/cli.py",
            _swap(
                _FREEZE_STEP,
                _FREEZE_STEP.replace(
                    "    try:\n", "    run.es.kyy_store and run.es.kyy_store()\n    try:\n"
                ),
            ),
        ),
        # P9: a getattr of the shadow's store opener in lines.py
        (
            "predict/lines.py",
            _swap(
                _FREEZE_PATH,
                _FREEZE_PATH.replace(
                    "self.load()\n", "self.load()\n        getattr(self, 'kyy_store')\n"
                ),
            ),
        ),
        # R: lines.Shadow.lines reaches the opener through another name
        (
            "predict/lines.py",
            _swap(
                _FREEZE_PATH,
                _FREEZE_PATH.replace(
                    "self.load()\n", "self.load()\n        me = self\n        me.kyy_store()\n"
                ),
            ),
        ),
        # Q: the store's databases read by item, the kind by its string
        (
            "predict/serve.py",
            _add(
                "def sneak(store):\n"
                "    return [d.read(i) for d in store.databases for i in d.items(['record'])]"
            ),
        ),
        # Q2: the same with the kinds in a variable
        (
            "predict/serve.py",
            _add(
                "def sneak(store, kinds):\n"
                "    return [d.read(i) for d in store.databases for i in d.items(kinds)]"
            ),
        ),
        # Q3: a store item made by a kind not written out, then read
        (
            "predict/serve.py",
            _add(
                "def sneak(d, kind, key, sha):\n    from snowlight.live import evidence\n"
                "    return d.read(evidence.Item(kind, key, sha, 0, 0, 1))"
            ),
        ),
        # Q4: the store's own statement, by hand
        (
            "predict/serve.py",
            _add(
                "def sneak(d, kind):\n"
                "    return d.run([('SELECT key, sha256 FROM items WHERE kind = ?', (kind,))])"
            ),
        ),
        # P1: frozen.py's store read handed the record's kind (now a TypeError as well)
        (
            "predict/serve.py",
            _add(
                "def sneak(store, since):\n    from snowlight.predict import frozen\n"
                "    return frozen._store_days(store, since, 'record')"
            ),
        ),
        # P1b: frozen.restore handed the record's kind
        (
            "predict/learn.py",
            _add(
                "def sneak(folder, store, now):\n    from snowlight.predict import frozen\n"
                "    return frozen.restore(folder, store, now, 'record')"
            ),
        ),
        # P4: a bound store read kept under another name
        (
            "predict/anchor.py",
            _add("def sneak(store):\n    read = store.pull\n    return read('record', None)"),
        ),
        # P4c: the same with the kind in a variable
        (
            "predict/anchor.py",
            _add("def sneak(store, kind):\n    read = store.pull\n    return read(kind)"),
        ),
        # P4b: a partial of a store read
        (
            "predict/serve.py",
            _add(
                "def sneak(store):\n    import functools\n"
                "    return functools.partial(store.pull, 'record')()"
            ),
        ),
        # P4d: a partial of a store read with the kind in a variable
        (
            "predict/serve.py",
            _add(
                "def sneak(store, kind):\n    import functools\n"
                "    return functools.partial(store.pull_all, kind)()"
            ),
        ),
        # P4e: the bound method's own call
        ("predict/serve.py", _add("def sneak(store, kind):\n    return store.pull.__call__(kind)")),
        # P4f: the class's function given the store
        (
            "predict/serve.py",
            _add("def sneak(store, kind):\n    return type(store).pull(store, kind)"),
        ),
        # P4g: a read with its arguments spread
        ("predict/serve.py", _add("def sneak(store, asked):\n    return store.pull(**asked)")),
        # P8: the record's file by its path
        (
            "predict/serve.py",
            _add(
                "def sneak():\n    import pathlib\n"
                "    return pathlib.Path('out/internal/predict/record.parquet').read_bytes()"
            ),
        ),
        # P8b: the record's yearly counts file by its name, built from pieces
        (
            "predict/serve.py",
            _add(
                "def sneak(folder):\n    import pathlib\n"
                "    return pathlib.Path(folder, 'record-' + 'counts.parquet').read_bytes()"
            ),
        ),
        # S1: the kind's string built from pieces
        ("predict/serve.py", _add("def sneak(store):\n    return store.pull('rec' + 'ord')")),
        ("predict/serve.py", _add("def sneak(store):\n    return store.pull(f\"{'rec'}ord\")")),
        (
            "predict/serve.py",
            _add("def sneak(store):\n    return store.pull(''.join(['rec', 'ord']))"),
        ),
        # S2: an attribute reached by a name not written out
        ("predict/serve.py", _add("def sneak(shadow, name):\n    return vars(shadow)[name]()")),
        (
            "predict/serve.py",
            _add("def sneak(shadow):\n    return shadow.__dict__['kyy' + '_store']()"),
        ),
        # L (critic r5, LR-P6A-6): a pass module hands the shadow its own consumer of R-KYY's
        # rows and calls the public refresh, from serve.py, learn.py and anchor.py
        *(
            (
                f"predict/{name}.py",
                _add(
                    "def sneak(opener, now, anchor):\n    from snowlight.predict import lines\n"
                    "    got = []\n"
                    "    lines.Shadow(kyy_store=opener, rows_k=got.append).refresh(now, anchor)\n"
                    "    return got"
                ),
            )
            for name in ("serve", "learn", "anchor")
        ),
        # M: the same, through lines.py's private rows K maker replaced from a pass module
        *(
            (
                f"predict/{name}.py",
                _add(
                    "def sneak(got):\n    from snowlight.predict import lines\n"
                    "    lines._rows_k = lambda: got.append"
                ),
            )
            for name in ("serve", "learn", "anchor")
        ),
    ],
)
def test_a_planted_extra_read_of_the_record_fails_the_allowlist(
    name: str, change: Callable[[str], str]
) -> None:
    planted = _planted(name, change)
    assert planted != PINNED


# --- the record's parts per live row (anchor_labels) ------------------------------------------


def test_the_record_s_parts_per_live_row_are_0_and_every_learned_value_is_the_same() -> None:
    from snowlight.predict import anchor  # noqa: PLC0415

    labels = _labels(date(2026, 11, 13), [("2900001", "no_school"), ("2900002", "unnamed")])
    assert anchor_labels.row_parts(labels) == (0.0, 0.0)
    assert anchor_labels.row_parts(labels, {"own": {}}) == (0.0, 0.0)
    assert anchor_labels.row_parts(labels, {"own": {"snow_warning|2900001": 0.4}}) == (0.4, 0.0)
    config = PredictConfig.load()
    settings = anchor.AnchorSettings.of(config)
    from snowlight.predict.exposure import Exposure  # noqa: PLC0415

    empty = Exposure((), {}, {}, {}, {}, {})
    before = anchor.fit(settings, empty, labels, {})
    anchor_labels.row_parts(labels)
    after = anchor.fit(settings, empty, labels, {})
    assert {k: (f.alpha, f.q, f.rows) for k, f in before.fits.items()} == {
        k: (f.alpha, f.q, f.rows) for k, f in after.fits.items()
    }


# --- the no-change proof (8.1) ----------------------------------------------------------------


def arms_moved(es: bytes, day: bytes, by: float = 0.01) -> int:
    """How many of a shadow arms day's M5o chances are more than ``by`` from the frozen
    district day's unrounded chance (``pr``) of the same freeze, zone and district: the arms
    moved, so the no-change proof ran with them moving."""
    base = {
        (row.freeze, row.zone, row.leaid): row.p_raw
        for row in frozen.parse_day(day).rows
        if row.p_raw is not None
    }
    moved = 0
    for found in frozen.parse_es(es):
        for leaid, chances in found.chances.items():
            p = base.get((found.freeze, found.zone, leaid))
            m5o = chances[found.arms.index("m5o")]
            moved += int(p is not None and m5o is not None and abs(m5o - p) > by)
    return moved


def districts_moved(es: bytes, day: bytes, by: float = 0.01) -> set[str]:
    """The districts with an M5o chance more than ``by`` from the frozen district day's
    unrounded chance of the same freeze and zone in some freeze (:func:`arms_moved`, counted
    by district)."""
    base = {
        (row.freeze, row.zone, row.leaid): row.p_raw
        for row in frozen.parse_day(day).rows
        if row.p_raw is not None
    }
    found: set[str] = set()
    for line in frozen.parse_es(es):
        for leaid, chances in line.chances.items():
            p = base.get((line.freeze, line.zone, leaid))
            m5o = chances[line.arms.index("m5o")]
            if p is not None and m5o is not None and abs(m5o - p) > by:
                found.add(leaid)
    return found


def _with_shadow(folder: Path | None, clock: Clock, host: MemoryHost) -> cli.Pass:
    run = adjusting_pass(folder, clock, host)
    if folder is not None:
        leaids = world.directory().district_ids
        own = OwnFit(1.0, {leaid: (0.8 if k % 2 else -0.8, 0.05) for k, leaid in enumerate(leaids)})
        at = datetime.combine(fa_test.DAY - timedelta(days=1), time(19, 31), UTC)
        run.es = lines.with_fit(Shadow(folder=folder / "es", frozen_folder=folder), own, at=at)
    return run


def _with_due_shadow(folder: Path | None, clock: Clock, host: MemoryHost) -> cli.Pass:
    """The shadow arms with no fit yet: the nightly fit is due and runs during the passes, from
    a labeled day, its ledger and a store that fails."""
    run = adjusting_pass(folder, clock, host)
    if folder is not None:
        from snowlight.predict import anchor  # noqa: PLC0415

        def failing() -> Any:
            raise OSError("planted: the store is down")

        reads = write_reads(
            folder.parent / f"reads-{folder.name}",
            fa_test.DAY - timedelta(days=1),
            [(leaid, "no_school") for leaid in world.directory().district_ids],
        )
        run.es = Shadow(
            folder=folder / "es", reads=reads, frozen_folder=folder, kyy_store=failing,
            class_of=anchor.AnchorSettings.of(PredictConfig.load()).class_of,
        )  # fmt: skip
    return run


def test_every_served_chance_and_byte_is_the_same_while_the_nightly_fit_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from predict.test_frozen import _passes  # noqa: PLC0415

    monkeypatch.setattr(lines, "_rows_k", lines_rows_k([]))

    on = _passes(_with_due_shadow, tmp_path / "on")
    off = _passes(adjusting_pass, tmp_path / "off")
    assert on == off
    key = fa_test.DAY.isoformat()
    assert (
        frozen.day_path(tmp_path / "on", key).read_bytes()
        == frozen.day_path(tmp_path / "off", key).read_bytes()
    )
    kept = json.loads((tmp_path / "on" / "es" / lines.FIT_NAME).read_bytes())
    assert kept["computed"].startswith("2026-01-14")  # the fit ran in a pass...
    assert kept["m5y"]["why"] == "R-KYY's pull failed (OSError)"  # ...its store down


def test_every_served_chance_and_byte_is_the_same_with_p6a_on(tmp_path: Path) -> None:
    """Each-school 8.1: with the shadow arms on (a fit whose parts move every district), every
    public file of every pass and the frozen district day are the same byte for byte as with
    them off; only the folder ``es/`` is new."""
    from predict.test_frozen import _passes  # noqa: PLC0415

    on = _passes(_with_shadow, tmp_path / "on")
    off = _passes(adjusting_pass, tmp_path / "off")
    assert on == off
    key = fa_test.DAY.isoformat()
    assert (
        frozen.day_path(tmp_path / "on", key).read_bytes()
        == frozen.day_path(tmp_path / "off", key).read_bytes()
    )
    es = frozen.day_path(tmp_path / "on" / "es", key).read_bytes()
    moved = [f for f in frozen.parse_es(es) if f.chances]
    assert moved
    day = frozen.day_path(tmp_path / "on", key).read_bytes()
    assert arms_moved(es, day) > 0  # the planted fit stays: its own part moves the chances
    assert not (tmp_path / "off" / "es").exists()
    assert json.loads((tmp_path / "on" / "es" / "index.json").read_bytes())["days"]
    assert TIMES


def test_the_shadow_refreshes_after_the_freeze_so_no_frozen_day_waits_on_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pass's freeze is written first, then the shadow's take-up and nightly fit; a freeze
    that fails still lets the shadow refresh, and a refresh that raises is one warning."""
    from types import SimpleNamespace  # noqa: PLC0415

    order: list[str] = []

    class Refreshing(Shadow):
        def refresh(self, now: datetime, anchor: Any = None) -> bool:  # noqa: ARG002
            order.append("refresh")
            if failing_refresh:
                raise RuntimeError("planted")
            return True

    def record(_inputs: Any, _folder: Path) -> list[Any]:
        order.append("record")
        if failing_record:
            raise RuntimeError("planted")
        return []

    monkeypatch.setattr(frozen, "PassInputs", lambda **kw: kw)
    monkeypatch.setattr(frozen, "record", record)
    for name in ("live_score_sha256", "frozen_shadows", "frozen_heads", "live_heads_ups"):
        monkeypatch.setattr(cli, name, lambda *_args: ())
    made = SimpleNamespace(generated_at=datetime(2026, 11, 16, 19, 35, tzinfo=UTC))
    built = SimpleNamespace(
        made=made, after=None, forecasts=None, noted=None, adjusted=None, maker=None
    )
    run = SimpleNamespace(
        frozen=Path("unused"), es=Refreshing(), anchor=None, config=SimpleNamespace(
            serve=SimpleNamespace(elevation_margin_feet=0)
        ), switch=None, ugc_index=lambda _d: None, school_heights=lambda _d: None,
    )  # fmt: skip
    for failing_record, failing_refresh in ((False, False), (True, False), (False, True)):
        order.clear()
        cli._record_frozen(run, built, None, None, None, (), None, None)  # type: ignore[arg-type]
        assert order == ["record", "refresh"], (failing_record, failing_refresh)


def test_a_shadow_that_cannot_be_made_is_none_with_one_warning(capsys: Any) -> None:
    def broken() -> Shadow:
        raise KeyError("planted")

    assert cli.shadow_or_none(broken) is None
    out = capsys.readouterr()
    lines_said = [line for line in (out.out + out.err).splitlines() if line]
    assert len(lines_said) == 1
    assert lines_said[0].endswith("predict lines: the shadow arms: KeyError: none this run")


def test_a_kept_fit_of_the_wrong_shape_leaves_every_pass_and_the_district_day(
    tmp_path: Path, capsys: Any
) -> None:
    """A kept ``fit.json`` of the right schema and the wrong shape: every pass exits 0
    (:func:`predict.test_frozen._finished_with` holds it), the district day is the same byte for
    byte, and the shadow says one line (the run has no anchor: the fit waits a window)."""
    from predict.test_frozen import _finished_with  # noqa: PLC0415

    plain = _finished_day(tmp_path / "plain")
    capsys.readouterr()
    folder = tmp_path / "es" / "es"
    folder.mkdir(parents=True)
    body = {"schema": lines.FIT_SCHEMA, "units": [], "spread": 0.0, "rows": 0, "groups": 0}
    (folder / lines.FIT_NAME).write_text(json.dumps({**body, "computed": "2026-01-06T19:31:00"}))
    shadow = _shadow(tmp_path / "es", folder=folder)
    said: list[str] = []
    shadow.say = said.append
    data, out = _finished_with(tmp_path / "es", shadow, capsys)
    assert data == plain
    assert not any("nothing frozen this pass" in line for line in out)
    assert len(said) == 1
    assert said[0].startswith("predict lines: the nightly fit: ")


# --- New York's A-8 rows in the record (records-ny, edition 1) -----------------------------------

NY = [f"36{n:05d}" for n in range(30)]


def _ny_keys() -> dict[str, bytes]:
    """New York past rows as the records-ny build writes them (synthetic): its LEAIDs, the
    form's codes (weather WX, a declared emergency SOE), dated days and yearly counts inside
    R-KYY's window, so only the state and the code keep them out."""
    days = [
        record.PastDay(
            version=1, day=date(2024, 12, 2) + timedelta(days=k % 5), unit=u, weather=None,
            klass="unknown", after=None, after_weather=None, situation=None, call=Call.CLOSED,
            source_kind=SourceKind.PAST_RECORDS, source_complete=False, closings_only=True,
            scope=Scope.WHOLE if k % 3 else Scope.SHARE,
            cause=Cause.WEATHER if k % 2 else Cause.ANY, weather_day=bool(k % 2),
            fit_usable=False, reasons=(), tropical=None, sources=("ny-a8-2025-26",),
            code="WX" if k % 2 else "SOE",
        )
        for k, u in enumerate(NY)
    ]  # fmt: skip
    counts = [
        record.YearCount(
            version=1, unit=u, year=year, code=code, days=1 + k % 4, not_weather=0,
            unconfirmed=0, source_kind=SourceKind.PAST_RECORDS, sources=("ny-a8-2025-26",),
            covid=False, disaster=None,
        )
        for k, u in enumerate(NY)
        for year in ("2021-22", "2022-23", "2023-24", "2024-25")
        for code in ("WX", "SOE")
    ]  # fmt: skip
    return {
        "past/ny-a8-2025-26/v1/days": record.lines_bytes(days, "t"),
        "past/ny-a8-2025-26/v1/counts": record.lines_bytes(counts, "t"),
        "past/ny-a8-2013-14/v1/days": b"",  # a file with no written row: an empty key
        "past/ny-a8-2013-14/v1/counts": b"",
    }


def test_new_york_past_rows_change_no_shadow_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """records-ny test 18: New York's rows planted in the record move no part of either
    shadow arm: R-KYY reads the same, and M5o's and M5y's fits, every line and the kept fit
    are the same byte for byte (no A-8 row reaches either arm)."""
    now = datetime(2026, 11, 16, 20, tzinfo=UTC)
    exposure = dict.fromkeys([*KY, *NY], 10.0)
    plain_kept, ny_kept = _kept(), {**_kept(), **_ny_keys()}
    assert lines.read_kyy(ny_kept, SERVED) == lines.read_kyy(plain_kept, SERVED)
    tendency = lines.fit_tendency(dict(lines.read_kyy(plain_kept, SERVED).counts), exposure)
    monkeypatch.setattr(lines, "_rows_k", lines_rows_k(_rows_k(tendency)))
    ledger = live_world(0.3, units=60, groups=200)

    def fitted(name: str, kept: Mapping[str, bytes]) -> Shadow:
        saved = _shadow(tmp_path / name, ledger=list(ledger), loaded=True)
        saved.save()
        shadow = _shadow(tmp_path / name, kyy_store=_store_of(lambda: kept), exposure=exposure)
        shadow.load()
        assert shadow.refresh(now, an_anchor())
        return shadow

    plain, planted = fitted("plain", plain_kept), fitted("planted", ny_kept)
    assert plain.own is not None
    assert plain.ky is not None
    assert plain.ky.units  # M5y moves Kentucky's units, so a New York row would show
    assert _untimed(planted.own) == _untimed(plain.own)
    assert _untimed(planted.ky) == _untimed(plain.ky)
    assert not any(u in plain.ky.units for u in NY)
    rows = [_row(u, 0.3) for u in (*KY[:5], *NY[:5])]
    assert json.dumps(planted.lines(rows)) == json.dumps(plain.lines(rows))
    assert _untimed(json.loads((tmp_path / "planted" / "es" / lines.FIT_NAME).read_bytes())) == (
        _untimed(json.loads((tmp_path / "plain" / "es" / lines.FIT_NAME).read_bytes()))
    )


def _w_keys(units: Sequence[str]) -> dict[str, bytes]:
    """Past rows of Kentucky's own weather code ``W`` (weather days, inside R-KYY's window) for
    ``units``, in a New York file's keys: only the unit's state can keep them out."""
    days = [
        record.PastDay(
            version=1, day=date(2024, 12, 2) + timedelta(days=k % 5), unit=u, weather=None,
            klass="unknown", after=None, after_weather=None, situation=None, call=Call.CLOSED,
            source_kind=SourceKind.PAST_RECORDS, source_complete=False, closings_only=True,
            scope=Scope.WHOLE, cause=Cause.WEATHER, weather_day=True, fit_usable=False,
            reasons=(), tropical=None, sources=("ny-a8-2025-26",), code="W",
        )
        for k, u in enumerate(units)
    ]  # fmt: skip
    counts = [
        record.YearCount(
            version=1, unit=u, year=year, code="W", days=1 + k % 4, not_weather=0,
            unconfirmed=0, source_kind=SourceKind.PAST_RECORDS, sources=("ny-a8-2025-26",),
            covid=False, disaster=None,
        )
        for k, u in enumerate(units)
        for year in ("2021-22", "2022-23", "2023-24", "2024-25")
    ]  # fmt: skip
    return {
        "past/ny-a8-2025-26/v1/days": record.lines_bytes(days, "t"),
        "past/ny-a8-2025-26/v1/counts": record.lines_bytes(counts, "t"),
    }


def test_new_york_rows_of_code_w_are_kept_out_of_r_kyy_by_their_state_alone() -> None:
    """records-ny fix r1 (S5): a New York row of Kentucky's own code ``W`` that is a weather
    day leaves R-KYY the same, while the same rows under Kentucky units would move it, so the
    state filter alone keeps New York out (test 18's rows differ in both state and code)."""
    plain = _kept()
    assert lines.read_kyy({**plain, **_w_keys(NY)}, SERVED) == lines.read_kyy(plain, SERVED)
    control = lines.read_kyy({**plain, **_w_keys([f"21{n:05d}" for n in range(90, 95)])}, SERVED)
    base = lines.read_kyy(plain, SERVED)
    assert control.counts != base.counts
    assert control.dated != base.dated


def _untimed(value: Any) -> Any:
    """``value`` with each fit's wall time (``seconds``) left out: the one field that is not a
    function of the rows."""
    if isinstance(value, dict):
        return {k: _untimed(v) for k, v in value.items() if k != "seconds"}
    if isinstance(value, list):
        return [_untimed(v) for v in value]
    if hasattr(value, "seconds") and hasattr(value, "__dataclass_fields__"):
        return replace(value, seconds=0.0)
    return value


def _with_ny_record(folder: Path | None, clock: Clock, host: MemoryHost) -> cli.Pass:
    """The shadow arms with the nightly fit due, reading a record that holds New York's
    rows beside Kentucky's."""
    run = _with_due_shadow(folder, clock, host)
    if isinstance(run.es, Shadow):
        run.es = replace(run.es, kyy_store=_store_of(lambda: {**_kept(), **_ny_keys()}))
    return run


def test_ny_past_rows_in_the_kept_record_change_no_served_or_published_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """records-ny test 21: New York's rows in a kept record are kept (``kept_rows`` and
    ``kept_counts`` hold them), and every public file of every pass and the frozen district
    day are the same byte for byte with the shadow's nightly fit reading them as with the
    shadow off."""
    from predict.test_frozen import _passes  # noqa: PLC0415

    kept = {**_kept(), **_ny_keys()}
    learn = PredictConfig.load(PIPELINE_ROOT / "config" / "predict.yaml").learn
    assert {r.unit for r in record.kept_rows(kept, learn)} >= set(NY)
    assert {c.unit for c in record.kept_counts(kept)} >= set(NY)
    monkeypatch.setattr(lines, "_rows_k", lines_rows_k([]))
    on = _passes(_with_ny_record, tmp_path / "on")
    off = _passes(adjusting_pass, tmp_path / "off")
    assert on == off
    key = fa_test.DAY.isoformat()
    assert (
        frozen.day_path(tmp_path / "on", key).read_bytes()
        == frozen.day_path(tmp_path / "off", key).read_bytes()
    )
    fit = json.loads((tmp_path / "on" / "es" / lines.FIT_NAME).read_bytes())
    assert "m5y" in fit  # the nightly fit ran and read the record
