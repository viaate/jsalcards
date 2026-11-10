"""The live switch (predict-next TIMING-AUTO): the registry and each refusal; the key; the
served config; every cell of the truth table; the ledger's behaviour, its replay and the
excluded days; the host state's failures and the step's limits; a second term plugging in;
and the lines. Every storm here is SYNTHETIC (rows made up for the test), never live data."""

import hashlib
import itertools
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from snowlight.live.publishers import DirPublisher, PublishError
from snowlight.predict import frozen, live_read, live_switch
from snowlight.predict.config import LIVE_SCORE_SHA256, PredictConfig, live_score_sha256
from snowlight.predict.live_switch import (
    ClassScore,
    Evaluation,
    Group,
    LedgerDate,
    Term,
    TermState,
)
from snowlight.predict.situations import WeatherClass

CONFIG = PredictConfig.load()
RULE = live_switch.rules(CONFIG)["bus_timing"]
MODEL = "m" * 64
KEY = live_switch.key_of(CONFIG, RULE, MODEL)
CHICAGO = "America/Chicago"
NOW = datetime(2027, 2, 20, 15, 0, tzinfo=UTC)
TODAY = NOW.date()
FIRST = date(2027, 1, 4)


def changed(config: PredictConfig, block: str, **values: Any) -> dict[str, Any]:
    """``config``'s settings as plain data with ``block``'s ``values`` changed (None drops)."""
    body = config.model_dump(mode="json")
    found = dict(body["live_score"][block])
    for key, value in values.items():
        if value is None:
            found.pop(key, None)
        else:
            found[key] = value
    body["live_score"][block] = found
    return body


# --- the registry -------------------------------------------------------------------------------


def test_the_registered_rule_is_the_spec_s() -> None:
    assert (RULE.default, RULE.arm_off, RULE.arm_on) == ("off", 1.0, 0.95)
    assert (RULE.arm_block, RULE.arm_key, RULE.scope) == (
        "forecast_adjustment",
        "timing_after_bus",
        ("forecast_adjustment",),
    )
    assert (RULE.revision, RULE.frozen_key, RULE.freeze, RULE.classes) == (
        1,
        "bt",
        "d0_0507",
        ("advisory", "warning"),
    )
    assert (RULE.bootstrap, RULE.seed, RULE.bound, RULE.tolerance) == (2000, 23, 0.90, 0.005)
    assert (RULE.on_lower, RULE.new_date_min, RULE.on_after, RULE.off_after) == (0, 0, 3, 2)
    assert (RULE.clear_point, RULE.clear_lower, RULE.clear_class) == (-0.005, -0.010, -0.010)
    assert (
        RULE.supply_dates,
        RULE.supply_date_classes,
        RULE.supply_states,
        RULE.supply_rows,
        RULE.max_date_share,
    ) == (8, 10, 3, 300, 0.40)
    assert (RULE.class_rows, RULE.class_date_classes) == (100, 3)
    assert live_switch.FREEZES == frozen.NAMES
    assert set(live_switch.TERMS) == {"bus_timing"}


@pytest.mark.parametrize(
    ("block", "values", "match"),
    [
        ("forecast_adjustment", {"timing_after_bus": 0.95}, "not the default arm's"),
        ("forecast_adjustment", {"timing_bus": False}, "timing_bus must be true"),
        ("switch_bus_timing", {"default": "maybe"}, "must be off"),
        ("switch_bus_timing", {"default": True}, "must be off"),
        # S5 (critic r2): the truth table's ties, evidence and new date clause all go toward
        # off, so a term off by default is the only one it registers
        ("switch_bus_timing", {"default": "on"}, r"must be off \(ties go to off\)"),
        ("switch_bus_timing", {"new_date_min": 1.5}, "new_date_min out of range"),
        ("switch_bus_timing", {"arm_on": 1.0}, "the same value"),
        ("switch_bus_timing", {"arm_on": "high"}, "all names or all numbers"),
        ("switch_bus_timing", {"arm_on": True}, "not a name or a number"),
        ("switch_bus_timing", {"arm_on": 1.5}, "settings do not read"),
        ("switch_bus_timing", {"frozen_key": None}, "frozen_key names the shadow"),
        ("switch_bus_timing", {"arm_key": "timing_later"}, "no forecast_adjustment"),
        ("switch_bus_timing", {"arm_block": "nowhere"}, "no nowhere"),
        ("switch_bus_timing", {"scope": ["nowhere"]}, "scope"),
        ("switch_bus_timing", {"freeze": "d0_0700"}, "not a freeze"),
        ("switch_bus_timing", {"classes": ["advisory", "chain"]}, "not serving classes"),
        ("switch_bus_timing", {"bootstrap": 10}, "bootstrap"),
        ("switch_bus_timing", {"bound": 1.0}, "bound"),
        ("switch_bus_timing", {"tolerance": -0.1}, "tolerance"),
        ("switch_bus_timing", {"on_lower": -0.01}, "on_lower"),
        ("switch_bus_timing", {"on_after": 0}, "on_after"),
        ("switch_bus_timing", {"off_after": 1.5}, "off_after"),
        ("switch_bus_timing", {"revision": 0}, "revision"),
        ("switch_bus_timing", {"clear": {"point": 0.01, "lower": -0.01, "class": -0.01}}, "clear"),
        ("switch_bus_timing", {"clear": {"point": -0.005, "lower": -0.01}}, "clear"),
        ("switch_bus_timing", {"supply": {"dates": 8}}, "supply"),
        ("switch_bus_timing", {"class_min": {"rows": 0, "date_classes": 3}}, "class_min"),
        ("switch_bus_timing", {"seed": None}, "missing"),
        ("switch_bus_timing", {"later": 1}, "unknown"),
    ],
)
def test_config_refuses_a_bad_registration(block: str, values: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        PredictConfig.model_validate(changed(CONFIG, block, **values))


def test_a_rule_may_leave_out_the_new_date_clause() -> None:
    # S3 (critic r2): a term with no N clause leaves new_date_min out (CALL-TIME-2's rule)
    config = PredictConfig.model_validate(changed(CONFIG, "switch_bus_timing", new_date_min=None))
    rule = live_switch.rules(config)["bus_timing"]
    assert rule.new_date_min is None
    found = evaluation(new=-0.5)
    assert live_switch.step(rule, "off", 0, 0, found).word == "confident"
    assert live_switch.step(RULE, "off", 0, 0, found).clauses == ("this date at or under 0",)


def test_config_refuses_an_unknown_term() -> None:
    body = CONFIG.model_dump(mode="json")
    body["live_score"]["switch_other"] = dict(body["live_score"]["switch_bus_timing"])
    with pytest.raises(ValueError, match="no such term"):
        PredictConfig.model_validate(body)


def test_the_key_is_the_term_sha_the_model_sha_and_the_revision() -> None:
    body = {
        "switch_bus_timing": CONFIG.live_score["switch_bus_timing"],
        "forecast_adjustment": CONFIG.live_score["forecast_adjustment"],
    }
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    assert KEY.term_sha256 == hashlib.sha256(text.encode()).hexdigest()
    assert (KEY.model_sha256, KEY.revision) == (MODEL, 1)
    # a change to the scope block or the switch block is another key
    other = changed(CONFIG, "forecast_adjustment", timing_max=0.39)
    assert live_switch.term_sha256(PredictConfig.model_validate(other), RULE) != KEY.term_sha256
    other = changed(CONFIG, "switch_bus_timing", revision=2)
    found = PredictConfig.model_validate(other)
    rule = live_switch.rules(found)["bus_timing"]
    assert live_switch.key_of(found, rule, MODEL) != KEY
    assert live_switch.key_of(CONFIG, RULE, "n" * 64) != KEY


def test_the_served_config_changes_one_value_and_the_committed_sha_stays() -> None:
    on = live_switch.served_config(CONFIG, {"bus_timing": "on"})
    off = live_switch.served_config(CONFIG, {"bus_timing": "off"})
    assert on.live_score["forecast_adjustment"]["timing_after_bus"] == 0.95
    assert off.live_score == CONFIG.live_score
    differ = [
        (block, key)
        for block, values in CONFIG.live_score.items()
        for key, value in values.items()
        if on.live_score[block][key] != value
    ]
    assert differ == [("forecast_adjustment", "timing_after_bus")]
    # the committed config (and so every header's sha) is the registered one either way
    assert CONFIG.live_score["forecast_adjustment"]["timing_after_bus"] == 1.0
    assert live_score_sha256(CONFIG) == LIVE_SCORE_SHA256
    with pytest.raises(ValueError, match="no registered arm"):
        live_switch.served_config(CONFIG, {"bus_timing": "maybe"})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="no registered arm"):
        live_switch.served_config(CONFIG, {"other": "on"})
    assert live_switch.arm_settings(CONFIG, RULE, "on").timing_after_bus == 0.95
    assert live_switch.arm_settings(CONFIG, RULE, "off").timing_after_bus == 1.0


# --- the score ------------------------------------------------------------------------------


def brute_cll(t: np.ndarray, y: np.ndarray) -> float:
    m = int(y.sum())
    if m in {0, len(y)}:
        return 0.0
    total = sum(
        math.exp(sum(t[list(chosen)])) for chosen in itertools.combinations(range(len(t)), m)
    )
    return float(t[y].sum() - math.log(total))


def test_cll_equals_brute_force_and_concordance_counts_pairs() -> None:
    rng = np.random.default_rng(4)
    for n in range(1, 9):
        for _ in range(5):
            t = rng.normal(0, 1.5, n)
            y = rng.random(n) < 0.5
            assert live_switch.cll(t, y) == pytest.approx(brute_cll(t, y), abs=1e-10)
    values = np.array([0.1, 0.5, 0.5, 0.9, 0.2])
    closed = np.array([False, True, False, True, False])
    # closed 0.5 over 0.1, 0.2 and ties 0.5; closed 0.9 over all three opens
    assert live_switch.wins2(values, closed) == 2 * 2 + 1 + 2 * 3


def test_a_group_scores_each_arm_and_says_whether_it_moved() -> None:
    day = FIRST
    found = live_switch.scored(
        day, "advisory", None, [0.3, 0.3, 0.3, 0.3], [0.4, 0.2, 0.4, 0.2],
        [True, False, True, False], ["36", "36", "42", "36"],
    )  # fmt: skip
    assert (found.n, found.closed, found.pairs, found.moved, found.states) == (
        4, 2, 4, True, ("36", "42"),
    )  # fmt: skip
    assert found.informative
    assert found.cll_off == pytest.approx(-math.log(6))  # every split equally likely
    assert found.cll_on > found.cll_off
    assert (found.wins2_on, found.wins2_off) == (8, 4)
    same = live_switch.scored(day, "advisory", None, [0.3, 0.4], [0.3, 0.4], [True, False], [])
    assert not same.moved
    assert Group.of(day, found.as_json()) == found


# --- the truth table ------------------------------------------------------------------------


def evaluation(  # noqa: PLR0913 - each number of an evaluation a cell sets
    *,
    point: float = 0.002,
    lower: float = 0.001,
    new: float = 0.002,
    moved_dates: int = 8,
    date_classes: int = 10,
    states: int = 3,
    rows: int = 300,
    share: float = 0.3,
    advisory: float = 0.002,
    warning: float = 0.002,
    bound: tuple[bool, bool] = (True, True),
    extra: tuple[str, ...] = (),
) -> Evaluation:
    return Evaluation(
        day=FIRST,
        number=1,
        moved_dates=moved_dates,
        date_classes=date_classes,
        states=states,
        rows=rows,
        largest_share=share,
        point=point,
        lower=lower,
        upper=point + 0.001,
        classes=(
            ClassScore("advisory", advisory * 150, 150, 5, bound[0]),
            ClassScore("warning", warning * 150, 150, 5, bound[1]),
        ),
        new_date=new,
        concordance_on=0.6,
        concordance_off=0.6,
        extra=extra,
    )


OFF_FAILING: dict[str, dict[str, Any]] = {
    "moved dates": {"moved_dates": 7},
    "date-classes": {"date_classes": 9},
    "states": {"states": 2},
    "rows": {"rows": 299},
    "largest date": {"share": 0.41},
    "a tie": {"point": 0.0},
    "behind": {"point": -0.001},
    "lower at on_lower": {"lower": 0.0},
    "lower under tolerance": {"lower": -0.006},
    "a binding class": {"advisory": -0.006},
    "this date at 0": {"new": 0.0},
    "an extra": {"extra": ("short of its own",)},
}


@pytest.mark.parametrize("cell", sorted(OFF_FAILING))
def test_off_each_clause_failing_alone_resets_the_on_streak(cell: str) -> None:
    found = live_switch.step(RULE, "off", 2, 0, evaluation(**OFF_FAILING[cell]))
    assert (found.word, found.served, found.on_streak, found.switched) == (
        "not confident", "off", 0, False,
    )  # fmt: skip
    assert len(found.clauses) == 1, found.clauses


def test_off_the_clauses_say_what_failed() -> None:
    found = live_switch.step(RULE, "off", 0, 0, evaluation(moved_dates=7, new=-0.001))
    assert found.clauses == ("short of evidence (7 of 8 moved dates)", "this date at or under 0")
    found = live_switch.step(RULE, "off", 0, 0, evaluation(lower=-0.006, warning=-0.006))
    assert found.clauses == ("lower bound at or under 0", "warning under -0.005")


def test_off_an_unbound_class_has_no_effect_and_3_confident_turn_on() -> None:
    weak = evaluation(advisory=-0.02, bound=(False, True))
    first = live_switch.step(RULE, "off", 0, 0, weak)
    assert (first.word, first.on_streak, first.served) == ("confident", 1, "off")
    second = live_switch.step(RULE, "off", 1, 0, weak)
    assert (second.on_streak, second.served) == (2, "off")
    third = live_switch.step(RULE, "off", 2, 0, weak)
    assert (third.word, third.served, third.on_streak, third.off_streak, third.switched) == (
        "confident", "on", 0, 0, True,
    )  # fmt: skip


def test_on_holding_with_a_lower_bound_under_0_resets_the_off_streak() -> None:
    # on_lower is no BEHIND clause: holding needs only L >= -tolerance, and no evidence
    found = live_switch.step(RULE, "on", 0, 1, evaluation(lower=-0.001, moved_dates=1, new=-1))
    assert (found.word, found.served, found.off_streak) == ("holding", "on", 0)


@pytest.mark.parametrize(
    "values",
    [
        {"point": 0.0},
        {"point": -0.001},
        {"lower": -0.006},
        {"warning": -0.007},
        {"extra": ("short of its own",)},
    ],
)
def test_on_behind_adds_to_the_off_streak_and_2_turn_off(values: dict[str, Any]) -> None:
    once = live_switch.step(RULE, "on", 0, 0, evaluation(**values))
    assert (once.word, once.served, once.off_streak, once.switched) == ("behind", "on", 1, False)
    twice = live_switch.step(RULE, "on", 0, 1, evaluation(**values))
    assert (twice.word, twice.served, twice.on_streak, twice.off_streak, twice.switched) == (
        "behind", "off", 0, 0, True,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("values", "clause"),
    [
        ({"point": -0.0051}, "on - off -0.0051"),
        ({"lower": -0.0101}, "lower bound -0.0101"),
        ({"advisory": -0.0101}, "advisory -0.0101"),
    ],
)
def test_on_each_clear_clause_turns_off_at_once(values: dict[str, Any], clause: str) -> None:
    found = live_switch.step(RULE, "on", 0, 0, evaluation(**values))
    assert (found.word, found.served, found.switched, found.clauses) == (
        "clear", "off", True, (clause,),
    )  # fmt: skip
    # an unbound class clears nothing
    loose = evaluation(advisory=-0.02, bound=(False, True))
    assert live_switch.step(RULE, "on", 0, 0, loose).word == "holding"


# --- a synthetic winter -----------------------------------------------------------------------


def school_days(count: int, first: date = FIRST) -> list[date]:
    found: list[date] = []
    day = first
    while len(found) < count:
        if day.weekday() < 5:
            found.append(day)
        day += timedelta(days=1)
    return found


def synthetic_groups(
    day: date, gain: float, n: int = 40, states: Sequence[str] = ("36",)
) -> list[Group]:
    """Two moved groups (advisory, warning), each ``n`` rows half closed, with on - off
    ``gain`` a district-day (SYNTHETIC)."""
    found = []
    for klass in RULE.classes:
        found.append(
            Group(
                day=day, klass=klass, stratum=None, n=n, closed=n // 2,
                cll_on=-10.0 + gain * n, cll_off=-10.0, pairs=(n // 2) * (n - n // 2),
                wins2_on=n * n // 4, wins2_off=n * n // 4, moved=True, states=tuple(states),
            )
        )  # fmt: skip
    return found


def winter(gains: Sequence[float]) -> list[LedgerDate]:
    days = school_days(len(gains))
    return [
        LedgerDate(day, "a" * 64, tuple(synthetic_groups(day, g, states=(f"{10 + i % 3}",))))
        for i, (day, g) in enumerate(zip(days, gains, strict=True))
    ]


BUS = live_switch.TERMS["bus_timing"]


def test_the_replay_turns_on_after_3_confident_evaluations_and_is_deterministic() -> None:
    ledger = winter([0.01] * 12)
    found = live_switch.replay(RULE, ledger, BUS, CONFIG)
    words = [j.verdict.word for j in found.judged]
    # dates 1-7 are short of evidence (8 moved dates); 8, 9 and 10 confident: ON at 10
    assert words[:7] == ["not confident"] * 7
    assert words[7:10] == ["confident"] * 3
    assert found.judged[9].verdict.switched
    assert found.judged[9].streak == tuple(e.day for e in ledger[7:10])
    assert words[10:] == ["holding", "holding"]
    assert (found.served, found.on_streak, found.off_streak) == ("on", 0, 0)
    again = live_switch.replay(RULE, ledger, BUS, CONFIG)
    assert [j.evaluation for j in again.judged] == [j.evaluation for j in found.judged]
    # an unmoved date enters the ledger but is no evaluation
    quiet = [replace(g, moved=False, cll_on=g.cll_off) for g in ledger[3].groups]
    still = [*ledger[:3], replace(ledger[3], groups=tuple(quiet)), *ledger[4:]]
    assert len(live_switch.replay(RULE, still, BUS, CONFIG).judged) == 11


def test_the_evaluation_s_numbers_are_the_ledger_s() -> None:
    ledger = winter([0.01, 0.02, -0.01])
    found = live_switch.evaluate(RULE, ledger, 3)
    assert (found.moved_dates, found.date_classes, found.states, found.rows) == (3, 6, 3, 240)
    assert found.point == pytest.approx((0.01 + 0.02 - 0.01) / 3)
    assert found.new_date == pytest.approx(-0.01)
    assert found.largest_share == pytest.approx(1 / 3)
    assert found.lower <= found.point <= found.upper
    assert [c.binding for c in found.classes] == [True, True]  # 120 rows over 3 date-classes
    rng = np.random.default_rng(23)
    picks = rng.integers(0, 3, size=(2000, 3))
    d = np.array([0.01 * 80, 0.02 * 80, -0.01 * 80])
    assert found.lower == pytest.approx(float(np.percentile(d[picks].sum(1) / (80 * 3), 5)))


# --- the step in read-labels --------------------------------------------------------------------


class Clock:
    def __init__(self, at: float = 0.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


def write_labels(reads: Path, day: date, labels: Mapping[str, tuple[int, str]]) -> bytes:
    """L1's file of ``day`` (SYNTHETIC): each district's weather class and label, tier A."""
    rows = [
        {
            "district": leaid, "weather": weather, "after": False, "label": label,
            "tier": "A", "market": "m1", "sources": ["s1"],
        }
        for leaid, (weather, label) in sorted(labels.items())
    ]  # fmt: skip
    data = json.dumps({"schema_version": 1, "day": day.isoformat(), "rows": rows}).encode()
    path = live_read.rows_path(reads, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def write_frozen(
    folder: Path,
    day: date,
    rows: Sequence[tuple[str, str, float, float]],
    key: live_switch.Key = KEY,
    freeze: str = "d0_0507",
) -> None:
    """A frozen day (SYNTHETIC): one zone's freeze with each (LEAID, class, off, on) row."""
    folder.mkdir(parents=True, exist_ok=True)
    at = frozen.freeze_at(day, CHICAGO, freeze)
    header = {
        "k": "freeze", "day": day.isoformat(), "freeze": freeze, "zone": CHICAGO,
        "at": at.isoformat(), "late_by_s": 0, "generated_at": at.isoformat(),
        "live_score_sha256": LIVE_SCORE_SHA256, "public": True, "rows": len(rows),
        "switch": {
            "bus_timing": {
                "arm": "off", "sha256": key.term_sha256, "model_sha256": key.model_sha256,
            }
        },
    }  # fmt: skip
    lines = [header] + [
        {"l": leaid, "s": 1, "c": klass, "sit": klass, "pr": off, "v": {"bt": [off, on]}}
        for leaid, klass, off, on in rows
    ]
    data = b"".join(json.dumps(line, sort_keys=True).encode() + b"\n" for line in lines)
    index = frozen.load_index(folder)
    frozen.day_path(folder, day.isoformat()).write_bytes(data)
    index.fresh = False
    index.days[day.isoformat()] = frozen.DayEntry(
        zones=[CHICAGO], groups={f"{CHICAGO}|{freeze}": "taken"}, bytes=len(data)
    )
    frozen.save_index(folder, index)


def storm_day(
    reads: Path, folder: Path, day: date, gain: float, states: Sequence[str] = ("29", "20", "49")
) -> None:
    """A SYNTHETIC storm morning: 30 advisory and 30 warning districts over ``states``, half
    of each closed, the on arm ``gain`` higher (or lower) on the closed and lower on the open."""
    labels: dict[str, tuple[int, str]] = {}
    rows: list[tuple[str, str, float, float]] = []
    for klass, weather in (
        ("advisory", WeatherClass.ADVISORY),
        ("warning", WeatherClass.SNOW_WARNING),
    ):
        for i in range(30):
            leaid = f"{states[i % len(states)]}{klass[0]}{i:04d}"
            shut = i % 2 == 0
            labels[leaid] = (int(weather), "no_school" if shut else "unnamed")
            off = 0.3 + 0.01 * (i % 5)
            on = off + (gain if shut else -gain)
            rows.append((leaid, klass, round(off, 6), round(on, 6)))
    write_labels(reads, day, labels)
    write_frozen(folder, day, rows)


class Host:
    """A folder host that counts writes and can fail or race."""

    def __init__(self, root: Path) -> None:
        self.folder = DirPublisher(root)
        self.writes = 0
        self.fail = False
        self.race: bytes | None = None

    def write(self, files: Mapping[str, bytes]) -> None:
        if self.fail:
            raise PublishError("write: HTTP 500")
        self.writes += 1
        self.folder.write(files)

    def read(self, key: str) -> bytes | None:
        found = self.folder.read(key)
        if self.race is not None and key.endswith("switch.json"):
            # another writer writes between this run's read and its write
            raced, self.race = self.race, None
            self.folder.write({key: raced})
        return found


def step_inputs(
    tmp_path: Path, host: Host, *, config: PredictConfig = CONFIG, clock: Clock | None = None
) -> live_switch.StepInputs:
    return live_switch.StepInputs(
        config=config,
        host=host,
        prefix="v1",
        reads=tmp_path / "reads",
        frozen=tmp_path / "frozen",
        model_sha256=MODEL,
        now=NOW,
        started=0.0,
        clock=clock or Clock(),
    )


def run(inputs: live_switch.StepInputs) -> list[str]:
    out: list[str] = []
    live_switch.run(inputs, out.append)
    return out


def state_of(host: Host) -> dict[str, TermState]:
    data = host.read(f"v1/{live_switch.SWITCH_PATH}")
    assert data is not None
    return live_switch.parse_state(data)


def started(tmp_path: Path, host: Host) -> None:
    """A first run before any labeled storm: the term starts through the day before FIRST."""
    write_labels(tmp_path / "reads", FIRST - timedelta(days=3), {})
    out = run(step_inputs(tmp_path, host))
    assert any(
        f"started (no state; term sha {KEY.term_sha256[:8]}, model sha mmmmmmmm)" in line
        for line in out
    ), out


def test_the_first_run_starts_the_term_through_the_newest_labeled_date(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    state = state_of(host)["bus_timing"]
    assert (state.served, state.through, state.ledger) == ("off", FIRST - timedelta(days=3), ())
    assert (state.term_sha256, state.model_sha256) == (KEY.term_sha256, MODEL)
    assert frozen.read_marker(tmp_path / "frozen") == FIRST - timedelta(days=3)
    # a run with no new labeled date writes nothing
    writes = host.writes
    out = run(step_inputs(tmp_path, host))
    assert host.writes == writes
    assert out == [
        "predict read-labels: switch bus_timing (served off): through 2027-01-01; 0 of 8 moved "
        "dates, 0 of 10 date-classes, 0 of 3 states, 0 of 300 rows; ON streak 0 of 3; 0 new "
        "labeled dates (0 informative, 0 moved, 0 with no frozen rows)"
    ]


def test_bus_groups_score_l1_s_labeled_rows_of_the_row_s_class_under_the_key(
    tmp_path: Path,
) -> None:
    reads, folder = tmp_path / "reads", tmp_path / "frozen"
    storm_day(reads, folder, FIRST, 0.05)
    status, day = frozen.switch_day(folder, FIRST, "d0_0507")
    assert status == "ready"
    assert day is not None
    _sha, labels = live_switch._label_rows(reads, FIRST)
    inputs = live_switch.DayInputs(FIRST, labels, day, RULE, KEY, live_switch._class_of(CONFIG))
    found = live_switch.bus_groups(inputs)
    assert [(g.klass, g.n, g.closed, g.moved) for g in found] == [
        ("advisory", 30, 15, True), ("warning", 30, 15, True),
    ]  # fmt: skip
    assert all(g.cll_on > g.cll_off for g in found)
    assert found[0].states == ("20", "29", "49")
    # under another key, none counts
    other = replace(KEY, term_sha256="0" * 64)
    assert live_switch.bus_groups(replace(inputs, key=other)) == []
    # a row L1 put in another class (or did not label) is left out
    shifted = dict(labels)
    first = next(iter(sorted(shifted)))
    shifted[first] = replace(shifted[first], weather="cold")
    assert sum(g.n for g in live_switch.bus_groups(replace(inputs, labels=shifted))) == 59


def test_a_backlog_of_3_dates_is_3_evaluations_and_the_replay_is_the_live_sequence(
    tmp_path: Path,
) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(12)
    for day in days[:9]:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    out = run(step_inputs(tmp_path, host))
    assert sum(" evaluation " in line for line in out) == 9
    state = state_of(host)["bus_timing"]
    assert (state.served, state.on_streak, state.through) == ("off", 2, days[8])
    for day in days[9:12]:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    out = run(step_inputs(tmp_path, host))
    assert sum(" evaluation " in line for line in out) == 3
    switched = [line for line in out if "SWITCHED" in line]
    assert switched == [
        f"predict read-labels: switch bus_timing: SWITCHED on after 3 confident evaluations "
        f"({days[7]}, {days[8]}, {days[9]}): timing_after_bus 0.95 serves from this run's passes"
    ]
    state = state_of(host)["bus_timing"]
    assert (state.served, state.on_streak, state.off_streak) == ("on", 0, 0)
    replayed = live_switch.replay(RULE, state.ledger, BUS, CONFIG)
    assert [j.evaluation.as_json() for j in replayed.judged] == list(state.evaluations)
    assert state.switches == ({"date": days[9].isoformat(), "to": "on", "why": "confident"},)
    served = live_switch.served_arms(
        CONFIG, host.read(f"v1/{live_switch.SWITCH_PATH}"), MODEL, today=TODAY
    )
    assert served.arms == {"bus_timing": "on"}
    assert served.lines == (
        f"switch: bus_timing served on (switch.json through {days[11]}, 12 evaluations)",
    )
    assert frozen.read_marker(tmp_path / "frozen") == days[11]
    # the state holds counts, sums and state codes: no LEAID
    data = host.read(f"v1/{live_switch.SWITCH_PATH}") or b""
    assert b"29a0000" not in data
    assert b'"29"' in data


def test_the_evaluation_line_and_a_quiet_date(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    day, quiet = school_days(2)
    storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    write_labels(tmp_path / "reads", quiet, {})
    write_frozen(tmp_path / "frozen", quiet, [])
    out = run(step_inputs(tmp_path, host))
    evaluation_line = next(line for line in out if " evaluation " in line)
    found = state_of(host)["bus_timing"].evaluations[0]
    point, lower, upper = (float(str(found[k])) for k in ("point", "lower", "upper"))
    assert evaluation_line == (
        f"predict read-labels: switch bus_timing: {day} evaluation 1 (served off): 1 moved "
        f"dates, 2 date-classes, 3 states, 60 rows, largest date 100%; on - off {point:+.4f} a "
        f"district-day (90% {lower:+.4f} to {upper:+.4f}); advisory {point:+.4f} (30 rows, not "
        f"binding), warning {point:+.4f} (30 rows, not binding); this date {point:+.4f}; "
        "concordance on 1.000 off 0.500; not confident: short of evidence (1 of 8 moved dates, "
        "2 of 10 date-classes, 60 of 300 rows, largest date 100% over 40%); ON streak 0 of 3"
    )
    assert out[-2] == (
        f"predict read-labels: switch bus_timing (served off): through {quiet}; 1 of 8 moved "
        "dates, 2 of 10 date-classes, 3 of 3 states, 60 of 300 rows; ON streak 0 of 3; 2 new "
        "labeled dates (1 informative, 1 moved, 1 with no frozen rows)"
    )
    assert out[-1].startswith("predict read-labels: switch: wrote predictions/switch.json (")
    assert out[-1].endswith(" B), read back")


def test_a_labeled_date_waits_for_its_frozen_day_then_counts_as_absent(tmp_path: Path) -> None:
    day, later = school_days(2)
    for root, now, through, line in (
        (tmp_path / "soon", datetime.combine(later, datetime.min.time(), UTC), None, "0 new"),
        (tmp_path / "late", NOW, later, "2 new labeled dates (1 informative, 1 moved, 1 with"),
    ):
        host = Host(root / "host")
        started(root, host)
        write_labels(root / "reads", day, {"2900001": (1, "no_school")})
        storm_day(root / "reads", root / "frozen", later, 0.05)
        out = run(replace(step_inputs(root, host), now=now))
        # within 7 days it waits, with every later date; then it is passed as absent
        assert state_of(host)["bus_timing"].through == (through or FIRST - timedelta(days=3))
        assert line in out[-2] if through else line in out[-1], out


def test_a_released_day_counts_as_absent_and_a_day_still_freezing_waits(tmp_path: Path) -> None:
    folder = tmp_path / "frozen"
    day = school_days(1)[0]
    storm_day(tmp_path / "reads", folder, day, 0.05)
    index = frozen.load_index(folder)
    index.days[day.isoformat()].zones.append("America/Denver")
    frozen.save_index(folder, index)
    assert frozen.switch_day(folder, day, "d0_0507")[0] == "wait"
    index.days[day.isoformat()].closed = NOW.isoformat()
    frozen.save_index(folder, index)
    assert frozen.switch_day(folder, day, "d0_0507")[0] == "ready"
    del index.days[day.isoformat()]
    index.done[day.isoformat()] = "x"
    frozen.save_index(folder, index)
    assert frozen.switch_day(folder, day, "d0_0507") == ("released", None)
    assert frozen.switch_day(folder, day + timedelta(days=1), "d0_0507") == ("missing", None)


def test_a_change_of_the_term_sha_or_the_model_restarts_the_term(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(2)
    storm_day(tmp_path / "reads", tmp_path / "frozen", days[0], 0.05)
    run(step_inputs(tmp_path, host))
    assert len(state_of(host)["bus_timing"].ledger) == 1
    storm_day(tmp_path / "reads", tmp_path / "frozen", days[1], 0.05)
    other = replace(step_inputs(tmp_path, host), model_sha256="n" * 64)
    out = run(other)
    assert (
        "predict read-labels: switch bus_timing: restarted "
        "(model sha mmmmmmmm to model sha nnnnnnnn)" in out
    )
    state = state_of(host)["bus_timing"]
    assert (state.model_sha256, state.ledger, state.through, state.served) == (
        "n" * 64, (), days[1], "off",
    )  # fmt: skip
    body = changed(CONFIG, "switch_bus_timing", revision=2)
    out = run(step_inputs(tmp_path, host, config=PredictConfig.model_validate(body)))
    assert any(f"restarted (term sha {KEY.term_sha256[:8]} to term sha" in line for line in out)


def test_a_counted_date_relabeled_keeps_its_numbers_and_warns(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    day = school_days(1)[0]
    storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    run(step_inputs(tmp_path, host))
    before = state_of(host)["bus_timing"]
    data = write_labels(tmp_path / "reads", day, {"2900001": (1, "no_school")})
    out = run(step_inputs(tmp_path, host))
    warned = [
        line
        for line in out
        if line.startswith("::warning::predict read-labels: switch bus_timing: L1's file of")
        and "its counted numbers are kept" in line
    ]
    assert len(warned) == 1
    after = state_of(host)["bus_timing"]
    # the counted numbers are kept; the file warned of is kept with them, so it is said once
    assert [replace(e, warned_sha256=None) for e in after.ledger] == list(before.ledger)
    assert after.ledger[0].warned_sha256 == hashlib.sha256(data).hexdigest()
    assert (after.served, after.evaluations) == (before.served, before.evaluations)
    writes = host.writes
    out = run(step_inputs(tmp_path, host))
    assert not any("changed after it was counted" in line for line in out)
    assert host.writes == writes
    # another new file is said again
    write_labels(tmp_path / "reads", day, {"2900002": (1, "no_school")})
    out = run(step_inputs(tmp_path, host))
    assert sum("changed after it was counted" in line for line in out) == 1


def test_failed_and_refused_writes_change_nothing_and_the_next_run_catches_up(
    tmp_path: Path,
) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    before = host.read(f"v1/{live_switch.SWITCH_PATH}")
    day = school_days(1)[0]
    storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    host.fail = True
    out = run(step_inputs(tmp_path, host))
    assert out[-1] == "::warning::predict read-labels: switch: PublishError: nothing written"
    # the lines of a state not written say so
    assert out[0].endswith("(not written)")
    assert all(line.endswith("(not written)") for line in out[:-1])
    assert host.read(f"v1/{live_switch.SWITCH_PATH}") == before
    assert frozen.read_marker(tmp_path / "frozen") == FIRST - timedelta(days=3)  # days kept
    # a concurrent writer: the compare and swap refuses, nothing written
    host.fail = False
    host.race = b'{"schema_version":1,"terms":{}}\n'
    out = run(step_inputs(tmp_path, host))
    assert out[-1] == "::warning::predict read-labels: switch: GuardRefusedError: nothing written"
    assert all(line.endswith("(not written)") for line in out[:-1])
    assert host.read(f"v1/{live_switch.SWITCH_PATH}") == b'{"schema_version":1,"terms":{}}\n'
    # the next run re-reads and evaluates from the host's state
    out = run(step_inputs(tmp_path, host))
    assert out[-1].startswith("predict read-labels: switch: wrote")


def test_an_unreadable_state_is_restarted_over_and_a_later_schema_is_never_written(
    tmp_path: Path,
) -> None:
    host = Host(tmp_path / "host")
    key = f"v1/{live_switch.SWITCH_PATH}"
    write_labels(tmp_path / "reads", FIRST - timedelta(days=3), {})
    for data, name in ((b"not json", "JSONDecodeError"), (b"[" * 100_000, "RecursionError")):
        host.write({key: data})
        out = run(step_inputs(tmp_path, host))
        assert out[0] == (
            f"::warning::predict read-labels: switch: {live_switch.SWITCH_PATH} does not read "
            f"({name}): every term restarted over it"
        )
        assert out[1] == (
            "predict read-labels: switch bus_timing: restarted (a state that does not read, to "
            f"term sha {KEY.term_sha256[:8]}, model sha mmmmmmmm)"
        )
        assert out[-1].startswith("predict read-labels: switch: wrote")
        state = state_of(host)["bus_timing"]
        assert (state.served, state.ledger, state.through) == ("off", (), FIRST - timedelta(3))
    # S2 (critic r2): the warning waits for the write; a racer refuses it, and it says so
    host.write({key: b"not json"})
    host.race = b'{"schema_version":1,"terms":{}}\n'
    out = run(step_inputs(tmp_path, host))
    assert out[0] == (
        f"::warning::predict read-labels: switch: {live_switch.SWITCH_PATH} does not read "
        "(JSONDecodeError): every term would restart over it (not written)"
    )
    assert out[-1] == "::warning::predict read-labels: switch: GuardRefusedError: nothing written"
    assert host.read(key) == b'{"schema_version":1,"terms":{}}\n'
    later = b'{"schema_version": 2, "terms": {}}'
    host.write({key: later})
    writes = host.writes
    out = run(step_inputs(tmp_path, host))
    assert out == [
        "::warning::predict read-labels: switch: predictions/switch.json is of a later schema: "
        "nothing written"
    ]
    assert (host.writes, host.read(key)) == (writes, later)


class Ticks(Clock):
    """A clock that moves ``step`` seconds each time it is read after ``after`` reads."""

    def __init__(self, at: float, step: float, after: int = 0) -> None:
        super().__init__(at)
        self.step, self.after = step, after

    def __call__(self) -> float:
        found = self.at
        if self.after:
            self.after -= 1
        else:
            self.at += self.step
        return found


def test_the_45_s_start_55_s_count_and_65_s_write_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = Host(tmp_path / "host")
    out = run(step_inputs(tmp_path, host, clock=Clock(45.5)))
    assert out == ["predict read-labels: switch: skipped past 45 s of the step"]
    assert host.writes == 0
    started(tmp_path, host)
    day = school_days(1)[0]
    storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    clock = Clock(0.0)
    made = live_switch.state_bytes

    def slow(terms: Mapping[str, TermState]) -> bytes:
        clock.at = 66.0  # after the count: past the write limit, and no date ran late
        return made(terms)

    monkeypatch.setattr(live_switch, "state_bytes", slow)
    writes = host.writes
    out = run(step_inputs(tmp_path, host, clock=clock))
    assert out[-1] == "predict read-labels: switch: skipped past 65 s of the step: nothing written"
    assert all(line.endswith("(not written)") for line in out[:-1])
    assert host.writes == writes


def test_a_backlog_past_the_count_limit_is_counted_over_two_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(6)
    for day in days:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    # each date takes 35.5 s: a second would end past 55 s, so the state is written through
    # the first (a backlog never written whole would be retried whole for good), and the
    # next run counts the rest
    clock = Clock(0.0)
    count = live_switch._count_day

    def slow(*args: Any) -> Any:
        clock.at += 35.5
        return count(*args)

    monkeypatch.setattr(live_switch, "_count_day", slow)
    out = run(step_inputs(tmp_path, host, clock=clock))
    monkeypatch.undo()
    state = state_of(host)["bus_timing"]
    assert (state.through, len(state.ledger)) == (days[0], 1)
    assert out[-2].endswith(f"; 5 labeled dates from {days[1]} left for the next run (past 55 s)")
    out = run(step_inputs(tmp_path, host))
    state = state_of(host)["bus_timing"]
    assert (state.through, len(state.ledger)) == (days[-1], len(days))
    replayed = live_switch.replay(RULE, state.ledger, BUS, CONFIG)
    assert [j.evaluation.as_json() for j in replayed.judged] == list(state.evaluations)


def test_a_date_that_does_not_read_stops_the_count_before_it_and_excluding_it_passes_it(
    tmp_path: Path,
) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(3)
    for day in days:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    live_read.rows_path(tmp_path / "reads", days[1]).write_bytes(b"{broken")
    for _ in range(2):  # each run says so, and makes no progress past it
        out = run(step_inputs(tmp_path, host))
        assert (
            f"::warning::predict read-labels: switch bus_timing: {days[1]} does not read "
            "(JSONDecodeError): counting stops before it (learn.excluded_days passes it)"
        ) in out
        state = state_of(host)["bus_timing"]
        assert (state.through, len(state.ledger)) == (days[0], 1)
        assert any(
            line.endswith(f"; 2 labeled dates held at {days[1]}, which does not read")
            for line in out
        )
    excluded = CONFIG.model_copy(update={"learn": replace_learn(CONFIG, (days[1],))})
    out = run(step_inputs(tmp_path, host, config=excluded))
    state = state_of(host)["bus_timing"]
    assert (state.through, [e.day for e in state.ledger]) == (days[2], [days[0], days[2]])


def test_a_labeled_date_waiting_says_how_many_wait_and_for_which_day(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(3)
    write_labels(tmp_path / "reads", days[0], {"2900001": (1, "no_school")})
    for day in days[1:]:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    soon = datetime.combine(days[2], datetime.min.time(), UTC)
    out = run(replace(step_inputs(tmp_path, host), now=soon))
    assert out[-1].endswith(
        f"0 new labeled dates (0 informative, 0 moved, 0 with no frozen rows); 3 labeled dates "
        f"waiting for the frozen day of {days[0]}"
    )


def test_the_keep_window_holds_the_days_after_a_date_passed_as_absent(tmp_path: Path) -> None:
    # S2 (critic r1): a labeled date whose frozen day never came is passed as absent once
    # WAIT_DAYS have gone; the next day is still held by then, with days to spare.
    from snowlight.live.evidence import DATABASES, FROZEN  # noqa: PLC0415

    assert frozen.KEEP_DAYS >= live_switch.WAIT_DAYS + 2
    folder = tmp_path / "frozen"
    lost, next_day = school_days(2)
    storm_day(tmp_path / "reads", folder, next_day, 0.05)
    index = frozen.load_index(folder)
    entry = index.days[next_day.isoformat()]
    entry.closed = datetime.combine(
        next_day + timedelta(days=1), datetime.min.time(), UTC
    ).isoformat()
    frozen.save_index(folder, index)
    frozen.write_marker(folder, lost - timedelta(days=1))
    data = frozen.day_path(folder, next_day.isoformat()).read_bytes()
    digest = hashlib.sha256(data[: entry.bytes]).hexdigest()
    held = {name: {(FROZEN, next_day.isoformat()): frozenset({digest})} for name in DATABASES}
    # the first run past the wait: the lost date passes as absent, the next day is still here
    passed = datetime.combine(
        lost + timedelta(days=live_switch.WAIT_DAYS + 1), datetime.min.time(), UTC
    )
    assert frozen.note_held(folder, held, passed + timedelta(days=1)) == []
    assert frozen.switch_day(folder, next_day, "d0_0507")[0] == "ready"


# --- serving --------------------------------------------------------------------------------


def stored(  # noqa: PLR0913 - each field a test sets
    served: str = "off",
    on: int = 0,
    off: int = 0,
    ledger: Sequence[LedgerDate] = (),
    *,
    through: date | None = None,
    evaluations: tuple[Mapping[str, object], ...] | None = None,
) -> bytes:
    """A state (SYNTHETIC) over ``ledger``, its evaluations its replay's unless given."""
    judged = live_switch.replay(RULE, ledger, BUS, CONFIG).judged
    state = TermState(
        term_sha256=KEY.term_sha256, model_sha256=MODEL, revision=1, served=served,  # type: ignore[arg-type]
        on_streak=on, off_streak=off, through=through or (ledger[-1].day if ledger else FIRST),
        ledger=tuple(ledger),
        evaluations=tuple(j.evaluation.as_json() for j in judged)
        if evaluations is None
        else evaluations,
    )  # fmt: skip
    return live_switch.state_bytes({"bus_timing": state})


def test_serving_takes_the_default_on_every_doubt() -> None:
    ledger = winter([0.01] * 12)
    good = stored("on", ledger=ledger)
    assert live_switch.served_arms(CONFIG, good, MODEL, today=TODAY).arms == {"bus_timing": "on"}
    for data, why, warned in (
        (None, "no switch.json", False),
        (b"{", "switch.json does not read (JSONDecodeError)", True),
        (b'{"schema_version": 2, "terms": {}}', "switch.json does not read (ValueError)", True),
        (live_switch.state_bytes({}), "no state for it", False),
        (stored("on", ledger=ledger[:9]), "not the replay of its ledger", True),  # a hand edit
        (stored("off", ledger=ledger), "not the replay of its ledger", True),
        (stored("on", on=1, ledger=ledger), "not the replay of its ledger", True),
    ):
        found = live_switch.served_arms(CONFIG, data, MODEL, today=TODAY)
        assert found.arms == {"bus_timing": "off"}
        assert found.lines == (
            f"{'::warning::' if warned else ''}switch: bus_timing served off, the committed "
            f"default ({why})",
        )
    found = live_switch.served_arms(CONFIG, good, "n" * 64, today=TODAY)
    assert found.lines == ("switch: bus_timing served off, the committed default (another key)",)
    found = live_switch.served_arms(CONFIG, None, MODEL, why="publishing is off", today=TODAY)
    assert found.arms == {"bus_timing": "off"}
    excluded = CONFIG.model_copy(update={"learn": replace_learn(CONFIG, (ledger[4].day,))})
    found = live_switch.served_arms(excluded, good, MODEL, today=TODAY)
    assert found.arms == {"bus_timing": "off"}
    assert "in learn.excluded_days" in found.lines[0]


def replace_learn(config: PredictConfig, days: tuple[date, ...]) -> Any:
    return config.learn.model_copy(update={"excluded_days": days})


def test_a_day_with_an_excluded_row_is_dropped_whole_and_replayed(tmp_path: Path) -> None:
    # predict-next ONE-STORM: the ledger keeps sums per date, so a day a pair of
    # learn.excluded_rows names is dropped whole, by the excluded-day code, and its line names
    # the list.
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(12)
    for day in days[:10]:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    run(step_inputs(tmp_path, host))
    assert state_of(host)["bus_timing"].served == "on"
    held = host.read(f"v1/{live_switch.SWITCH_PATH}")

    def with_lists(days_out: tuple[date, ...], pairs: tuple[tuple[date, str], ...]) -> Any:
        learned = CONFIG.learn.model_copy(
            update={"excluded_days": days_out, "excluded_rows": pairs}
        )
        return CONFIG.model_copy(update={"learn": learned})

    # serving refuses a state whose ledger holds the day, and names the list
    row_out = with_lists((), ((days[8], "2900001"),))
    found = live_switch.served_arms(row_out, held, MODEL, today=TODAY)
    assert found.arms == {"bus_timing": "off"}
    assert f"its ledger holds {days[8].isoformat()}, in learn.excluded_rows" in found.lines[0]
    both = with_lists((days[8],), ((days[8], "2900001"),))  # in both lists: the day's list
    found = live_switch.served_arms(both, held, MODEL, today=TODAY)
    assert f"its ledger holds {days[8].isoformat()}, in learn.excluded_days" in found.lines[0]
    # the step drops the day whole and replays the rest
    out = run(step_inputs(tmp_path, host, config=row_out))
    assert (
        f"predict read-labels: switch bus_timing: SWITCHED off: {days[8]} excluded "
        "(learn.excluded_rows); the ledger without it ends off"
    ) in out
    state = state_of(host)["bus_timing"]
    assert state.served == "off"
    assert days[8] not in {e.day for e in state.ledger}
    assert len(state.ledger) == 9
    assert live_switch.served_arms(
        row_out, host.read(f"v1/{live_switch.SWITCH_PATH}"), MODEL, today=TODAY
    ).arms == {"bus_timing": "off"}
    # it is never counted again while listed: a second run says nothing of it
    out = run(step_inputs(tmp_path, host, config=row_out))
    assert not any("excluded" in line for line in out), out
    # a run with a day of each kind names both lists
    mixed = with_lists((days[2],), ((days[8], "2900001"), (days[5], "2900002")))
    out = run(step_inputs(tmp_path, host, config=mixed))
    assert any(
        f"switch bus_timing: {days[2]}, {days[5]} excluded (learn.excluded_days, "
        "learn.excluded_rows): dropped from the ledger; served off, " in line
        for line in out
    ), out
    assert len(state_of(host)["bus_timing"].ledger) == 7


def test_an_on_reached_on_a_day_later_excluded_replays_off_and_a_robust_on_stays(
    tmp_path: Path,
) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(12)
    for day in days[:10]:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    run(step_inputs(tmp_path, host))
    assert state_of(host)["bus_timing"].served == "on"
    excluded = CONFIG.model_copy(update={"learn": replace_learn(CONFIG, (days[8],))})
    out = run(step_inputs(tmp_path, host, config=excluded))
    assert (
        f"predict read-labels: switch bus_timing: SWITCHED off: {days[8]} excluded "
        "(learn.excluded_days); the ledger without it ends off"
    ) in out
    state = state_of(host)["bus_timing"]
    assert state.served == "off"
    assert days[8] not in {e.day for e in state.ledger}
    assert live_switch.served_arms(
        excluded, host.read(f"v1/{live_switch.SWITCH_PATH}"), MODEL, today=TODAY
    ).arms == {"bus_timing": "off"}
    # a robust ON: twelve dates, one early one excluded, stays on
    root = tmp_path / "robust"
    host2 = Host(root / "host")
    started(root, host2)
    for day in days:
        storm_day(root / "reads", root / "frozen", day, 0.05)
    run(step_inputs(root, host2))
    assert state_of(host2)["bus_timing"].served == "on"
    early = CONFIG.model_copy(update={"learn": replace_learn(CONFIG, (days[2],))})
    out = run(step_inputs(root, host2, config=early))
    assert not any("SWITCHED" in line for line in out)
    assert state_of(host2)["bus_timing"].served == "on"


def test_two_behind_and_a_clear_switch_off_with_their_lines(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(16)
    for day in days[:10]:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    run(step_inputs(tmp_path, host))
    for day in days[10:16]:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, -0.2)
    out = run(step_inputs(tmp_path, host))
    lines = [line for line in out if "SWITCHED" in line]
    assert lines, out
    assert lines[0].startswith("predict read-labels: switch bus_timing: SWITCHED off")
    assert lines[0].endswith("timing_after_bus 1 serves from this run's passes")
    assert state_of(host)["bus_timing"].served == "off"


# --- a second term plugs in -------------------------------------------------------------------


def plugged(config: PredictConfig = CONFIG) -> PredictConfig:
    """``config`` with a second term registered beside the bus term: its arms are call time's
    ``serve`` names (``off`` and ``on``, a name, not a number), it freezes no variant, and it
    reads the d0_0630 freeze (CALL-TIME-2's shape)."""
    body = config.model_dump(mode="json")
    block = dict(body["live_score"]["switch_bus_timing"])
    del block["frozen_key"]
    block.update(
        arm_block="call_time", arm_key="serve", arm_off="off", arm_on="on", freeze="d0_0630",
        scope=["call_time"], classes=["advisory", "warning", "cold"],
    )  # fmt: skip
    body["live_score"]["switch_fake"] = block
    return PredictConfig.model_validate(body)


def test_a_second_term_with_name_arms_a_fitted_arm_strata_sums_and_an_extra_check_plugs_in(  # noqa: PLR0915
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gains: dict[date, float] = {}
    fitted: list[tuple[date, int]] = []

    def groups(inputs: live_switch.DayInputs) -> list[Group]:
        # a fitted arm fits on the dates before D only: D itself and later are refused
        assert inputs.earlier is not None
        assert inputs.config is not None
        assert inputs.reads == tmp_path / "reads"
        assert all(d < inputs.day for d in inputs.before)
        assert all(e.day < inputs.day for e in inputs.ledger)
        for wanted in (inputs.day, inputs.day + timedelta(days=1)):
            with pytest.raises(ValueError, match="before"):
                inputs.earlier(wanted)
        fitted.append((inputs.day, sum(len(inputs.earlier(d)) for d in inputs.before)))
        gain = gains[inputs.day]
        return [
            replace(g, stratum=band, sums={"expected_on": 12.25, "expected_off": 11.5})
            for g in synthetic_groups(inputs.day, gain, states=("10", "11", "12"))
            for band in ("early", "late")
        ]

    def checks(
        _config: PredictConfig, rule: live_switch.Rule, ledger: Sequence[LedgerDate]
    ) -> tuple[str, ...]:
        expected = sum(g.sums["expected_on"] for e in ledger for g in e.groups)
        return ("its own check",) if expected < (rule.on_after + 8) * 4 * 12.25 else ()

    monkeypatch.setitem(live_switch.TERMS, "fake", Term(groups=groups, checks=checks))
    config = plugged()
    rule = live_switch.rules(config)["fake"]
    assert (rule.arm_off, rule.arm_on, rule.frozen_key, rule.freeze) == (
        "off", "on", None, "d0_0630",
    )  # fmt: skip
    # the committed value must be the default arm's, as stored: "off" (no number stands in)
    body = config.model_dump(mode="json")
    body["live_score"]["call_time"]["serve"] = "on"
    with pytest.raises(ValueError, match=r"off only|not the default arm's"):
        PredictConfig.model_validate(body)
    # a term whose code freezes no shadow takes no frozen_key, and one that does needs it
    body = config.model_dump(mode="json")
    body["live_score"]["switch_fake"]["frozen_key"] = "ct"
    with pytest.raises(ValueError, match="frozen_key names the shadow"):
        PredictConfig.model_validate(body)
    # serving: the arm reaches only the copy the anchor is built from
    served = live_switch.served_config(config, {"fake": "on"})
    assert served.live_score["call_time"]["serve"] == "on"
    assert config.live_score["call_time"]["serve"] == "off"
    assert live_score_sha256(served) != live_score_sha256(config)
    host = Host(tmp_path / "host")
    write_labels(tmp_path / "reads", FIRST - timedelta(days=3), {})
    run(step_inputs(tmp_path, host, config=config))
    days = school_days(13)
    for day in days:
        gains[day] = 0.05
        write_labels(tmp_path / "reads", day, {"1000001": (1, "no_school")})
        write_frozen(tmp_path / "frozen", day, [], freeze="d0_0630")
    out = run(step_inputs(tmp_path, host, config=config))
    evaluations = [line for line in out if "switch fake: " in line and " evaluation " in line]
    assert len(evaluations) == 13
    assert "its own check" in evaluations[9]
    assert any("switch fake: SWITCHED on" in line and "serve on serves" in line for line in out)
    assert [n for _day, n in fitted] == list(range(13))  # one labeled row a date before D
    state = state_of(host)["fake"]
    assert state.served == "on"
    assert {g.stratum for e in state.ledger for g in e.groups} == {"early", "late"}
    assert {g.sums["expected_on"] for e in state.ledger for g in e.groups} == {12.25}
    # the bus term beside it is untouched (no rows of its own here)
    assert state_of(host)["bus_timing"].ledger == ()
    found = live_switch.served_arms(
        config, host.read(f"v1/{live_switch.SWITCH_PATH}"), MODEL, today=TODAY
    )
    assert found.arms == {"bus_timing": "off", "fake": "on"}
    # S2 (critic r2): a term served outside the anchor reads its value from the run's served
    # arms (the pass's switch), never from the committed config, which holds the default
    assert live_switch.served_value(found, config, "fake") == "on"
    assert live_switch.served_value(None, config, "fake") == "off"
    assert live_switch.served_value(found, config, "bus_timing") == 1.0
    with pytest.raises(ValueError, match="no registered term"):
        live_switch.served_value(found, config, "other")
    # the frozen record: every header names both terms; only the bus term freezes a variant
    from snowlight.predict import cli  # noqa: PLC0415

    assert [s.name for s in cli.frozen_shadows(config, found)] == ["bus_timing"]
    assert [(h.name, h.arm) for h in cli.frozen_heads(config, found)] == [
        ("bus_timing", "off"), ("fake", "on"),
    ]  # fmt: skip


def test_a_group_s_sums_and_counts_read_back_and_out_of_range_ones_do_not() -> None:
    group = replace(
        synthetic_groups(FIRST, 0.01)[0], counts={"dropped": 2}, sums={"expected": 3.75}
    )
    assert Group.of(FIRST, json.loads(json.dumps(group.as_json()))) == group
    for key, value in (
        ("n", 10**400), ("n", -1), ("n", True), ("cll_on", 1e300), ("cll_on", 10**400),
        ("cll_on", float("nan")), ("sums", {"x": "1"}), ("counts", {"x": 1.5}),
    ):  # fmt: skip
        body = dict(group.as_json())
        body[key] = value
        with pytest.raises(ValueError, match=r"does not read|do not hold"):
            Group.of(FIRST, body)


def test_serving_takes_the_default_on_a_state_that_overflows_or_nests_too_deep() -> None:
    ledger = winter([0.01] * 12)
    body = json.loads(stored("on", ledger=ledger))
    body["terms"]["bus_timing"]["ledger"][0]["groups"][0]["n"] = 10**400
    for data in (json.dumps(body).encode(), b"[" * 100_000 + b"]" * 100_000):
        found = live_switch.served_arms(CONFIG, data, MODEL, today=TODAY)
        assert found.arms == {"bus_timing": "off"}
        assert found.lines[0].startswith("::warning::switch: bus_timing served off, the committed")
    # a replay that fails serves the default too
    term = live_switch.TERMS["bus_timing"]

    def broken(*_args: object) -> tuple[str, ...]:
        raise OverflowError

    live_switch.TERMS["bus_timing"] = replace(term, checks=broken)
    try:
        found = live_switch.served_arms(CONFIG, stored("on", ledger=ledger), MODEL, today=TODAY)
    finally:
        live_switch.TERMS["bus_timing"] = term
    assert found.arms == {"bus_timing": "off"}
    assert found.lines == (
        "::warning::switch: bus_timing served off, the committed default (its ledger does not "
        "replay (OverflowError))",
    )


def test_a_read_back_that_fails_after_a_write_says_it_was_written(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    day = school_days(1)[0]
    storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    read = host.read
    writes = host.writes

    def flaky(key: str) -> bytes | None:
        if host.writes > writes:  # once written, the read-back fails
            raise PublishError("read: HTTP 502")
        return read(key)

    host.read = flaky  # type: ignore[method-assign]
    out = run(step_inputs(tmp_path, host))
    host.read = read  # type: ignore[method-assign]
    assert out[-1].startswith(
        "::warning::predict read-labels: switch: wrote predictions/switch.json ("
    )
    assert out[-1].endswith(" B), read back failed (PublishError)")
    assert not any("not written" in line for line in out)
    assert state_of(host)["bus_timing"].through == day
    # the marker is not rewritten: the days are kept until a read-back
    assert frozen.read_marker(tmp_path / "frozen") == FIRST - timedelta(days=3)


def test_the_switch_never_changes_the_step_s_labels_audit_added_or_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from predict import test_live_read as lr  # noqa: PLC0415
    from predict.test_learn import Host as LearnHost  # noqa: PLC0415
    from snowlight.predict import read_cli  # noqa: PLC0415

    now = world_utc("2026-01-08T06:00:00")
    found: dict[bool, tuple[int, bytes | None, dict[str, bytes], str, str]] = {}
    for on in (False, True):
        host = LearnHost()
        folder = tmp_path / f"reads-{on}"
        outputs = tmp_path / f"outputs-{on}"
        run = replace(
            lr.read_run(host, folder, now),
            frozen=tmp_path / f"frozen-{on}",
            model_sha256=MODEL,
            switch=on,
            outputs=outputs,
        )
        code = read_cli.read_once(run)
        out = capsys.readouterr().out
        files = {
            str(path.relative_to(folder)): path.read_bytes()
            for path in sorted(folder.rglob("*"))
            if path.is_file() and path.name != "summary.json"
        }
        found[on] = (
            code,
            host.files.get("v1/predictions/read-audit.json"),
            files,
            outputs.read_text(),
            out,
        )
        assert ("v1/predictions/switch.json" in host.files) is on
    assert found[True][:4] == found[False][:4]
    said = found[True][4].splitlines()
    switch = next(i for i, line in enumerate(said) if "switch bus_timing (served off)" in line)
    calls = [i for i, line in enumerate(said) if "call time (off)" in line]
    assert calls
    assert switch < min(calls)


def world_utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_a_run_reads_the_state_once_and_says_what_it_serves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from snowlight.predict import cli  # noqa: PLC0415
    from snowlight.predict.publish import Mode  # noqa: PLC0415

    found = cli.served_switch(
        CONFIG, None, Mode.OFF, MODEL, today=TODAY, folder=tmp_path / "frozen"
    )
    assert found.arms == {"bus_timing": "off"}
    assert capsys.readouterr().out == (
        "predict: switch: bus_timing served off, the committed default (publishing is off)\n"
    )

    class Broken:
        def read(self, key: str) -> bytes | None:
            raise PublishError(f"read {key}: HTTP 502")

    found = cli.served_switch(
        CONFIG,
        Broken(),  # type: ignore[arg-type]
        Mode.ON,
        MODEL,
        today=TODAY,
        folder=tmp_path / "frozen",
    )
    assert found.arms == {"bus_timing": "off"}
    err = capsys.readouterr().err
    assert (
        "switch: bus_timing served off, the committed default (predictions/switch.json "
        "unreadable (PublishError))"
    ) in err
    host = Host(tmp_path / "host")
    host.write({f"v1/{live_switch.SWITCH_PATH}": stored("on", ledger=winter([0.01] * 12))})
    found = cli.served_switch(CONFIG, host, Mode.ON, MODEL, today=TODAY, folder=tmp_path / "frozen")
    assert found.arms == {"bus_timing": "on"}
    assert "predict: switch: bus_timing served on (switch.json through" in capsys.readouterr().out
    # the frozen headers get each term's arm and key, and the bus term's shadow its settings
    [shadow] = cli.frozen_shadows(CONFIG, found)
    assert (shadow.name, shadow.key, shadow.freeze, shadow.arm) == (
        "bus_timing",
        "bt",
        "d0_0507",
        "on",
    )
    assert [s.timing_after_bus for s in shadow.settings] == [1.0, 0.95]
    assert cli.frozen_heads(CONFIG, found) == (
        frozen.Head("bus_timing", "on", KEY.term_sha256, MODEL),
    )
    assert cli.frozen_shadows(CONFIG, None) == ()
    assert cli.frozen_heads(CONFIG, None) == ()


# --- what a term's checks see, strata, limits and exclusions (critic r2) -------------------------


def quiet_band(day: date, klass: str, n: int = 20, expected: float = 3.0) -> Group:
    """A SYNTHETIC band of ``n`` rows at risk that all stayed open, ``expected`` closings
    expected under the on arm: not informative, so never scored, but a term's check reads
    it."""
    return Group(
        day=day, klass=klass, stratum="quiet", n=n, closed=0, cll_on=0.0, cll_off=0.0,
        pairs=0, wins2_on=0, wins2_off=0, moved=True, states=("10",),
        sums={"observed": 0.0, "expected_on": expected},
    )  # fmt: skip


def calibration(
    config: PredictConfig, _rule: live_switch.Rule, ledger: Sequence[LedgerDate]
) -> tuple[str, ...]:
    """A SYNTHETIC calibration check over every row the term built (CALL-TIME-2's shape):
    observed less expected closings, refused past the rows over a registered number."""
    groups = [g for e in ledger for g in e.groups]
    gap = sum(g.sums["observed"] - g.sums["expected_on"] for g in groups)
    rows = sum(g.n for g in groups)
    least = config.live_score["call_time"]["stratum_min_rows"]
    assert isinstance(least, int)
    return ("calibration off",) if abs(gap) > rows / least else ()


def test_a_term_s_check_sees_every_group_it_built_and_its_registered_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # B1 (critic r2): a date's groups that are not informative are kept for the term's own
    # checks (scored nowhere), and a date holding only such a group still enters the ledger
    def groups(inputs: live_switch.DayInputs) -> list[Group]:
        if inputs.day == days[3]:
            return [quiet_band(inputs.day, "advisory")]
        return [
            *(
                replace(g, stratum="band", sums={"observed": 20.0, "expected_on": 20.0})
                for g in synthetic_groups(inputs.day, 0.05, states=("10", "11", "12"))
            ),
            *(quiet_band(inputs.day, k) for k in ("advisory", "warning")),
        ]

    monkeypatch.setitem(live_switch.TERMS, "fake", Term(groups=groups, checks=calibration))
    days = school_days(14)
    found: dict[int, list[str]] = {}
    for least in (100, 10):
        root = tmp_path / str(least)
        body = plugged().model_dump(mode="json")
        body["live_score"]["call_time"]["stratum_min_rows"] = least
        config = PredictConfig.model_validate(body)
        host = Host(root / "host")
        write_labels(root / "reads", FIRST - timedelta(days=3), {})
        run(step_inputs(root, host, config=config))
        for day in days:
            write_labels(root / "reads", day, {"1000001": (1, "no_school")})
            write_frozen(root / "frozen", day, [], freeze="d0_0630")
        found[least] = run(step_inputs(root, host, config=config))
        state = state_of(host)["fake"]
        assert [e.day for e in state.ledger] == days
        assert len(state.ledger[3].groups) == 1
        assert not state.ledger[3].informative
        assert len(state.evaluations) == 13  # the quiet date is no evaluation
        assert sum(len(e.groups) for e in state.ledger) == 13 * 4 + 1
    # every row: observed less expected -6 a date over 120 rows a date. Over 1.2 a date (100
    # rows a unit), the check fails each time; over 12 (10 a unit), it never does
    evaluations = [
        line for line in found[100] if "switch fake: " in line and " evaluation " in line
    ]
    assert all("calibration off" in line for line in evaluations)
    assert not any("SWITCHED on" in line for line in found[100])
    assert any("switch fake: SWITCHED on" in line for line in found[10])
    # the informative groups alone are what is scored and counted
    line = next(line for line in found[10] if "switch fake (served" in line)
    assert "13 of 8 moved dates, 26 of 10 date-classes, 3 of 3 states, 1,040 of 300 rows" in line


def stratified(ledger: Sequence[LedgerDate], bands: int = 5) -> list[LedgerDate]:
    """``ledger`` with each group split into ``bands`` strata of equal rows and sums."""
    found = []
    for entry in ledger:
        split = []
        for g in entry.groups:
            n, m = g.n // bands, g.closed // bands
            for b in range(bands):
                split.append(
                    replace(
                        g, stratum=f"b{b}", n=n, closed=m, pairs=m * (n - m),
                        cll_on=g.cll_on / bands, cll_off=g.cll_off / bands,
                        wins2_on=g.wins2_on // bands, wins2_off=g.wins2_off // bands,
                    )
                )  # fmt: skip
        found.append(replace(entry, groups=tuple(split)))
    return found


def test_a_stratified_ledger_counts_its_date_classes_as_the_same_unstratified_one() -> None:
    # B2 (critic r2): a date-class is a distinct (date, class), however many strata
    ledger = winter([0.01, 0.02, -0.01])
    plain = live_switch.evaluate(RULE, ledger, 3)
    banded = live_switch.evaluate(RULE, stratified(ledger), 3)
    assert (banded.moved_dates, banded.date_classes, banded.states, banded.rows) == (
        plain.moved_dates, plain.date_classes, plain.states, plain.rows,
    ) == (3, 6, 3, 240)  # fmt: skip
    assert [(c.rows, c.moved, c.binding) for c in banded.classes] == [
        (c.rows, c.moved, c.binding) for c in plain.classes
    ] == [(120, 3, True), (120, 3, True)]  # fmt: skip
    assert banded.point == pytest.approx(plain.point)
    assert banded.lower == pytest.approx(plain.lower)
    # two moved dates of a class over 100 rows do not bind it, in 5 strata or not
    two = live_switch.evaluate(RULE, stratified(winter([0.01] * 2), 5), 2)
    assert [c.binding for c in two.classes] == [False, False]
    assert two.date_classes == 4
    assert "4 of 10 date-classes" in live_switch.short_of_evidence(RULE, two)
    state = TermState(KEY.term_sha256, MODEL, 1, "off", 0, 0, ledger[-1].day, tuple(ledger))
    count = live_switch._Count()
    assert live_switch.counts_line(RULE, state, count) == live_switch.counts_line(
        RULE, replace(state, ledger=tuple(stratified(ledger))), count
    )


def durations(clock: Clock, seconds: Sequence[float]) -> Callable[..., Any]:
    """``_count_day`` taking each of ``seconds`` in turn on ``clock`` (the last one after)."""
    count = live_switch._count_day
    left = list(seconds)

    def slow(*args: Any) -> Any:
        clock.at += left.pop(0) if len(left) > 1 else left[0]
        return count(*args)

    return slow


def test_slow_dates_never_stop_a_backlog_and_a_date_past_both_limits_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # S1 (critic r2): at 14 s a date, a date starts only while the longest so far ends by
    # 55 s: 3 dates a run (they end at 42 s), each run written
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(12)
    for day in days:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    for done in (3, 6, 9, 12):
        clock = Clock(0.0)
        monkeypatch.setattr(live_switch, "_count_day", durations(clock, [14.0]))
        out = run(step_inputs(tmp_path, host, clock=clock))
        assert out[-1].endswith(" B), read back")
        assert state_of(host)["bus_timing"].through == days[done - 1]
    # one date that crosses both limits (8 s to 78 s) is kept, and the write it made late
    # goes through with every date counted; the next run counts the rest
    root = tmp_path / "late"
    host = Host(root / "host")
    started(root, host)
    for day in days[:5]:
        storm_day(root / "reads", root / "frozen", day, 0.05)
    clock = Clock(0.0)
    monkeypatch.setattr(live_switch, "_count_day", durations(clock, [4.0, 4.0, 70.0, 4.0]))
    out = run(step_inputs(root, host, clock=clock))
    assert (
        "predict read-labels: switch: a date counted ran to 78 s, past 55 s: written through "
        "every date counted"
    ) in out
    assert out[-1].endswith(" B), read back")
    assert state_of(host)["bus_timing"].through == days[2]
    # the run's first date alone past both limits is written too
    clock = Clock(30.0)
    monkeypatch.setattr(live_switch, "_count_day", durations(clock, [60.0]))
    out = run(step_inputs(root, host, clock=clock))
    assert "a date counted ran to 90 s, past 55 s" in " ".join(out)
    assert state_of(host)["bus_timing"].through == days[3]
    # a late write with no date past the count limit is refused (the host read ran long,
    # and an exclusion changes the state)
    storm_day(root / "reads", root / "frozen", days[5], 0.05)
    monkeypatch.undo()
    clock = Clock(44.0)
    read = host.read

    def slow_read(key: str) -> bytes | None:
        clock.at = 66.0
        return read(key)

    host.read = slow_read  # type: ignore[method-assign]
    excluded = CONFIG.model_copy(update={"learn": replace_learn(CONFIG, (days[0],))})
    out = run(step_inputs(root, host, config=excluded, clock=clock))
    host.read = read  # type: ignore[method-assign]
    assert out[-1] == "predict read-labels: switch: skipped past 65 s of the step: nothing written"


def test_an_exclusion_that_moves_only_a_streak_says_so_and_a_fault_warns_once_written(
    tmp_path: Path,
) -> None:
    # S2 (critic r2, decision rule): 9 confident dates are off with ON streak 2; excluding
    # the 9th leaves ON streak 1: a plain line, no fault warning
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(9)
    for day in days:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    run(step_inputs(tmp_path, host))
    state = state_of(host)["bus_timing"]
    assert (state.served, state.on_streak, state.off_streak) == ("off", 2, 0)
    excluded = CONFIG.model_copy(update={"learn": replace_learn(CONFIG, (days[8],))})
    out = run(step_inputs(tmp_path, host, config=excluded))
    assert not any(line.startswith("::warning::") for line in out), out
    assert (
        f"predict read-labels: switch bus_timing: {days[8]} excluded (learn.excluded_days): "
        "dropped from the ledger; served off, ON streak 2 to 1"
    ) in out
    assert (state_of(host)["bus_timing"].on_streak, len(state_of(host)["bus_timing"].ledger)) == (
        1, 8,
    )  # fmt: skip
    # 7 dates are short of evidence (streak 0); one more excluded changes nothing more
    more = excluded
    for dropped, said in ((days[0], "ON streak 1 to 0"), (days[1], "ON streak 0 unchanged")):
        more = CONFIG.model_copy(
            update={"learn": replace_learn(CONFIG, (days[8], days[0], dropped))}
        )
        out = run(step_inputs(tmp_path, host, config=more))
        assert (
            f"predict read-labels: switch bus_timing: {dropped} excluded (learn.excluded_days): "
            f"dropped from the ledger; served off, {said}"
        ) in out
        assert not any(line.startswith("::warning::") for line in out), out
    # S2 (critic r2, serving safety): a stored state that is not its replay, with no
    # exclusion, warns; the warning is held until the write and says when nothing is written
    key = f"v1/{live_switch.SWITCH_PATH}"
    edited = replace(state_of(host)["bus_timing"], on_streak=2)
    host.write({key: live_switch.state_bytes({"bus_timing": edited})})
    host.fail = True
    out = run(step_inputs(tmp_path, host, config=more))
    host.fail = False
    warned = [line for line in out if "not the replay of its ledger" in line]
    assert warned == [
        "::warning::predict read-labels: switch bus_timing: the stored arm, streaks or "
        "evaluations are not the replay of its ledger: the replay's "
        f"({edited.served}, {len(edited.evaluations)} evaluations) would be written (not written)"
    ]
    out = run(step_inputs(tmp_path, host, config=more))
    assert [line for line in out if "not the replay of its ledger" in line] == [
        "::warning::predict read-labels: switch bus_timing: the stored arm, streaks or "
        "evaluations are not the replay of its ledger: the replay's "
        f"({edited.served}, {len(edited.evaluations)} evaluations) is written"
    ]
    assert out[-1].endswith(" B), read back")


def test_a_group_or_clause_carrying_a_leaid_or_list_text_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # S6 (critic r2): counts and numbers only, whatever a term's code makes
    group = synthetic_groups(FIRST, 0.01)[0]
    for bad in (
        {"states": ("3600001",)}, {"states": ("NY",)}, {"stratum": "Big Band"},
        {"stratum": "l3600001"}, {"counts": {"3600001": 1}}, {"sums": {"two words": 1.0}},
        {"sums": {"x3600001": 1.0}},
        {"klass": "chain"},
    ):  # fmt: skip
        with pytest.raises(ValueError, match="group's"):
            replace(group, **bad).check()
    for text in ("district 3600001 dark", "Snow Hill closed", "x" * 81, 7):
        with pytest.raises(ValueError, match="clause"):
            live_switch.clauses([text])
    assert live_switch.clauses(["calibration off (-0.0121)"]) == ("calibration off (-0.0121)",)
    # a time band (CALL-TIME-2's strata) and a short mixed-case key are counts' names
    replace(group, stratum="06:30", sums={"E_on": 3.0}, counts={"O": 2}).check()
    # in the step: a date whose group carries a LEAID stops the count, and nothing of it is
    # written; a check naming one writes nothing, and serving takes the default

    def leaky(inputs: live_switch.DayInputs) -> list[Group]:
        return [replace(g, states=("1000001",)) for g in synthetic_groups(inputs.day, 0.05)]

    monkeypatch.setitem(live_switch.TERMS, "fake", Term(groups=leaky))
    config = plugged()
    host = Host(tmp_path / "host")
    write_labels(tmp_path / "reads", FIRST - timedelta(days=3), {})
    run(step_inputs(tmp_path, host, config=config))
    write_labels(tmp_path / "reads", FIRST, {"1000001": (1, "no_school")})
    write_frozen(tmp_path / "frozen", FIRST, [], freeze="d0_0630")
    out = run(step_inputs(tmp_path, host, config=config))
    assert (
        f"::warning::predict read-labels: switch fake: {FIRST} does not read (ValueError): "
        "counting stops before it (learn.excluded_days passes it)"
    ) in out
    assert b"1000001" not in (host.read(f"v1/{live_switch.SWITCH_PATH}") or b"")

    def named(*_args: object) -> tuple[str, ...]:
        return ("district 1000001 dark",)

    monkeypatch.setitem(
        live_switch.TERMS,
        "fake",
        Term(groups=lambda i: synthetic_groups(i.day, 0.05), checks=named),
    )
    before = host.read(f"v1/{live_switch.SWITCH_PATH}")
    out = run(step_inputs(tmp_path, host, config=config))
    assert out[-1] == "::warning::predict read-labels: switch: ValueError: nothing written"
    assert host.read(f"v1/{live_switch.SWITCH_PATH}") == before


# --- a forged through or evaluations, a lost answer, a lagging host, replay cost (critic r3) ---


def test_serving_refuses_a_through_after_the_run_s_date_and_evaluations_not_the_replay_s() -> None:
    ledger = winter([0.01] * 12)
    good = stored("on", ledger=ledger)
    on_it = live_switch.served_arms(CONFIG, good, MODEL, today=ledger[-1].day)
    assert on_it.arms == {"bus_timing": "on"}
    assert on_it.lines == (
        f"switch: bus_timing served on (switch.json through {ledger[-1].day}, 12 evaluations)",
    )
    for data, today in (
        (stored("on", ledger=ledger, through=date(2030, 1, 1)), TODAY),
        (good, ledger[-1].day - timedelta(days=1)),
    ):
        found = live_switch.served_arms(CONFIG, data, MODEL, today=today)
        through = live_switch.parse_state(data)["bus_timing"].through
        assert found.arms == {"bus_timing": "off"}
        assert found.lines == (
            "::warning::switch: bus_timing served off, the committed default (through "
            f"{through} is after the run's date)",
        )
    # a hand-cut evaluations count, a dropped one, one number edited, none: never served
    evaluations = live_switch.parse_state(good)["bus_timing"].evaluations
    assert len(evaluations) == 12
    for cut in (
        evaluations[:3],
        evaluations[1:],
        (*evaluations[:-1], {**evaluations[-1], "point": 0.5}),
        (*evaluations[:-1], {**evaluations[-1], "number": 99}),
        (),
    ):
        found = live_switch.served_arms(
            CONFIG, stored("on", ledger=ledger, evaluations=cut), MODEL, today=TODAY
        )
        assert found.arms == {"bus_timing": "off"}
        assert found.lines == (
            "::warning::switch: bus_timing served off, the committed default (not the replay "
            "of its ledger)",
        )


def test_the_step_repairs_a_through_after_the_run_s_date_and_the_marker_never_passes_it(
    tmp_path: Path,
) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    key = f"v1/{live_switch.SWITCH_PATH}"
    days = school_days(4)
    for day in days[:2]:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    run(step_inputs(tmp_path, host))
    state = state_of(host)["bus_timing"]
    assert state.through == days[1]
    # a through after the run's date: serving refuses it, and the step repairs it to its
    # ledger's last date (said once written) and counts on from there
    host.write(
        {key: live_switch.state_bytes({"bus_timing": replace(state, through=date(2030, 1, 1))})}
    )
    found = live_switch.served_arms(CONFIG, host.read(key), MODEL, today=TODAY)
    assert found.lines[0].startswith("::warning::")
    assert "after the run's date" in found.lines[0]
    storm_day(tmp_path / "reads", tmp_path / "frozen", days[2], 0.05)
    # L1 labeling a date after the run's date is never counted
    write_labels(tmp_path / "reads", TODAY + timedelta(days=3), {})
    out = run(step_inputs(tmp_path, host))
    assert (
        "::warning::predict read-labels: switch bus_timing: through 2030-01-01 is after the "
        f"run's date: repaired to {days[1]} (its ledger's last date)"
    ) in out
    assert out[-1].endswith(" B), read back")
    fixed = state_of(host)["bus_timing"]
    assert fixed.through == days[2]
    assert [e.day for e in fixed.ledger] == days[:3]
    assert frozen.read_marker(tmp_path / "frozen") == days[2]
    assert live_switch.served_arms(CONFIG, host.read(key), MODEL, today=TODAY).lines == (
        f"switch: bus_timing served off (switch.json through {days[2]}, 3 evaluations)",
    )
    # nothing written: said so, and the marker stays
    host.write(
        {key: live_switch.state_bytes({"bus_timing": replace(fixed, through=date(2030, 1, 1))})}
    )
    host.fail = True
    out = run(step_inputs(tmp_path, host))
    host.fail = False
    assert (
        "::warning::predict read-labels: switch bus_timing: through 2030-01-01 is after the "
        f"run's date: would repair to {days[2]} (its ledger's last date) (not written)"
    ) in out
    assert frozen.read_marker(tmp_path / "frozen") == days[2]
    # a ledger holding a date after the run's date is restarted over
    late = replace(fixed.ledger[-1], day=date(2030, 1, 1))
    forged = replace(fixed, through=date(2030, 1, 1), ledger=(*fixed.ledger, late))
    host.write({key: live_switch.state_bytes({"bus_timing": forged})})
    out = run(step_inputs(tmp_path, host))
    assert (
        "::warning::predict read-labels: switch bus_timing: through 2030-01-01 is after the "
        "run's date, and so is its ledger's 2030-01-01: restarted over it"
    ) in out
    restarted = state_of(host)["bus_timing"]
    assert (restarted.ledger, restarted.through, restarted.served) == ((), days[2], "off")
    assert frozen.read_marker(tmp_path / "frozen") == days[2]
    # an empty ledger's is repaired to the newest labeled date
    host.write(
        {key: live_switch.state_bytes({"bus_timing": replace(restarted, through=date(2030, 1, 1))})}
    )
    out = run(step_inputs(tmp_path, host))
    assert f"repaired to {days[2]} (the newest labeled date)" in " ".join(out)
    # a through after L1's newest labeled date but not the run's: warned, at once
    host.write({key: live_switch.state_bytes({"bus_timing": replace(fixed, through=TODAY)})})
    host.fail = True
    out = run(step_inputs(tmp_path, host))
    host.fail = False
    assert (
        f"::warning::predict read-labels: switch bus_timing: through {TODAY} is after L1's "
        f"newest labeled date, {days[2]}"
    ) in out


def test_the_step_rewrites_evaluations_that_are_not_the_replay_s(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    key = f"v1/{live_switch.SWITCH_PATH}"
    for day in school_days(3):
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    run(step_inputs(tmp_path, host))
    state = state_of(host)["bus_timing"]
    host.write(
        {
            key: live_switch.state_bytes(
                {"bus_timing": replace(state, evaluations=state.evaluations[:1])}
            )
        }
    )
    out = run(step_inputs(tmp_path, host))
    assert (
        "::warning::predict read-labels: switch bus_timing: the stored arm, streaks or "
        "evaluations are not the replay of its ledger: the replay's (off, 3 evaluations) is "
        "written"
    ) in out
    assert state_of(host)["bus_timing"] == state


class LostAnswer(Host):
    """A host whose write lands (or lands other bytes) and whose answer is then lost."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.lose = False
        self.other: bytes | None = None
        self.read_fails = False

    def write(self, files: Mapping[str, bytes]) -> None:
        if not self.lose:
            super().write(files)
            return
        landed = dict.fromkeys(files, self.other) if self.other is not None else files
        super().write(landed)
        raise PublishError("write: ReadTimeout")

    def read(self, key: str) -> bytes | None:
        if self.read_fails and self.writes:
            raise PublishError("read: HTTP 502")
        return super().read(key)


def test_a_write_whose_answer_is_lost_is_read_once_and_said_as_it_is(tmp_path: Path) -> None:
    host = LostAnswer(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(3)
    storm_day(tmp_path / "reads", tmp_path / "frozen", days[0], 0.05)
    host.lose = True
    out = run(step_inputs(tmp_path, host))
    # it landed: every line as written, one warning, the marker rewritten
    assert not any("not written" in line for line in out), out
    assert out[-1].startswith(
        "::warning::predict read-labels: switch: the write's answer was lost: "
        "predictions/switch.json ("
    )
    assert out[-1].endswith(" B) read back as written")
    assert state_of(host)["bus_timing"].through == days[0]
    assert frozen.read_marker(tmp_path / "frozen") == days[0]
    # other bytes landed: unknown, nothing said as written, the marker kept
    storm_day(tmp_path / "reads", tmp_path / "frozen", days[1], 0.05)
    host.other = b'{"schema_version":1,"terms":{}}\n'
    out = run(step_inputs(tmp_path, host))
    assert out[-1] == (
        "::warning::predict read-labels: switch: PublishError: the write's outcome is unknown "
        "(the host holds other bytes): nothing is said as written and the frozen days are kept"
    )
    assert all(line.endswith("(not written)") for line in out[:-1]), out
    assert frozen.read_marker(tmp_path / "frozen") == days[0]
    # the read-back fails: unknown too
    host.other = None
    host.lose = False
    host.write({f"v1/{live_switch.SWITCH_PATH}": b'{"schema_version":1,"terms":{}}\n'})
    host.lose = True
    host.read_fails = True
    host.writes = 0
    out = run(step_inputs(tmp_path, host))
    host.read_fails = False
    assert out[-1].startswith(
        "::warning::predict read-labels: switch: PublishError: the write's outcome is unknown "
        "(the read-back failed (PublishError))"
    )
    assert frozen.read_marker(tmp_path / "frozen") == days[0]


class Replica:
    """A host whose first reads return older bytes (a replica that has not caught up)."""

    def __init__(self, *found: bytes | None) -> None:
        self.found = list(found)
        self.reads = 0

    def read(self, key: str) -> bytes | None:  # noqa: ARG002 - the host's protocol
        self.reads += 1
        return self.found.pop(0) if len(self.found) > 1 else self.found[0]


def test_serving_reads_a_state_behind_the_frozen_marker_once_more(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from snowlight.predict import cli  # noqa: PLC0415
    from snowlight.predict.publish import Mode  # noqa: PLC0415

    ledger = winter([0.01] * 12)
    old, new = stored("off", on=2, ledger=ledger[:9]), stored("on", ledger=ledger)
    folder = tmp_path / "frozen"

    def served(host: Replica) -> tuple[live_switch.Served, str, str]:
        found = cli.served_switch(CONFIG, host, Mode.ON, MODEL, today=TODAY, folder=folder)  # type: ignore[arg-type]
        said = capsys.readouterr()
        return found, said.out, said.err

    # no marker: one read
    host = Replica(old, new)
    assert served(host)[0].arms == {"bus_timing": "off"}
    assert host.reads == 1
    frozen.write_marker(folder, ledger[-1].day)
    # behind once: read again, served the newer, no warning
    host = Replica(old, new)
    found, out, err = served(host)
    assert (found.arms, host.reads, err) == ({"bus_timing": "on"}, 2, "")
    assert f"served on (switch.json through {ledger[-1].day}, 12 evaluations)" in out
    # still behind: served as read, with one warning
    for data, was in ((old, str(ledger[8].day)), (None, "none")):
        host = Replica(data)
        found, out, err = served(host)
        assert host.reads == 2
        assert err.count("warning:") == 1
        assert (
            f"switch: predictions/switch.json is behind the step's read-back (through {was}, "
            f"the frozen marker {ledger[-1].day}): served as read"
        ) in err
    # level with the marker: one read
    host = Replica(new)
    assert served(host)[0].arms == {"bus_timing": "on"}
    assert host.reads == 1


def test_the_step_replays_each_date_once_and_a_long_ledger_replays_in_bounded_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time  # noqa: PLC0415

    gains = np.random.default_rng(1).normal(0.002, 0.01, 250)
    ledger = winter([float(g) for g in gains])
    began = time.process_time()
    full = live_switch.replay(RULE, ledger, BUS, CONFIG)
    # 250 moved dates (about 8 bus winters) measured 0.9 s of CPU; the bound holds the line
    assert time.process_time() - began < 8.0
    evaluate = live_switch.evaluate
    calls: list[int] = []

    def counted(*args: Any, **kwargs: Any) -> Evaluation:
        calls.append(1)
        return evaluate(*args, **kwargs)

    monkeypatch.setattr(live_switch, "evaluate", counted)
    part = live_switch.replay(RULE, ledger[:200], BUS, CONFIG)
    calls.clear()
    assert live_switch.replay(RULE, ledger, BUS, CONFIG, prior=part) == full
    assert len(calls) == 50
    with pytest.raises(ValueError, match="a longer ledger"):
        live_switch.replay(RULE, ledger[:10], BUS, CONFIG, prior=part)
    # the step: the stored ledger replayed once, each new date once
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(4)
    for day in days[:3]:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    run(step_inputs(tmp_path, host))
    storm_day(tmp_path / "reads", tmp_path / "frozen", days[3], 0.05)
    calls.clear()
    out = run(step_inputs(tmp_path, host))
    assert out[-1].endswith(" B), read back")
    assert len(calls) == 3 + 1


def test_a_slow_date_is_said_at_once_and_a_large_state_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = Host(tmp_path / "host")
    started(tmp_path, host)
    days = school_days(3)
    for day in days:
        storm_day(tmp_path / "reads", tmp_path / "frozen", day, 0.05)
    clock = Clock(0.0)
    monkeypatch.setattr(live_switch, "_count_day", durations(clock, [4.0, 74.0, 4.0]))
    host.fail = True
    out = run(step_inputs(tmp_path, host, clock=clock))
    host.fail = False
    slow = (
        f"predict read-labels: switch bus_timing: {days[1]} ran to 78 s of the step, past 55 s: "
        "kept"
    )
    # said at once, so a step cut off before its write still says it
    assert slow in out
    assert out.index(slow) < len(out) - 1
    assert out[-1] == "::warning::predict read-labels: switch: PublishError: nothing written"
    monkeypatch.undo()
    monkeypatch.setattr(live_switch, "STATE_BYTES", 100)
    out = run(step_inputs(tmp_path, host))
    size = len(host.read(f"v1/{live_switch.SWITCH_PATH}") or b"")
    assert (
        f"::warning::predict read-labels: switch: predictions/switch.json is {size:,} B, over 100 B"
    ) in out
    assert out[-1].endswith(" B), read back")
