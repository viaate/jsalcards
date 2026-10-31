"""The night chart's shadow evidence (``predict/chart_evidence.py``, design spec chart-shadow W2
and W3): the deterministic fault rotation and the counts-only 48-hour summary. Every record here
is made up."""

import json
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from snowlight.predict import chart_evidence as ce

GRID = (7, 37)
START = datetime(2026, 11, 1, 0, 7, tzinfo=UTC)


def _grid_passes(hours: int = 48, start: datetime = START) -> list[datetime]:
    return [start + timedelta(minutes=30 * k) for k in range(hours * 2)]


def test_the_slot_is_the_scheduled_grid_minute() -> None:
    at = datetime(2026, 11, 1, 3, 7, tzinfo=UTC)
    slot = ce.grid_slot(at, GRID)
    # A pass that starts late in its slot, or the same pass run again, keeps the slot.
    assert ce.grid_slot(at + timedelta(minutes=2, seconds=41), GRID) == slot
    assert ce.grid_slot(at + timedelta(minutes=29, seconds=59), GRID) == slot
    assert ce.grid_slot(at + timedelta(minutes=30), GRID) == slot + 1
    assert ce.grid_slot(at - timedelta(seconds=1), GRID) == slot - 1


def test_rotate_injects_one_grid_pass_in_six_in_a_fixed_order() -> None:
    picked = [ce.fault_for("rotate", at, GRID, grid=True) for at in _grid_passes()]
    injected = [fault for fault in picked if fault is not None]
    assert len(injected) == len(picked) // ce.ROTATE_EVERY == 16
    # Every 6th slot, the five faults in turn, each 3 or 4 times in 48 hours.
    assert set(Counter(injected).values()) <= {3, 4}
    assert set(injected) == set(ce.FAULTS)
    first = next(i for i, fault in enumerate(picked) if fault is not None)
    assert all(
        (fault is not None) == ((i - first) % ce.ROTATE_EVERY == 0)
        for i, fault in enumerate(picked)
    )
    k = ce.FAULTS.index(injected[0])
    assert injected[:10] == [ce.FAULTS[(k + n) % len(ce.FAULTS)] for n in range(10)]


def test_each_fault_comes_at_a_new_time_of_day_each_day() -> None:
    """Every 15 hours: a fault whose slot comes with the gate shut (a calm hour of the day) meets
    another hour of the day next time, so no fault is held to one time of day."""
    at: dict[str, list[int]] = {fault: [] for fault in ce.FAULTS}
    for moment in _grid_passes(24 * 5):
        fault = ce.fault_for("rotate", moment, GRID, grid=True)
        if fault is not None:
            at[fault].append(moment.hour)
    for hours in at.values():
        assert len(set(hours)) >= 5


def test_any_six_grid_passes_in_a_row_hold_at_most_one_fault() -> None:
    picked = [ce.fault_for("rotate", at, GRID, grid=True) for at in _grid_passes(72)]
    for i in range(len(picked) - ce.ROTATE_EVERY + 1):
        assert sum(fault is not None for fault in picked[i : i + ce.ROTATE_EVERY]) <= 1


def test_a_pass_run_again_picks_the_same_fault() -> None:
    for at in _grid_passes(12):
        once = ce.fault_for("rotate", at, GRID, grid=True)
        again = ce.fault_for("rotate", at + timedelta(minutes=4, seconds=12), GRID, grid=True)
        assert once == again


def _fault_record(at: datetime, fault: str | None) -> dict[str, object]:
    return {"at": at.isoformat(), "fault": fault}


def test_a_slot_injects_once_even_when_a_run_starts_in_it() -> None:
    """chart-shadow critic S1: a run's first pass counts as a grid pass wherever it starts, so
    one that starts at :12 lands in the :07 slot the run before already injected. It injects
    nothing, and the next fault slot injects as usual."""
    slot_start = next(at for at in _grid_passes() if ce.fault_for("rotate", at, GRID, grid=True))
    fault = ce.fault_for("rotate", slot_start, GRID, grid=True)
    done = [_fault_record(slot_start, fault)]
    run_start = slot_start + timedelta(minutes=5)  # :12, the next job's first pass
    assert ce.fault_for("rotate", run_start, GRID, grid=True) == fault  # what it would pick
    assert ce.fault_for("rotate", run_start, GRID, grid=True, done=done) is None
    # A clean pass in that slot does not use it up; the next fault slot still injects.
    assert (
        ce.fault_for("rotate", run_start, GRID, grid=True, done=[_fault_record(slot_start, None)])
        == fault
    )
    later = slot_start + timedelta(hours=3)
    assert ce.fault_for("rotate", later, GRID, grid=True, done=done) is not None
    # Unreadable records are skipped; a fixed fault is never held back.
    assert ce.fault_for("rotate", run_start, GRID, grid=True, done=[{"fault": fault}]) == fault
    assert ce.fault_for("raise", run_start, GRID, grid=True, done=done) == "raise"


def test_chained_runs_inject_at_most_one_grid_pass_in_six() -> None:
    """Runs of 320 minutes, a gap of 1 to 3 minutes between jobs, each run's first pass a grid
    pass at its start: over 48 hours, never more than 1 grid pass in 6 injects and no slot
    twice (the critic's simulation gave 17 or 18 of 104 or 105, with a slot injected twice)."""
    for gap in (1, 2, 3, 13):
        done: list[dict[str, object]] = []
        grid_passes = 0
        start = START + timedelta(minutes=3)
        while start < START + timedelta(hours=48):
            passes = [start]
            moment = start
            while True:
                moment = _next_grid(moment)
                if moment >= start + timedelta(minutes=320):
                    break
                passes.append(moment)
            for at in passes:
                grid_passes += 1
                fault = ce.fault_for("rotate", at, GRID, grid=True, done=done)
                done.append(_fault_record(at, fault))
            start += timedelta(minutes=320 + gap)
        injected = [item for item in done if item["fault"] is not None]
        slots = [ce.grid_slot(datetime.fromisoformat(str(i["at"])), GRID) for i in injected]
        assert len(slots) == len(set(slots))
        assert len(injected) * ce.ROTATE_EVERY <= grid_passes


def _next_grid(at: datetime) -> datetime:
    moment = at.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while moment.minute not in GRID:
        moment += timedelta(minutes=1)
    return moment


def test_an_event_pass_never_injects_and_a_fixed_fault_always_does() -> None:
    for at in _grid_passes(12):
        between = at + timedelta(minutes=13)
        assert ce.fault_for("rotate", between, GRID, grid=False) is None
        assert ce.fault_for("none", at, GRID, grid=True) is None
        assert ce.fault_for("bad_host", between, GRID, grid=False) == "bad_host"


def _record(at: datetime, **fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "fault": None,
        "gated": True,
        "cycle": at - timedelta(minutes=97),
        "codes": [],
        "nights": 12,
        "read_ms": 700,
        "build_ms": 16_000,
        "extra_ms": 17_000,
        "clean": None,
    }
    return ce.record(at, **(base | fields))  # type: ignore[arg-type]


def test_the_summary_counts_the_last_48_hours_only() -> None:
    now = START + timedelta(hours=60)
    records = [
        _record(START),  # 60 h old: out
        _record(now - timedelta(hours=10), cycle=now - timedelta(hours=10, minutes=67)),
        _record(now - timedelta(hours=9), codes=["nbm_stale"], cycle=None, nights=0),
        _record(now - timedelta(hours=8), codes=["nbm_slow"], cycle=None, nights=0),
        _record(now - timedelta(hours=7), cycle=now - timedelta(hours=7, minutes=127)),
        _record(
            now - timedelta(hours=6),
            fault="raise",
            codes=["invalid (RuntimeError)"],
            nights=0,
            clean=True,
        ),
        _record(
            now - timedelta(hours=5),
            fault="bad_host",
            codes=["nbm_unreadable"],
            cycle=None,
            nights=0,
            clean=True,
        ),
        # Gate open but no night: nothing for the stale night_at to act on.
        _record(now - timedelta(hours=4), fault="stale_night_at", codes=[], nights=0, clean=True),
        _record(
            now - timedelta(hours=3, minutes=30),
            fault="nbm_slow",
            codes=["nbm_slow"],
            cycle=None,
            nights=0,
            clean=True,
        ),
        _record(now - timedelta(hours=3), gated=False, cycle=None, nights=0, extra_ms=3),
        # Its slot came with the gate shut: nothing ran, so it counts apart.
        _record(
            now - timedelta(hours=2), fault="frozen_listing", gated=False, cycle=None, nights=0
        ),
    ]
    found = ce.summary(records, now, mode="shadow", setting="rotate")
    assert found["passes"] == 10
    assert found["gated"] == 8
    assert found["injected"] == 3  # raise, bad_host, nbm_slow; not the night-less stale pass
    assert found["since"] == records[1]["at"]
    assert found["cycle_age_minutes"] == {"min": 67, "n": 2, "p50": 67, "p95": 127, "max": 127}
    assert found["withheld"] == {"nbm_slow": 1, "nbm_stale": 1}
    faults = found["faults"]
    assert isinstance(faults, dict)
    assert faults["raise"] == {
        "injected": 1,
        "gate_shut": 0,
        "no_night": 0,
        "expected_code": "invalid (RuntimeError)",
        "with_expected_code": 1,
        "clean_chances": 1,
        "not_clean": 0,
        "codes": {"invalid (RuntimeError)": 1},
    }
    assert faults["bad_host"]["with_expected_code"] == 1
    assert faults["nbm_slow"]["with_expected_code"] == faults["nbm_slow"]["injected"] == 1
    # No nights on that pass: nothing for the stale night_at to act on. It counts apart, as
    # no_night, so injected and with_expected_code agree (critic S2).
    stale = faults["stale_night_at"]
    assert (stale["injected"], stale["no_night"], stale["with_expected_code"]) == (0, 1, 0)
    assert stale["not_clean"] == 0
    assert faults["frozen_listing"]["injected"] == 0
    assert faults["frozen_listing"]["gate_shut"] == 1
    extra = found["extra_ms"]
    assert isinstance(extra, dict)
    assert extra["max"] == 17_000
    assert extra["n"] == 10


def test_a_stale_night_at_pass_with_nights_counts_and_a_failed_check_shows() -> None:
    now = START + timedelta(hours=10)
    records = [
        _record(
            now - timedelta(hours=2),
            fault="stale_night_at",
            codes=["invalid (night_at_age)"],
            nights=9,
            clean=True,
        ),
        _record(
            now - timedelta(hours=1),
            fault="raise",
            codes=["invalid (RuntimeError)"],
            nights=0,
            clean=False,
        ),
        _record(now, fault="stale_night_at", codes=[], nights=0, clean=False),
    ]
    faults = ce.summary(records, now, mode="shadow", setting="rotate")["faults"]
    assert isinstance(faults, dict)
    stale = faults["stale_night_at"]
    assert (stale["injected"], stale["with_expected_code"], stale["clean_chances"]) == (1, 1, 1)
    assert (stale["no_night"], stale["not_clean"]) == (1, 1)  # every gated pass's check counts
    assert (faults["raise"]["clean_chances"], faults["raise"]["not_clean"]) == (0, 1)


def test_the_summary_holds_counts_and_codes_only() -> None:
    now = START + timedelta(hours=2)
    records = [_record(START + timedelta(minutes=30 * k)) for k in range(4)]
    records.append(_record(now, fault="bad_host", codes=["nbm_unreadable"], clean=True))
    keys: set[str] = set()
    values: set[str] = set()

    def walk(value: object, within: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                # The per-fault code counts are keyed by the codes themselves.
                (values if within in {"withheld", "codes"} else keys).add(str(key))
                walk(item, str(key))
        elif isinstance(value, str):
            values.add(value)
        else:
            assert value is None or isinstance(value, int), value

    walk(json.loads(json.dumps(ce.summary(records, now, mode="shadow", setting="rotate"))))
    assert keys <= {
        *("schema_version", "generated_at", "mode", "chart_fault", "window_hours", "since"),
        *("passes", "gated", "injected", "cycle_age_minutes", "withheld", "extra_ms"),
        *("build_ms", "read_ms", "faults", "min", "n", "p50", "p95", "max"),
        *("injected", "gate_shut", "expected_code", "with_expected_code", "clean_chances"),
        *("no_night", "not_clean"),
        "codes",
        *ce.FAULTS,
    }
    times = {value for value in values if value.endswith("+00:00")}
    assert values - times <= {"shadow", "rotate", *ce.EXPECTED.values()}


def test_records_older_than_48_hours_or_unreadable_are_dropped() -> None:
    now = START + timedelta(hours=49)
    found = ce.kept(
        [
            _record(START),
            _record(START + timedelta(hours=2)),
            {"at": "not a time"},
            {"no": "time"},
            _record(now + timedelta(hours=1)),
        ],
        now,
    )
    assert [item["at"] for item in found] == [(START + timedelta(hours=2)).isoformat()]


def test_an_empty_summary_reads() -> None:
    found = ce.summary([], START, mode="shadow", setting="rotate")
    assert found["passes"] == 0
    assert found["since"] is None
    assert found["cycle_age_minutes"] is None


@pytest.mark.parametrize("fault", ce.FAULTS)
def test_each_fault_has_its_expected_code(fault: str) -> None:
    assert ce.EXPECTED[fault]
