"""S7-L for the outlook (S7-F F3, spec-f s. 10): the one chance function scores the learning
step, the record moves to the host, live cases are counted once, ``T`` is swapped in only when
the held-out days find it no worse, and the internal report. SYNTHETIC records and T only."""

import json
from datetime import date, timedelta
from typing import Any

import numpy as np
import pytest

from predict import night, world
from predict.test_learn import CFG, Host, built, learn_run
from snowlight.predict import cli, learn
from snowlight.predict import outlook as outlook_module
from snowlight.predict.live_labels import NoLiveSource
from snowlight.predict.outlook import OutlookMode, cell_index
from snowlight.predict.outlook_learn import (
    CASES_PATH,
    HELD_DAYS,
    LEARNED_PATH,
    REPORT_PATH,
    CaseDay,
    LearnedOutlook,
    LiveCases,
    count_days,
    day_cases,
    decide,
    log_loss,
    report_changed,
    served_outlook,
    with_live,
)
from snowlight.predict.outlook_record import (
    NOT_TAKEN8,
    NOT_TAKEN16,
    RECORD_PATH,
    Record,
    carried,
    pack,
)
from snowlight.predict.outlook_serve import OutlookServe
from snowlight.predict.serve import build_model
from snowlight.predict.situations import WeatherClass

KS = outlook_module.STATES.index("KS")
MO = outlook_module.STATES.index("MO")
CELL = cell_index(5, 0, 0, 4)
SHA = "a" * 64


def committed() -> outlook_module.Outlook:
    return night.outlook_model()[1]


def test_the_learning_step_scores_through_the_one_chance_function() -> None:
    model = built(None)
    rows = np.repeat(np.arange(model.p.shape[0]), model.p.shape[1])
    situations = np.tile(np.arange(model.p.shape[1]), model.p.shape[0])
    p, q = learn.served_chances(model, rows, situations)
    assert np.array_equal(p, model.p[rows, situations])
    assert np.array_equal(q, model.q[rows, situations])
    empty = learn.served_chances(model, np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64))
    assert empty[0].size == empty[1].size == 0


def case_day(day: date, warned: int, quiet: int, state: int = KS) -> CaseDay:
    rows = []
    if quiet:
        rows.append((state, CELL, int(WeatherClass.NONE), quiet))
    if warned:
        rows.append((state, CELL, int(WeatherClass.SNOW_WARNING), warned))
    return CaseDay(day=day, rows=tuple(sorted(rows)))


def test_live_days_count_into_t_at_their_state_region_and_nation() -> None:
    table = committed()
    assert with_live(table, []) is table
    day = case_day(date(2026, 1, 7), warned=40, quiet=0)
    found = with_live(table, [day])
    assert found.state[KS, CELL, WeatherClass.SNOW_WARNING] == table.state[KS, CELL, 5] + 40
    assert found.nation[CELL].sum() == table.nation[CELL].sum() + 40
    region = outlook_module.REGION_OF_STATE[KS]
    assert found.region[region, CELL].sum() == table.region[region, CELL].sum() + 40
    assert found.nights_state[KS, CELL] == table.nights_state[KS, CELL] + 1
    assert found.nights_nation[CELL] == table.nights_nation[CELL] + 1
    assert found.nights_state[MO, CELL] == table.nights_state[MO, CELL]
    assert found.t_state()[KS, CELL, 5] > table.t_state()[KS, CELL, 5]
    sums = found.t_state().sum(axis=2)
    assert np.allclose(sums[sums > 0], 1.0)


def test_a_learned_t_serves_only_over_its_own_artifact() -> None:
    table = committed()
    assert served_outlook(table, None, SHA) == (table, None)
    assert (
        served_outlook(table, b"{", SHA)[1]
        == "the learned outlook does not validate (ValidationError)"
    )
    learned = LearnedOutlook(
        schema_version=1, artifact_sha256=SHA, through=date(2026, 1, 7),
        days=(case_day(date(2026, 1, 7), 40, 0),), check={}, made_at=world.utc("2026-01-08T09:00"),
    )  # fmt: skip
    other, why = served_outlook(table, learned.to_bytes(), "b" * 64)
    assert other is table
    assert why == "the learned outlook was made over another artifact"
    found, why = served_outlook(table, learned.to_bytes(), SHA)
    assert why is None
    assert found.state[KS, CELL].sum() == table.state[KS, CELL].sum() + 40


def record_with(day: date, morning: dict[int, int], samples: dict[int, dict[int, int]]) -> Record:
    """A record whose Chicago districts took ``samples`` (sample to district to packed state)
    and the ``morning`` classes."""
    record = Record("content", len(world.DISTRICTS))
    now = world.utc("2026-01-07T12:00")
    chicago = [
        i for i, leaid in enumerate(world.DISTRICTS) if world.ZONES[leaid].endswith("Chicago")
    ]
    for k, by_district in samples.items():
        values = np.array([by_district.get(i, 0) for i in chicago])
        record.sample(day, k).put("America/Chicago", chicago, values, now)
    record.morning(day).put(
        "America/Chicago", chicago, np.array([morning.get(i, 0) for i in chicago]), now
    )
    return record


def test_a_day_s_cases_are_its_samples_against_its_five_am_record() -> None:
    day = date(2026, 1, 7)
    record = record_with(
        day,
        morning={0: 5, 1: 5, 2: 0, 3: 1},
        samples={
            12: {0: pack(0, 0, 4), 1: pack(1, 1, 4), 2: pack(5, 0, 4), 3: pack(0, 0, 0)},
            13: {0: pack(0, 0, 4)},
        },
    )
    zones = [world.ZONES[leaid] for leaid in world.DISTRICTS]
    states = np.array([KS, MO, MO, MO, outlook_module.STATES.index("UT")])
    found = day_cases(record, day, zones, states)
    assert found is not None
    rows = {row[:3]: row[3] for row in found.rows}
    assert rows[(KS, CELL, 5)] == 2  # 20:00 and 21:00, both slot 5
    assert rows[(MO, cell_index(5, 1, 1, 4), 5)] == 1
    assert rows[(MO, cell_index(5, 0, 0, 0), 1)] == 2  # 20:00 and 21:00
    # A warning issued (c0 snow_warning) trains nothing; Utah took no sample; sample 13's other
    # Chicago districts read quiet.
    assert sum(rows.values()) == 7
    assert day_cases(Record("content", 5), day, zones, states) is None


def test_live_days_are_counted_once_and_never_today() -> None:
    day = date(2026, 1, 7)
    record = record_with(day, morning={0: 5}, samples={12: {0: pack(0, 0, 4)}})
    zones = [world.ZONES[leaid] for leaid in world.DISTRICTS]
    states = np.array([KS, MO, MO, MO, -1])
    same_day = world.utc("2026-01-07T23:00")
    cases, added = count_days(LiveCases.empty(), record, zones, states, same_day)
    assert added == []
    later = world.utc("2026-01-08T10:00")
    cases, added = count_days(LiveCases.empty(), record, zones, states, later)
    assert added == [day]
    again, more = count_days(
        cases, record_with(day, {0: 0}, {12: {0: pack(0, 0, 4)}}), zones, states, later
    )
    assert more == []
    assert again == cases  # frozen: a rerun changes nothing
    assert LiveCases.from_bytes(cases.to_bytes()) == cases


def school_days(count: int, start: date = date(2026, 1, 5)) -> list[date]:
    found: list[date] = []
    day = start
    while len(found) < count:
        if day.weekday() < 5:
            found.append(day)
        day += timedelta(days=1)
    return found


def test_t_waits_for_more_than_the_held_out_days() -> None:
    table = committed()
    days = [case_day(d, 3, 2) for d in school_days(HELD_DAYS)]
    found = decide(
        table,
        None,
        LiveCases(schema_version=1, days=tuple(days)),
        SHA,
        world.utc("2026-02-01T09:00"),
    )
    assert found.kind == "unchanged"


def test_a_candidate_no_worse_on_the_held_out_days_is_swapped_in_with_every_day() -> None:
    table = committed()
    days = [case_day(d, 3, 2) for d in school_days(HELD_DAYS + 3)]
    cases = LiveCases(schema_version=1, days=tuple(days))
    found = decide(table, None, cases, SHA, world.utc("2026-02-01T09:00"))
    assert found.kind == "swap", found.why
    assert found.learned is not None
    assert [item.day for item in found.learned.days] == [item.day for item in days]
    assert found.learned.check["held_cases"] == 5 * HELD_DAYS
    # The same days again: nothing new to judge.
    again = decide(table, found.learned, cases, SHA, world.utc("2026-02-02T09:00"))
    assert again.kind == "unchanged"


def test_t_takes_in_a_new_live_day_every_night_judged_without_the_held_out_days() -> None:
    table = committed()
    every = [case_day(d, 3, 2) for d in school_days(HELD_DAYS + 12)]
    served = None
    kinds: list[str] = []
    for night_count in range(HELD_DAYS + 1, len(every) + 1):
        cases = LiveCases(schema_version=1, days=tuple(every[:night_count]))
        found = decide(table, served, cases, SHA, world.utc("2026-03-01T09:00"))
        kinds.append(found.kind)
        if found.kind == "swap":
            assert found.learned is not None
            # Every day counted so far, the held-out ones too: the full refit.
            assert [item.day for item in found.learned.days] == [
                item.day for item in every[:night_count]
            ]
            # Judged on the held-out cases against the committed T, which never counted them.
            check = found.learned.check
            assert check["held_cases"] == 5 * HELD_DAYS
            assert check["candidate_log_loss"] <= check["committed_log_loss"]
            # The served T without the held-out days is the candidate itself: never a judge.
            assert "served_log_loss" not in check
            served = found.learned
    assert kinds == ["swap"] * len(kinds)  # nightly, not every 8 days


def test_after_nightly_swaps_live_days_that_hurt_t_on_the_days_after_them_are_kept_out() -> None:
    table = committed()
    benign = [case_day(d, 3, 2) for d in school_days(HELD_DAYS + 1)]
    later = school_days(HELD_DAYS + 12, date(2026, 3, 2))
    # A stretch where the cell always ends in a warning, then days where it never does.
    harmful = [case_day(d, 400, 0) for d in later[:6]] + [case_day(d, 0, 50) for d in later[6:]]
    every = benign + harmful
    served: LearnedOutlook | None = None
    kinds: list[str] = []
    for night_count in range(HELD_DAYS + 1, len(every) + 1):
        cases = LiveCases(schema_version=1, days=tuple(every[:night_count]))
        found = decide(table, served, cases, SHA, world.utc("2026-04-01T09:00"))
        held, fit = every[:night_count][-HELD_DAYS:], every[:night_count][:-HELD_DAYS]
        candidate = log_loss(with_live(table, fit), held)[0]
        archive = log_loss(table, held)[0]
        kinds.append(found.kind)
        if found.kind == "swap":
            assert found.learned is not None
            # Never swapped in while worse than the archive's T on days neither counted.
            assert candidate <= archive + 1e-9, (night_count, candidate, archive)
            served = found.learned
        elif candidate > archive + 1e-9:
            assert found.kind == "keep"
            assert f"{archive:.5f} committed" in found.why
    assert kinds[:5] == ["swap"] * 5  # the benign days swap in nightly
    assert kinds[-7:] == ["keep"] * 7  # the warning stretch fitted, the quiet days held out
    # The probe's night: the warning stretch fitted, the quiet days held out. Its candidate is
    # far worse than the archive's T there, so the T served after the earlier swaps stays.
    night_count = len(benign) + 6 + HELD_DAYS
    held = every[:night_count][-HELD_DAYS:]
    fit = every[:night_count][:-HELD_DAYS]
    assert log_loss(with_live(table, fit), held)[0] > log_loss(table, held)[0] + 1.0
    assert served is not None
    assert served.through < every[night_count - 1].day


def test_the_served_t_is_judged_without_the_held_out_days_it_counted() -> None:
    table = committed()
    # The served T counted the held-out days (they say this cell never ends in a warning); a
    # candidate fitted without them must not be judged against a T that has seen them.
    fit = [case_day(d, 3, 2) for d in school_days(3)]
    held = [case_day(d, 0, 50) for d in school_days(HELD_DAYS, date(2026, 2, 2))]
    seen = LearnedOutlook(
        schema_version=1,
        artifact_sha256=SHA,
        through=held[-1].day,
        days=tuple(fit[:2] + held),
        check={},
        made_at=world.utc("2026-02-12T09:00"),
    )
    cases = LiveCases(schema_version=1, days=tuple(fit + held))
    found = decide(table, seen, cases, SHA, world.utc("2026-02-20T09:00"))
    fair = log_loss(with_live(table, fit[:2]), held)[0]
    biased = log_loss(with_live(table, fit[:2] + held), held)[0]
    assert abs(fair - biased) > 1e-3
    assert f"{fair:.5f} served" in found.why
    assert f"{biased:.5f} served" not in found.why


def test_a_candidate_worse_on_the_held_out_days_is_kept_out() -> None:
    table = committed()
    # The fit days say this cell always ends in a warning; the held-out days say it never does.
    fit = [case_day(d, 400, 0) for d in school_days(3)]
    held = [case_day(d, 0, 50) for d in school_days(HELD_DAYS, date(2026, 2, 2))]
    cases = LiveCases(schema_version=1, days=tuple(fit + held))
    found = decide(table, None, cases, SHA, world.utc("2026-02-20T09:00"))
    assert found.kind == "keep"
    assert "log loss" in found.why


def test_with_three_hundred_e20_rows_a_swap_also_needs_an_e20_brier_no_worse() -> None:
    table = committed()
    days = [case_day(d, 3, 2) for d in school_days(HELD_DAYS + 3)]
    cases = LiveCases(schema_version=1, days=tuple(days))
    calls: list[int] = []

    def e20(_t: Any, _days: Any) -> tuple[int, float]:
        calls.append(1)
        return (300, 0.2) if len(calls) == 1 else (300, 0.1)  # candidate first, then the judges

    found = decide(table, None, cases, SHA, world.utc("2026-02-01T09:00"), e20)
    assert found.kind == "keep"
    assert "E20 Brier" in found.why
    assert "0.10000 committed" in found.why
    few = decide(table, None, cases, SHA, world.utc("2026-02-01T09:00"), lambda _t, _d: (299, 0.9))
    assert few.kind == "swap"


def shadow_state() -> dict[str, object]:
    _files, run, _host = night.run_night(prepare=night.with_outlook(OutlookMode.SHADOW))
    return dict(run.state.outlook)


def outlook_run(
    host: Host, now: Any, state: dict[str, object], broken: bool = False
) -> cli.LearnRun:
    run = learn_run(host, NoLiveSource(), now)

    def outlook_of() -> tuple[OutlookServe, str]:
        if broken:
            raise RuntimeError("broken")
        rates, table = night.outlook_model()
        model = build_model(world.directory(), rates, CFG, lambda _x, _y: None)
        return OutlookServe.of(model, table), SHA

    run.outlook_mode = OutlookMode.SHADOW
    run.outlook_state = state
    run.outlook = outlook_of
    return run


def test_the_learning_step_moves_the_record_counts_the_cases_and_reports(capsys: Any) -> None:
    state = shadow_state()
    host = Host()
    now = world.utc("2026-01-08T13:00")
    assert cli.learn_once(outlook_run(host, now, state)) == 0
    record = json.loads(host.files[f"v1/{RECORD_PATH}"])
    assert "2026-01-07" in record["days"]
    cases = LiveCases.from_bytes(host.files[f"v1/{CASES_PATH}"])
    assert [item.day for item in cases.days] == [date(2026, 1, 7)]
    report = json.loads(host.files[f"v1/{REPORT_PATH}"])
    assert report["days"] == ["2026-01-06", "2026-01-07", "2026-01-08"][: len(report["days"])]
    assert f"v1/{LEARNED_PATH}" not in host.files  # one live day: T waits
    out = capsys.readouterr().out
    assert "predict learn: outlook: counted the live cases of 2026-01-07" in out
    assert "predict learn: T: 1 live days counted" in out
    assert "predict learn: outlook report:" in out
    # A rerun counts nothing again.
    writes = host.writes
    assert cli.learn_once(outlook_run(host, now, state)) == 0
    assert host.writes == writes  # nothing new: no write, so no commit on the live host
    assert "counted the live cases" not in capsys.readouterr().out
    # A report that says something new is written, its time aside.
    report = json.loads(host.files[f"v1/{REPORT_PATH}"])
    assert not report_changed(json.dumps({**report, "made_at": "x"}).encode(), report)
    assert report_changed(json.dumps({**report, "days": []}).encode(), report)
    assert report_changed(None, report)
    assert report_changed(b"not json", report)
    assert report_changed(b"[]", report)


def test_a_new_directory_carries_the_record_over_by_leaid_and_loses_no_day() -> None:
    day = date(2026, 1, 7)
    old_ids = world.DISTRICTS
    new_ids = ("2900002", "2000004", "3100009", "2900001", "4900005", "2900003")
    old = record_with(day, morning={0: 5, 1: 5}, samples={12: {0: pack(0, 0, 4)}})
    old = Record(old.content, old.districts, old.days, old_ids)
    host_value = old.as_json()
    moved, line = carried(host_value, "new-content", new_ids)
    assert line is not None
    assert "carried 1 days" in line
    assert (moved.content, moved.districts, moved.leaids) == ("new-content", 6, new_ids)
    entry = moved.days[day]
    assert entry.morning is not None
    # Each value follows its LEAID; the new district reads as not taken.
    assert int(entry.morning.values[1]) == 5  # 2000004, was position 0
    assert int(entry.morning.values[3]) == 5  # 2900001, was position 1
    assert int(entry.morning.values[2]) == NOT_TAKEN8  # 3100009 is new
    assert int(entry.samples[12].values[1]) == pack(0, 0, 4)
    assert int(entry.samples[12].values[2]) == NOT_TAKEN16
    assert entry.morning.taken == old.days[day].morning.taken  # type: ignore[union-attr]
    # The passes' state of the old content (no LEAIDs of its own) is carried with the host's.
    state = Record(old.content, old.districts, old.days).as_json()
    assert "leaids" not in state
    moved_state, state_line = carried(state, "new-content", new_ids, Record.read_any(host_value))
    assert state_line is not None
    assert int(moved_state.days[day].morning.values[1]) == 5  # type: ignore[union-attr]
    # Without any LEAIDs it cannot be carried: it starts again, and says so.
    lost, lost_line = carried(state, "new-content", new_ids)
    assert lost.days == {}
    assert lost_line is not None
    assert "starts again" in lost_line
    # The same content reads as kept; nothing read is an empty record.
    same, same_line = carried(host_value, old.content, old_ids)
    assert same_line is None
    assert same.days.keys() == old.days.keys()
    assert carried(None, "new-content", new_ids)[0].days == {}
    # Every complete day of the carried record still counts its cases on the new directory.
    zones = [world.ZONES.get(leaid, "America/Chicago") for leaid in new_ids]
    states = np.array([MO, KS, -1, MO, -1, MO])
    cases, added = count_days(
        LiveCases.empty(), moved, zones, states, world.utc("2026-01-08T10:00")
    )
    assert added == [day]
    # The four Chicago districts it held (the new one was not taken), at 20:00.
    assert sum(n for (*_key, n) in cases.days[0].rows) == 4
    assert (KS, cell_index(5, 0, 0, 4), 5, 1) in cases.days[0].rows  # 2000004, as before


def test_an_outlook_error_never_changes_the_learning_step(capsys: Any) -> None:
    host = Host()
    now = world.utc("2026-01-08T13:00")
    assert cli.learn_once(outlook_run(host, now, {}, broken=True)) == 0
    assert host.files == {}
    assert "outlook: RuntimeError: nothing written" in capsys.readouterr().err


@pytest.mark.parametrize("mode", [OutlookMode.OFF])
def test_with_the_outlook_off_the_step_is_s7l_s(mode: OutlookMode, capsys: Any) -> None:
    host = Host()
    run = outlook_run(host, world.utc("2026-01-08T13:00"), shadow_state())
    run.outlook_mode = mode
    capsys.readouterr()
    assert cli.learn_once(run) == 0
    assert host.files == {}
    assert "outlook" not in capsys.readouterr().out


def test_the_report_and_the_e20_check_score_the_recorded_nights_against_live_labels() -> None:
    from snowlight.predict.outlook_learn import (  # noqa: PLC0415
        Labels,
        e20_score,
        report,
        summary_line,
    )

    state = shadow_state()
    rates, table = night.outlook_model()
    model = build_model(world.directory(), rates, CFG, lambda _x, _y: None)
    serve = OutlookServe.of(model, table)
    record = Record.from_json(state, learn.content_key(world.directory()), len(world.DISTRICTS))
    day = date(2026, 1, 7)
    # SYNTHETIC labels: Missouri's districts closed, Kansas's opened; the day before, none.
    labels = Labels({(0, day): 0.0, (1, day): 1.0, (2, day): 1.0, (3, day): 1.0})
    assert not labels.after(1, day)
    found = report(serve, table, record, labels, world.utc("2026-01-08T13:00"), model)
    assert found["labeled_days"] == ["2026-01-07"]
    five = found["by_slot"]["5"]
    # At 20:00 Missouri had its warning (c0 snow_warning: no outlook row); Kansas's advisory
    # and the quiet Missouri samples before 23Z are rows.
    assert five["rows"] >= 1
    assert five["bins_f"]
    assert five["brier_v2"] is not None  # S7-F against the v2 rates, slot by slot
    e20 = found["e20_recorded"]
    assert e20["rows"] == 1  # Kansas only: Missouri's warning was out by 8 PM
    assert e20["brier_f"] is not None
    assert "outlook report: 3 days recorded, 1 labeled" in summary_line(found)
    rows, brier = e20_score(serve, record, labels)(table, [day])
    assert rows == 1
    assert 0.0 <= brier <= 1.0
    none, nan = e20_score(serve, record, Labels({}))(table, [day])
    assert none == 0
    assert np.isnan(nan)


def test_a_record_on_the_host_that_does_not_read_starts_again(capsys: Any) -> None:
    host = Host()
    host.files[f"v1/{RECORD_PATH}"] = b"{"
    now = world.utc("2026-01-08T13:00")
    assert cli.learn_once(outlook_run(host, now, shadow_state())) == 0
    assert json.loads(host.files[f"v1/{RECORD_PATH}"])["days"]
    assert "the host's record does not read: it starts again" in capsys.readouterr().out


def test_the_v3_rates_learn_from_the_five_am_labels_under_their_own_check(capsys: Any) -> None:
    from predict.test_learn import honest, store_of  # noqa: PLC0415
    from snowlight.predict.artifact import Learned  # noqa: PLC0415
    from snowlight.predict.outlook_learn import (  # noqa: PLC0415
        RATES_LEARNED_PATH,
        RATES_STORE_PATH,
    )

    host = Host()
    host.files[f"v1/{RATES_STORE_PATH}"] = store_of([honest(j) for j in range(30)]).to_bytes()
    run = outlook_run(host, world.utc("2026-01-08T13:00"), shadow_state())
    rates, _table = night.outlook_model()
    run.outlook_build = lambda learned: build_model(
        world.directory(), rates, CFG, lambda _x, _y: None, learned
    )
    capsys.readouterr()
    assert cli.learn_once(run) == 0
    learned = Learned.from_bytes(host.files[f"v1/{RATES_LEARNED_PATH}"])
    assert learned.archive_sha256 == SHA
    assert learned.anchored == ("snow_warning",)
    out = capsys.readouterr().out
    assert "predict learn: outlook: v3 rates: swapped in the refit" in out
    # The v2 store is untouched: the v3 rates' labels are their own.
    assert "v1/predictions/learn.json" not in host.files
    broken = Host()
    broken.files[f"v1/{RATES_STORE_PATH}"] = b"{"
    run = outlook_run(broken, world.utc("2026-01-08T13:00"), shadow_state())
    run.outlook_build = lambda learned: build_model(
        world.directory(), rates, CFG, lambda _x, _y: None, learned
    )
    assert cli.learn_once(run) == 0
    assert f"v1/{RATES_LEARNED_PATH}" not in broken.files
    assert "the v3 rates' labels do not read" in capsys.readouterr().out


def test_the_five_am_record_reads_as_the_labels_class_snapshots() -> None:
    from snowlight.predict.live_labels import snapshot_classes  # noqa: PLC0415
    from snowlight.predict.outlook_learn import morning_snapshots  # noqa: PLC0415
    from snowlight.predict.situations import Window  # noqa: PLC0415

    record = Record.from_json(
        shadow_state(), learn.content_key(world.directory()), len(world.DISTRICTS)
    )
    found = morning_snapshots(record)
    day = date(2026, 1, 7)
    classes = snapshot_classes(
        found,
        day,
        content=learn.content_key(world.directory()),
        zones=[world.ZONES[leaid] for leaid in world.DISTRICTS],
        window=Window(CFG.weather.window_from, CFG.weather.window_until, 21),
        slack=timedelta(minutes=60),
    )
    assert classes[1] is WeatherClass.SNOW_WARNING  # Missouri woke up to the warning
    assert classes[0] is WeatherClass.NONE  # Kansas's advisory was cancelled at 9 PM
