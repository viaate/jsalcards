"""The frozen record (predict-next P1): every chance served and its inputs, frozen four times a
night on each zone's clock, kept until both evidence databases hold the finished day, read back
typed, and never changing a byte of what is served. SYNTHETIC alerts, forecasts and districts
only (the test world's).
"""

import base64
import json
import shutil
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from predict import test_forecast_adjust as fa_test
from predict import world
from predict.test_publish import MemoryHost, make_pass
from snowlight.live.d1 import Answer, D1Error, Statement
from snowlight.live.evidence import (
    BACKUP,
    FROZEN,
    PRESETS,
    PRIMARY,
    EvidenceStore,
    Offer,
    compress,
    item_of,
    unpack,
)
from snowlight.predict import cli, frozen
from snowlight.predict import forecast_adjust as fa
from snowlight.predict.config import LIVE_SCORE_SHA256
from snowlight.predict.forecast_values import Forecasts
from snowlight.predict.night_serve import NO_NIGHTS
from snowlight.predict.publish import Mode
from snowlight.predict.serve import (
    SITUATION_POSITION,
    AdjustDetail,
    Fit,
    Noted,
    adjust_detail,
    forecast_file,
)
from snowlight.predict.situations import WeatherClass
from snowlight.schemas.predictions import Forecast, PredictionsFile
from snowlight.sources.nws.alerts import ActiveFeed, parse_active

PREDICT = {"GITHUB_WORKFLOW": "predict", "GITHUB_RUN_ID": "78"}
CHICAGO = "America/Chicago"
DENVER = "America/Denver"
DAY = date(2026, 1, 7)


def feed_at(
    now: datetime, *, code: str = "WS.W", event: str = "Winter Storm Warning"
) -> ActiveFeed:
    """A SYNTHETIC alert over the Missouri zone for Jan 7 (or Jan 14), fresh at ``now``."""
    features = [
        world.feature(
            f"/O.NEW.KEAX.{code}.0001.260106T0600Z-260115T0000Z/",
            ("MOZ028",),
            sent="2026-01-05T20:00:00+00:00",
            onset="2026-01-06T06:00:00+00:00",
            ends="2026-01-15T00:00:00+00:00",
            event=event,
        ),
        world.feature(
            "/O.NEW.KSLC.WS.A.0002.260106T0600Z-260115T0000Z/",
            ("UTZ105",),
            sent="2026-01-05T20:00:00+00:00",
            onset="2026-01-06T06:00:00+00:00",
            ends="2026-01-15T00:00:00+00:00",
            event="Winter Storm Watch",
        ),
    ]
    updated = (now - timedelta(minutes=5)).isoformat()
    return parse_active(world.feed_bytes(features, updated))


@dataclass
class FakeD1:
    """D1 as one in-memory SQLite database per D1 database; ``broken`` names fail every call
    (as tests/live/test_evidence.py's)."""

    dbs: dict[str, sqlite3.Connection] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    broken: set[str] = field(default_factory=set)

    def databases(self, name: str) -> list[tuple[str, str]]:
        return [(n, uuid) for n, uuid in self.names.items() if name in n]

    def create(self, name: str) -> str:
        uuid = f"uuid-{len(self.names) + 1}"
        self.names[name] = uuid
        self.dbs[uuid] = sqlite3.connect(":memory:")
        return uuid

    def run(self, database: str, statements: Sequence[Statement]) -> list[Answer]:
        name = next(n for n, uuid in self.names.items() if uuid == database)
        if name in self.broken:
            raise D1Error("query: HTTP 500")
        db = self.dbs[database]
        answers = []
        for sql, params in statements:
            before = db.total_changes
            cursor = db.execute(sql, params)
            names = [column[0] for column in cursor.description or ()]
            rows = tuple(dict(zip(names, row, strict=True)) for row in cursor.fetchall())
            db.commit()
            changes = db.total_changes - before
            answers.append(Answer(rows=rows, rows_written=changes, changes=changes))
        return answers


class Clock:
    def __init__(self, at: str) -> None:
        self.at = world.utc(at)

    def __call__(self) -> datetime:
        return self.at

    def to(self, at: str) -> None:
        self.at = world.utc(at)


def frozen_pass(folder: Path | None, clock: Clock, host: MemoryHost, **changes: Any) -> cli.Pass:
    run = make_pass(host, directory=world.directory(), now=clock())
    run.now = clock
    run.alerts = lambda: (feed_at(clock()), True)
    run.frozen = folder
    for key, value in changes.items():
        setattr(run, key, value)
    return run


def lines(folder: Path, day: date) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in frozen.day_path(folder, day.isoformat()).read_text().splitlines()
    ]


def headers(folder: Path, day: date) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (value["zone"], value["freeze"]): value
        for value in lines(folder, day)
        if value.get("k") in {"freeze", "missed"}
    }


# --- when ----------------------------------------------------------------------------------


def test_each_freeze_is_on_its_zone_s_clock_through_the_fall_and_spring_changes() -> None:
    # Nov 1 2026 (DST ends at 2 AM): Monday Nov 2's evening freezes are on standard time.
    monday = date(2026, 11, 2)
    east = "America/New_York"
    assert frozen.freeze_at(monday, east, "d1_2007") == world.utc("2026-11-02T01:07:00")
    assert frozen.freeze_at(monday, east, "d1_2130") == world.utc("2026-11-02T02:30:00")
    assert frozen.freeze_at(monday, east, "d0_0507") == world.utc("2026-11-02T10:07:00")
    assert frozen.freeze_at(monday, east, "d0_0630") == world.utc("2026-11-02T11:30:00")
    # the Friday before is still on daylight time
    friday = date(2026, 10, 30)
    assert frozen.freeze_at(friday, east, "d1_2007") == world.utc("2026-10-30T00:07:00")
    # spring forward (Mar 14 2027): Monday Mar 15's evening freeze is on daylight time
    spring = date(2027, 3, 15)
    assert frozen.freeze_at(spring, east, "d1_2007") == world.utc("2027-03-15T00:07:00")
    assert frozen.freeze_at(spring, east, "d0_0507") == world.utc("2027-03-15T09:07:00")
    assert frozen.freeze_at(spring, "America/Phoenix", "d0_0507") == world.utc(
        "2027-03-15T12:07:00"
    )
    # the four zones, Alaska and Hawaii
    for zone, hours in (
        ("America/Chicago", 11),
        ("America/Denver", 12),
        ("America/Los_Angeles", 13),
        ("America/Anchorage", 14),
        ("Pacific/Honolulu", 15),
    ):
        assert frozen.freeze_at(monday, zone, "d0_0507") == world.utc(f"2026-11-02T{hours}:07:00")
    # a day is finished an hour after Hawaii's 06:30 freeze
    assert frozen.finished_at(monday) == world.utc("2026-11-02T17:30:00")
    with pytest.raises(ValueError, match="no freeze"):
        frozen.freeze_at(monday, east, "d0_0700")


def test_every_freeze_is_taken_once_late_ones_say_so_and_over_90_minutes_is_missed(
    tmp_path: Path, capsys: Any
) -> None:
    clock = Clock("2026-01-07T02:10:00")  # 20:10 CST, 19:10 MST, Jan 6
    run = frozen_pass(tmp_path, clock, MemoryHost())
    assert cli.one_pass(run) == 0
    found = headers(tmp_path, DAY)
    assert list(found) == [(CHICAGO, "d1_2007")]
    first = found[CHICAGO, "d1_2007"]
    assert first["late_by_s"] == 180
    assert first["rows"] == 4
    assert first["live_score_sha256"] == LIVE_SCORE_SHA256
    assert first["at"] == "2026-01-07T02:07:00+00:00"
    out = capsys.readouterr().out
    assert "predict frozen: 2026-01-07 d1_2007: 1 zones, 4 rows (4 served), up to 180 s late" in out
    assert "predict frozen: recorded in " in out
    # Jan 6 was first seen finished: nothing to take, no file
    assert not frozen.day_path(tmp_path, "2026-01-06").exists()
    # a later pass never takes it again
    clock.to("2026-01-07T02:20:00")
    assert cli.one_pass(run) == 0
    assert list(headers(tmp_path, DAY)) == [(CHICAGO, "d1_2007")]
    clock.to("2026-01-07T03:40:00")  # 21:40 CST, 20:40 MST
    assert cli.one_pass(run) == 0
    found = headers(tmp_path, DAY)
    assert found[CHICAGO, "d1_2130"]["late_by_s"] == 600
    assert found[DENVER, "d1_2007"]["late_by_s"] == 33 * 60
    assert (DENVER, "d1_2130") not in found  # 21:30 MST is 04:30Z
    # no pass from midnight to 07:00 CST: Chicago's 05:07 is 113 minutes late, and Denver's
    # 21:30 the evening before 8.5 hours late, so both are missed
    clock.to("2026-01-07T13:00:00")
    assert cli.one_pass(run) == 0
    found = headers(tmp_path, DAY)
    assert found[CHICAGO, "d0_0507"]["k"] == "missed"
    assert found[CHICAGO, "d0_0507"]["districts"] == 4
    assert found[CHICAGO, "d0_0630"]["late_by_s"] == 30 * 60
    assert found[DENVER, "d0_0507"]["late_by_s"] == 53 * 60
    assert found[DENVER, "d1_2130"]["k"] == "missed"
    assert (DENVER, "d0_0630") not in found
    assert not frozen.offers(tmp_path)  # not finished yet
    # the day finishes at 17:30Z; Denver's 06:30 freeze, never taken, is missed
    clock.to("2026-01-07T18:00:00")
    assert cli.one_pass(run) == 0
    found = headers(tmp_path, DAY)
    assert found[DENVER, "d0_0630"]["k"] == "missed"
    assert len(found) == 8
    day = frozen.parse_day(frozen.day_path(tmp_path, DAY.isoformat()).read_bytes())
    assert len(day.rows) == 4 + 4 + 1 + 4 + 1  # Chicago 20:07, 21:30, 06:30; Denver 20:07, 05:07
    assert {(m.zone, m.freeze) for m in day.missed} == {
        (CHICAGO, "d0_0507"),
        (DENVER, "d1_2130"),
        (DENVER, "d0_0630"),
    }
    assert [key for key, _ in frozen.offers(tmp_path)] == ["2026-01-07"]
    # Jan 8 is known (it is in the file the passes served) but nothing of it was due yet
    assert "2026-01-08" in frozen.load_index(tmp_path).days
    assert not frozen.day_path(tmp_path, "2026-01-08").exists()


def test_a_row_holds_the_served_chances_the_class_and_the_alert_codes_only(
    tmp_path: Path,
) -> None:
    clock = Clock("2026-01-07T02:10:00")
    host = MemoryHost()
    run = frozen_pass(tmp_path, clock, host)
    assert cli.one_pass(run) == 0
    day = frozen.parse_day(frozen.day_path(tmp_path, DAY.isoformat()).read_bytes())
    by = {row.leaid: row for row in day.rows}
    assert set(by) == {"2000004", "2900001", "2900002", "2900003"}
    made = PredictionsFile.from_json_bytes(host.files["v1/predictions/latest.json"])
    d = made.days.index(DAY)
    for index, leaid in enumerate(world.DISTRICTS[:4]):
        item = made.districts[index].days[d]
        assert isinstance(item, Forecast)
        row = by[leaid]
        assert row.served
        assert (row.p, row.q) == (item.p_no_school, item.p_delay)
        assert row.p_raw is not None
        assert round(row.p_raw, 2) == item.p_no_school or row.p == 0.01
        assert row.variants == {}
        assert row.freeze == "d1_2007"
        assert row.zone == CHICAGO
        assert row.generated_at == made.generated_at
    # the Missouri districts are under the warning (the class, its alert and its span); the
    # Kansas one is not
    for leaid in ("2900001", "2900002", "2900003"):
        row = by[leaid]
        assert (row.situation, row.klass, row.alert) == (
            "snow_warning",
            "warning",
            "winter_storm_warning",
        )
        assert row.alert_begin == world.utc("2026-01-06T06:00:00")
        assert row.alert_end == world.utc("2026-01-15T00:00:00")
        assert not row.heights
    assert (by["2000004"].situation, by["2000004"].klass) == ("none", "none")
    assert by["2000004"].alert_begin is None
    # codes and numbers only: no names, no text, no URLs
    text = frozen.day_path(tmp_path, DAY.isoformat()).read_text()
    assert "http" not in text
    assert "Warning" not in text


def test_a_watch_reaching_a_district_is_flagged(tmp_path: Path) -> None:
    clock = Clock("2026-01-07T03:40:00")  # Denver's 20:07 freeze for Jan 7
    run = frozen_pass(tmp_path, clock, MemoryHost())
    assert cli.one_pass(run) == 0
    day = frozen.parse_day(frozen.day_path(tmp_path, DAY.isoformat()).read_bytes())
    utah = next(row for row in day.rows if row.leaid == "4900005")
    assert utah.watch == "winter_storm_watch"
    assert all(row.watch is None for row in day.rows if row.leaid != "4900005")


def adjusting_pass(folder: Path | None, clock: Clock, host: MemoryHost) -> cli.Pass:
    built, anchor = fa_test.adjusting_model(fa_test.NATION)
    del built
    heavy = replace(fa_test.forecast(6.0), run_time=fa_test.RUN, snow_bus=4.0)
    found = Forecasts({fa_test.DAY: {1: heavy, 2: fa_test.forecast(0.0)}})
    run = frozen_pass(folder, clock, host, anchor=anchor)
    run.forecast = lambda _model, _days, _now: found
    run.alerts = lambda: (
        feed_at(clock(), code="WW.Y", event="Winter Weather Advisory"),
        True,
    )
    return run


def test_an_adjusted_day_keeps_its_terms_clamps_inputs_and_unrounded_chance(
    tmp_path: Path,
) -> None:
    clock = Clock("2026-01-14T03:35:00")  # 21:35 CST Jan 13: past the 9 PM snapshot
    host = MemoryHost()
    run = adjusting_pass(tmp_path, clock, host)
    assert cli.one_pass(run) == 0
    day = frozen.parse_day(frozen.day_path(tmp_path, fa_test.DAY.isoformat()).read_bytes())
    # 20:07 was 88 minutes ago: taken late, with this pass's chance, and saying so
    assert {row.freeze for row in day.rows} == {"d1_2007", "d1_2130"}
    late = {r.late_by_s for r in day.rows if (r.freeze, r.zone) == ("d1_2007", CHICAGO)}
    assert late == {88 * 60}
    by = {row.leaid: row for row in day.rows if row.freeze == "d1_2130"}
    heavy, light, unread = by["2900001"], by["2900002"], by["2900003"]
    for row in (heavy, light, unread):
        assert (row.klass, row.base) == ("advisory", "class")
        assert row.points is not None
        assert row.level is not None
        assert row.offset is not None
    assert heavy.forecast_read == "read"
    assert heavy.p is not None
    assert heavy.points is not None
    assert heavy.p > heavy.points / 100
    assert heavy.forecast is not None
    assert heavy.forecast["sn"] == 6.0
    assert heavy.forecast["bb"] == 4.0  # the snow before the bus hour, on every freeze
    assert heavy.forecast["rt"] == fa_test.RUN.isoformat()
    assert len(heavy.forecast["pp"]) >= 1
    assert heavy.terms is not None
    assert len(heavy.terms["raw"]) == len(heavy.terms["b"]) == len(heavy.terms["cl"]) == 4
    assert heavy.p_raw is not None
    assert round(heavy.p_raw, 2) == heavy.p
    assert next(kind for kind, _ in heavy.reasons) == "snow_total"
    assert light.p is not None
    assert light.points is not None
    assert light.p < light.points / 100
    assert light.terms is not None
    # a dusting's snow term is clamped at the advisory's lower bound or not: it says which
    assert set(light.terms["cl"]) <= {0, 1}
    assert unread.forecast_read == "none"
    assert unread.terms is None
    assert unread.points is not None
    assert unread.p == unread.points / 100


def test_a_row_frozen_before_the_bus_hour_snow_was_kept_still_reads(tmp_path: Path) -> None:
    # BUS-TIMING: rows frozen before ``bb`` was kept read as they did, with no ``bb``.
    clock = Clock("2026-01-14T03:35:00")
    assert cli.one_pass(adjusting_pass(tmp_path, clock, MemoryHost())) == 0
    path = frozen.day_path(tmp_path, fa_test.DAY.isoformat())
    new = frozen.parse_day(path.read_bytes())
    old_lines = []
    for line in path.read_bytes().splitlines():
        value = json.loads(line)
        if isinstance(value.get("f"), dict):
            value["f"].pop("bb", None)
        old_lines.append(json.dumps(value).encode())
    old = frozen.parse_day(b"\n".join(old_lines))
    assert len(old.rows) == len(new.rows)
    assert any(row.forecast and "bb" in row.forecast for row in new.rows)
    for was, now in zip(old.rows, new.rows, strict=True):
        assert was.forecast is None or "bb" not in was.forecast
        bare = None
        if now.forecast is not None:
            bare = {k: v for k, v in now.forecast.items() if k != "bb"}
        assert was.forecast == bare
        assert (was.p, was.terms, was.leaid) == (now.p, now.terms, now.leaid)


def test_an_evening_freeze_before_the_snapshot_says_the_forecast_was_not_read_yet(
    tmp_path: Path,
) -> None:
    clock = Clock("2026-01-14T02:10:00")  # 20:10 CST Jan 13: before the 9 PM snapshot
    run = adjusting_pass(tmp_path, clock, MemoryHost())
    assert cli.one_pass(run) == 0
    day = frozen.parse_day(frozen.day_path(tmp_path, fa_test.DAY.isoformat()).read_bytes())
    missouri = [row for row in day.rows if row.leaid.startswith("29")]
    assert missouri
    assert all(row.forecast_read == "before" for row in missouri)
    assert all(row.terms is None for row in missouri)


# --- never changes what is served ---------------------------------------------------------

TIMES = (
    "2026-01-14T02:10:00",
    "2026-01-14T03:35:00",
    "2026-01-14T03:50:00",
    "2026-01-14T11:15:00",
    "2026-01-14T12:40:00",
    "2026-01-14T13:40:00",
    "2026-01-14T18:00:00",
)


def _passes(
    make: Callable[[Path | None, Clock, MemoryHost], cli.Pass], folder: Path | None
) -> list[dict[str, bytes]]:
    clock = Clock(TIMES[0])
    host = MemoryHost()
    run = make(folder, clock, host)
    found: list[dict[str, bytes]] = []
    for at in TIMES:
        clock.to(at)
        assert cli.one_pass(run, grid=True) == 0
        found.append(dict(host.files))
    return found


def test_every_public_file_is_the_same_byte_for_byte_with_the_record_on_or_off(
    tmp_path: Path,
) -> None:
    on = _passes(adjusting_pass, tmp_path / "frozen")
    off = _passes(adjusting_pass, None)
    assert on == off
    assert len(on[-1]) >= 1
    assert frozen.day_path(tmp_path / "frozen", fa_test.DAY.isoformat()).is_file()


def test_a_recorder_that_fails_warns_once_and_the_pass_publishes_as_before(
    tmp_path: Path, capsys: Any
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the folder should be")
    broken = _passes(adjusting_pass, blocked)
    assert broken == _passes(adjusting_pass, None)
    err = capsys.readouterr().err
    assert err.count("frozen record: ") == len(TIMES)  # once a pass
    assert "nothing frozen this pass" in err


def test_a_pass_that_stopped_mid_write_never_holds_a_freeze_twice(tmp_path: Path) -> None:
    clock = Clock("2026-01-07T02:10:00")
    run = frozen_pass(tmp_path, clock, MemoryHost())
    assert cli.one_pass(run) == 0
    path = frozen.day_path(tmp_path, DAY.isoformat())
    good = path.read_bytes()
    with path.open("ab") as handle:  # a write the index never counted
        handle.write(b'{"k":"freeze","day":"2026-01-07","freeze":"d1_2130"')
    clock.to("2026-01-07T03:40:00")
    assert cli.one_pass(run) == 0
    data = path.read_bytes()
    assert data.startswith(good)
    day = frozen.parse_day(data)
    assert sum(1 for z, f in day.groups if f == "d1_2130") == 1


def test_not_public_rows_say_so(tmp_path: Path) -> None:
    clock = Clock("2026-01-07T02:10:00")
    run = frozen_pass(tmp_path, clock, MemoryHost(), mode=Mode.SHADOW)
    assert cli.one_pass(run) == 0
    day = frozen.parse_day(frozen.day_path(tmp_path, DAY.isoformat()).read_bytes())
    assert day.rows
    assert all(not row.served and row.why == "not_public" for row in day.rows)
    assert all(row.p is not None for row in day.rows)


# --- the evidence, the check and the restore drill ------------------------------------------


def _finished_day(folder: Path) -> bytes:
    clock = Clock("2026-01-07T02:10:00")
    run = frozen_pass(folder, clock, MemoryHost())
    for at in ("2026-01-07T02:10:00", "2026-01-07T03:40:00", "2026-01-07T13:00:00",
               "2026-01-07T18:00:00"):  # fmt: skip
        clock.to(at)
        assert cli.one_pass(run) == 0
    [(key, data)] = frozen.offers(folder)
    assert key == DAY.isoformat()
    return data


def test_a_finished_day_is_kept_in_both_databases_then_leaves_the_folder(
    tmp_path: Path, capsys: Any
) -> None:
    folder = tmp_path / "frozen"
    data = _finished_day(folder)
    api = FakeD1()
    store = EvidenceStore(api, PREDICT, lambda: world.utc("2026-01-07T19:00:00"))
    now = world.utc("2026-01-07T19:00:00")
    assert cli.keep_evidence(store, {}, {}, now, frozen_folder=folder) == 0
    assert "1 finished files offered" in capsys.readouterr().out
    assert store.pull(FROZEN) == {DAY.isoformat(): data}
    # one database answered so far: the day stays
    held = store.held((FROZEN,))
    assert frozen.note_held(folder, {PRIMARY: held[PRIMARY]}, now) == []
    assert frozen.day_path(folder, DAY.isoformat()).is_file()
    cli.note_frozen(store, folder, now)
    assert not frozen.day_path(folder, DAY.isoformat()).exists()
    index = frozen.load_index(folder)
    assert DAY.isoformat() in index.done
    assert DAY.isoformat() not in index.days
    # a later pass the same day never takes the day up again
    clock = Clock("2026-01-07T19:10:00")
    run = frozen_pass(folder, clock, MemoryHost())
    assert cli.one_pass(run) == 0
    assert not frozen.day_path(folder, DAY.isoformat()).exists()
    # and the reader gets it from the store
    found = frozen.rows(DAY, DAY, folder, store)
    assert found[DAY] == frozen.parse_day(data)


def test_the_check_fails_when_a_finished_day_waits_two_days_for_both_databases(
    tmp_path: Path, capsys: Any
) -> None:
    folder = tmp_path / "frozen"
    _finished_day(folder)
    state = tmp_path / "state.json"
    assert cli.check_kept(state, world.utc("2026-01-08T19:00:00"), folder) == 0
    assert "1 finished frozen days wait for both databases" in capsys.readouterr().out
    assert cli.check_kept(state, world.utc("2026-01-09T18:00:00"), folder) == 1
    out = capsys.readouterr().out
    assert "::error::predict evidence: 1 finished frozen days" in out
    # held by both: nothing waits
    api = FakeD1()
    store = EvidenceStore(api, PREDICT, lambda: world.utc("2026-01-09T18:00:00"))
    assert (
        cli.keep_evidence(store, {}, {}, world.utc("2026-01-09T18:00:00"), frozen_folder=folder)
        == 0
    )
    cli.note_frozen(store, folder, world.utc("2026-01-09T18:00:00"))
    assert cli.check_kept(state, world.utc("2026-01-09T18:00:00"), folder) == 0


def test_the_restore_drill_deletes_the_folder_and_takes_the_days_back(tmp_path: Path) -> None:
    folder = tmp_path / "frozen"
    data = _finished_day(folder)
    api = FakeD1()
    now = world.utc("2026-01-07T19:00:00")
    store = EvidenceStore(api, PREDICT, lambda: now)
    # kept in the primary only so far (the backup did not answer that push)
    primary = EvidenceStore(api, PREDICT, lambda: now, names=(PRIMARY,))
    assert cli.keep_evidence(primary, {}, {}, now, frozen_folder=folder) == 0
    cli.note_frozen(store, folder, now)
    assert BACKUP not in api.names
    assert frozen.day_path(folder, DAY.isoformat()).is_file()  # one copy: it stays
    before = frozen.rows(DAY, DAY, folder)
    # the Actions cache is lost: the folder is gone; the next run's passes begin afresh
    for path in folder.iterdir():
        path.unlink()
    folder.rmdir()
    clock = Clock("2026-01-07T19:30:00")
    run = frozen_pass(folder, clock, MemoryHost())
    assert cli.one_pass(run) == 0
    assert frozen.load_index(folder).fresh
    assert frozen.rows(DAY, DAY, folder) == {}
    # the evidence step restores what the store holds, then keeps it until both hold it
    cli.restore_frozen(store, folder, world.utc("2026-01-07T20:00:00"))
    assert frozen.day_path(folder, DAY.isoformat()).read_bytes() == data
    assert frozen.rows(DAY, DAY, folder) == before
    index = frozen.load_index(folder)
    assert not index.fresh
    assert index.days[DAY.isoformat()].closed is not None
    assert cli.keep_evidence(store, {}, {}, now, frozen_folder=folder) == 0
    cli.note_frozen(store, folder, now)
    assert not frozen.day_path(folder, DAY.isoformat()).exists()
    assert frozen.restore(folder, store, now) == []  # only once, after a loss


def test_the_reader_reads_a_day_range_typed_from_the_folder_else_the_store(tmp_path: Path) -> None:
    folder = tmp_path / "frozen"
    _finished_day(folder)
    found = frozen.rows(DAY - timedelta(days=1), DAY + timedelta(days=1), folder)
    assert set(found) == {DAY}  # Jan 8 holds nothing yet
    rows = found[DAY].rows
    assert rows
    assert {row.day for row in rows} == {DAY}
    assert all(row.live_score_sha256 == LIVE_SCORE_SHA256 for row in rows)
    with pytest.raises(ValueError, match="no freeze before it"):
        frozen.parse_day(b'{"l":"2900001","s":1}\n')
    with pytest.raises(ValueError, match="empty"):
        frozen.parse_day(b"\n")


# --- a lost or cut folder, and every copy of a day (critic r1 S1-S3) ------------------------


def _run_to(folder: Path, times: Sequence[str]) -> None:
    clock = Clock(times[0])
    run = frozen_pass(folder, clock, MemoryHost())
    for at in times:
        clock.to(at)
        assert cli.one_pass(run) == 0


def test_a_day_closed_from_an_older_folder_reads_back_with_every_freeze_taken_anywhere(
    tmp_path: Path,
) -> None:
    folder, older = tmp_path / "a", tmp_path / "b"
    _run_to(folder, ("2026-01-07T02:10:00", "2026-01-07T03:40:00"))
    shutil.copytree(folder, older)  # the cache the next run restores (this run's save failed)
    _run_to(folder, ("2026-01-07T13:00:00", "2026-01-07T18:00:00"))
    now = world.utc("2026-01-07T19:00:00")
    store = EvidenceStore(FakeD1(), PREDICT, lambda: now)
    assert cli.keep_evidence(store, {}, {}, now, frozen_folder=folder) == 0
    taken = frozen.parse_day(frozen.offers(folder)[0][1]).groups
    assert taken[CHICAGO, "d0_0630"] == taken[DENVER, "d0_0507"] == "taken"
    # the next run, on the older folder, closes the day without the freezes taken since
    _run_to(older, ("2026-01-07T18:30:00",))
    stale = frozen.parse_day(frozen.offers(older)[0][1]).groups
    assert stale[CHICAGO, "d0_0630"] == stale[DENVER, "d0_0507"] == "missed"
    assert cli.keep_evidence(store, {}, {}, now, frozen_folder=older) == 0
    assert len(store.pull_all(FROZEN)) == 2  # two versions of the day kept
    # the reader merges every copy: a freeze taken anywhere is read taken, once
    for found in (frozen.rows(DAY, DAY, older, store), frozen.rows(DAY, DAY, tmp_path, store)):
        assert dict(found[DAY].groups) == dict(taken)
        assert found[DAY] == frozen.parse_day(frozen.offers(folder)[0][1])
    # and so does a restore after a lost folder
    fresh = tmp_path / "c"
    assert frozen.restore(fresh, store, now) == [DAY.isoformat()]
    assert frozen.rows(DAY, DAY, fresh)[DAY].groups == taken


def test_merge_keeps_a_day_s_one_version_byte_for_byte_and_the_first_taken_copy(
    tmp_path: Path,
) -> None:
    data = _finished_day(tmp_path / "frozen")
    assert frozen.merge([data]) == data
    assert frozen.merge([data, data]) == data
    assert frozen.merge([data + b'{"k":"freeze","day"']) == data  # a torn tail left out
    first = frozen.parse_day(data)
    # a copy of Chicago's 20:07 freeze taken later never replaces the one taken first
    later = data.replace(b'"late_by_s":180', b'"late_by_s":900', 1)
    assert later != data
    assert frozen.parse_day(frozen.merge([later, data])) == first


def test_a_lost_or_unreadable_index_is_made_again_from_the_day_files(tmp_path: Path) -> None:
    clock = Clock("2026-01-07T02:10:00")
    run = frozen_pass(tmp_path, clock, MemoryHost())
    assert cli.one_pass(run) == 0
    before = frozen.day_path(tmp_path, DAY.isoformat()).read_bytes()
    for broken in (b"{not json", json.dumps({"schema": frozen.SCHEMA + 1}).encode()):
        (tmp_path / frozen.INDEX).write_bytes(broken)
        index = frozen.load_index(tmp_path)
        assert index.fresh
        assert index.days[DAY.isoformat()].groups == {f"{CHICAGO}|d1_2007": "taken"}
        assert index.days[DAY.isoformat()].bytes == len(before)
    # the next pass keeps the freeze taken (never truncated into missed) and takes the next
    clock.to("2026-01-07T03:40:00")
    assert cli.one_pass(run) == 0
    data = frozen.day_path(tmp_path, DAY.isoformat()).read_bytes()
    assert data.startswith(before)
    groups = frozen.parse_day(data).groups
    assert groups[CHICAGO, "d1_2007"] == groups[CHICAGO, "d1_2130"] == "taken"
    # a finished day no database holds yet is still offered after its index was lost
    _run_to(tmp_path, ("2026-01-07T13:00:00", "2026-01-07T18:00:00"))
    offered = frozen.offers(tmp_path)
    (tmp_path / frozen.INDEX).unlink()
    _run_to(tmp_path, ("2026-01-07T18:30:00",))
    assert frozen.offers(tmp_path) == offered


def test_a_cut_day_file_is_cut_back_to_its_last_whole_freeze_and_reads(tmp_path: Path) -> None:
    clock = Clock("2026-01-07T02:10:00")
    run = frozen_pass(tmp_path, clock, MemoryHost())
    assert cli.one_pass(run) == 0
    path = frozen.day_path(tmp_path, DAY.isoformat())
    data = path.read_bytes()
    path.write_bytes(data[:-40])  # a cache that came back short
    clock.to("2026-01-07T02:20:00")  # Chicago's 20:07 freeze is still due: taken again
    assert cli.one_pass(run) == 0
    day = frozen.parse_day(path.read_bytes())
    assert day.groups == {(CHICAGO, "d1_2007"): "taken"}
    assert {row.late_by_s for row in day.rows} == {13 * 60}
    assert len(day.rows) == 4
    # a finished day cut short is closed again, the lost freeze written missed, and reads
    _run_to(tmp_path, ("2026-01-07T03:40:00", "2026-01-07T13:00:00", "2026-01-07T18:00:00"))
    data = path.read_bytes()
    path.write_bytes(data[:-40])
    _run_to(tmp_path, ("2026-01-07T18:30:00",))
    [(_key, kept)] = frozen.offers(tmp_path)
    day = frozen.parse_day(kept)
    assert len(day.groups) == 8
    assert frozen.load_index(tmp_path).days[DAY.isoformat()].bytes == len(kept)


# --- what the public saw, and what the file applied (critic r1 S4, S5) ----------------------


def test_a_pass_that_found_its_file_unchanged_freezes_what_the_public_file_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # no previous chances read from the host, so the blank file leaves the loop's unchanged
    monkeypatch.setattr(cli, "_last_file", lambda _run: None)
    clock = Clock("2026-01-07T02:00:00")  # 20:00 CST: no freeze due yet
    host = MemoryHost()
    run = frozen_pass(tmp_path, clock, host)
    assert cli.one_pass(run) == 0
    # an unchanged pass, the public file as it uploaded it: served
    clock.to("2026-01-07T02:10:00")
    assert cli.one_pass(run, grid=False) == 0
    day = frozen.parse_day(frozen.day_path(tmp_path, DAY.isoformat()).read_bytes())
    assert day.rows
    assert all(row.served for row in day.rows)
    clock.to("2026-01-07T03:00:00")  # the heartbeat uploads it again
    assert cli.one_pass(run) == 0
    # predict blank: the public file has no districts; the loop's file is unchanged
    cli.blank(host, world.STAMP, run.config, clock())
    clock.to("2026-01-07T03:10:00")  # Denver's 20:07 freeze, off the grid
    assert cli.one_pass(run, grid=False) == 0
    day = frozen.parse_day(frozen.day_path(tmp_path, DAY.isoformat()).read_bytes())
    held = [row for row in day.rows if row.zone == DENVER]
    assert held
    assert all(not row.served and row.why == "not_shown" for row in held)
    header = headers(tmp_path, DAY)[DENVER, "d1_2007"]
    assert (header["public"], header["why"]) == (False, "not_shown")


def test_a_public_file_that_does_not_read_back_is_not_called_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_last_file", lambda _run: None)
    clock = Clock("2026-01-07T02:00:00")
    host = MemoryHost()
    run = frozen_pass(tmp_path, clock, host)
    assert cli.one_pass(run) == 0
    read = host.read

    def broken(key: str) -> bytes | None:
        if key.endswith("latest.json"):
            raise OSError("host down")
        return read(key)

    monkeypatch.setattr(host, "read", broken)
    clock.to("2026-01-07T02:10:00")
    assert cli.one_pass(run, grid=False) == 0
    day = frozen.parse_day(frozen.day_path(tmp_path, DAY.isoformat()).read_bytes())
    assert all(not row.served and row.why == "unconfirmed" for row in day.rows)


def test_a_file_that_did_not_apply_the_forecast_says_no_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock("2026-01-14T03:35:00")
    # the size ladder down to the file with no reasons: the adjustment is not applied
    monkeypatch.setattr(cli, "_fit_steps", lambda *_a, **_k: iter([(Fit.NO_REASONS, NO_NIGHTS)]))
    run = adjusting_pass(tmp_path, clock, MemoryHost())
    assert cli.one_pass(run) == 0
    day = frozen.parse_day(frozen.day_path(tmp_path, fa_test.DAY.isoformat()).read_bytes())
    missouri = [row for row in day.rows if row.leaid.startswith("29")]
    assert missouri
    assert all(row.forecast_read is None and row.terms is None for row in missouri)
    assert all(row.forecast is None for row in missouri)


def test_an_outlook_file_s_rows_hold_what_it_published_not_the_model_s_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken: list[frozen.PassInputs] = []

    def keep(inputs: frozen.PassInputs, _folder: Path) -> list[frozen.Taken]:
        taken.append(inputs)
        return []

    monkeypatch.setattr(frozen, "record", keep)
    clock = Clock("2026-01-14T03:35:00")
    assert cli.one_pass(adjusting_pass(tmp_path, clock, MemoryHost())) == 0
    [inputs] = taken
    assert (inputs.maker, inputs.adjusted) == ("model", True)
    monkeypatch.undo()
    frozen.record(replace(inputs, maker="outlook", adjusted=False), tmp_path)
    found = lines(tmp_path, fa_test.DAY)
    head = next(value for value in found if value.get("k") == "freeze")
    assert head["maker"] == "outlook"
    rows = [value for value in found if "l" in value and value.get("s") == 1]
    assert rows
    for row in rows:
        assert not {"lv", "o", "pr", "qr", "fr", "f", "t"} & set(row)
        assert {"p", "q", "sit", "c"} <= set(row)


def test_a_row_keeps_bounded_terms_only_where_one_was_clamped() -> None:
    parts = fa.TermParts(
        raw=(0.123456, 0.0, 0.0, 0.0), bounded=(0.123456, 0.0, 0.0, 0.0), snow=1.0,
        weighted=1.0, ice=0.0, low=-0.7, high=2.0,
    )  # fmt: skip
    detail = AdjustDetail("advisory", 0.3, world.utc("2026-01-14T02:00:00"), parts=parts)
    kept = frozen._terms_json(detail)
    assert kept == {"raw": [0.1235, 0.0, 0.0, 0.0], "lo": -0.7, "hi": 2.0}
    read = frozen._terms_read(kept)
    assert read is not None
    assert (read["b"], read["cl"]) == (read["raw"], [0, 0, 0, 0])
    clamped = replace(parts, raw=(3.0, 0.0, 0.0, 0.0), bounded=(2.0, 0.0, 0.0, 0.0))
    kept = frozen._terms_json(replace(detail, parts=clamped))
    assert kept is not None
    assert (kept["b"], kept["cl"]) == ([2.0, 0.0, 0.0, 0.0], [1, 0, 0, 0])


# --- the served arithmetic, pinned to the code before the record (critic r1 S8) -------------

PINNED = (
    # class, usual, snow, ice, feels, the most the terms add, the old code's terms, chances
    ("advisory", 0.68, 0.0, 0.08, 5, None, 0.9507762933965818, (0.53, 0.09)),
    ("advisory", 0.68, 0.4, 0.0, 25, None, -0.2708749541353998, (0.25, 0.15)),
    ("advisory", 0.68, 1.6, 0.0, 25, None, 0.5764229062518038, (0.43, 0.11)),
    ("advisory", 0.68, 1.6, 0.0, 25, 0.4, 0.4, (0.43, 0.11)),
    ("advisory", 0.68, 5.0, 0.0, 25, None, 1.5392336537608517, (0.67, 0.07)),
    ("advisory", 4.0, 0.0, 0.3, -25, None, 0.8753641449035616, (0.51, 0.1)),
    ("advisory", 4.0, 2.5, 0.0, 25, None, -0.44107096356237907, (0.22, 0.16)),
    ("advisory", 4.0, 5.0, 0.08, 5, 0.4, 0.4000000000000001, (0.47, 0.11)),
    ("advisory", 4.0, 9.0, 0.3, -25, None, 1.629135947279942, (0.69, 0.06)),
    ("advisory", 4.0, 20.0, 0.08, 5, None, 1.7103069998445346, (0.7, 0.06)),
    ("warning", 0.68, 0.0, 0.0, 25, None, -0.4, (0.22, 0.16)),
    ("warning", 0.68, 0.0, 0.3, -25, None, 1.5, (0.66, 0.07)),
)
SPLITS = {0.9: (0.6, 0.3, 0.1), 2.5: (0.2, 0.3, 0.5), 3.0: (0.7, 0.2, 0.1), 20.0: (0.1, 0.2, 0.7)}


@pytest.mark.parametrize("case", PINNED)
def test_the_terms_and_chances_served_are_the_old_code_s_and_the_record_s_agree(
    case: tuple[str, float, float, float, int, float | None, float, tuple[float, float]],
) -> None:
    klass, usual, snow, ice, feels, most, old, shown = case
    found = fa_test.forecast(snow, split=SPLITS.get(snow), ice=ice, feels=feels)
    args = (found, usual, klass, fa_test.DAY, fa_test.EAST, fa_test.SETTINGS)
    terms = fa.day_terms(*args, None, most)
    assert terms is not None
    assert sum(terms.values.values()) == pytest.approx(old, abs=1e-12)
    parts = fa.term_parts(*args, None, most)
    assert parts is not None
    assert sum(parts.bounded) == pytest.approx(old, abs=1e-12)
    cap = None if most is None else 0.5
    moved = fa.adjusted(
        0.3, 0.2, klass, usual, found, fa_test.DAY, fa_test.EAST, fa_test.SETTINGS, 0.01, 0.99,
        cap=cap,
    )  # fmt: skip
    assert moved is not None
    assert (moved.p_no_school, moved.p_delay) == shown
    _parts, raw = fa.terms_detail(
        0.3, klass, usual, found, fa_test.DAY, fa_test.EAST, fa_test.SETTINGS, cap
    )
    assert raw is not None
    assert min(max(round(raw, 2), 0.01), 0.99) == moved.p_no_school


def test_noting_the_terms_changes_no_byte_of_the_file_and_they_are_the_ones_worked_out() -> None:
    model, _anchor = fa_test.adjusting_model(fa_test.NATION)
    heavy = replace(fa_test.forecast(6.0), run_time=fa_test.RUN)
    found = Forecasts({fa_test.DAY: {1: heavy, 2: fa_test.forecast(0.0)}})
    days = (fa_test.DAY, fa_test.DAY + timedelta(days=1))
    weather = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    now = world.utc("2026-01-14T03:35:00")
    noted: dict[tuple[int, date], Noted] = {}
    made = [
        forecast_file(
            model, weather, days, now, closed_on=lambda _d: None, last=None, forecasts=found,
            adjust=True, noted=sink,
        ).to_json_bytes()
        for sink in (None, noted)
    ]  # fmt: skip
    assert made[0] == made[1]
    assert {key for key, value in noted.items() if value.parts is not None} >= {
        (1, fa_test.DAY),
        (2, fa_test.DAY),
    }
    k = SITUATION_POSITION["advisory"]
    for index, day in noted:
        kept = adjust_detail(model, index, k, day, found, now, noted)
        again = adjust_detail(model, index, k, day, found, now)
        assert kept == again


def test_a_frozen_day_is_kept_at_the_frozen_kind_s_xz_preset_and_reads_back(
    tmp_path: Path,
) -> None:
    data = _finished_day(tmp_path / "frozen")
    item, parts = item_of(Offer(FROZEN, DAY.isoformat(), data), "2026-01-07T19:00:00+00:00")
    packed = b"".join(base64.b64decode(part) for part in parts)
    assert packed == compress(data, PRESETS[FROZEN])
    assert PRESETS[FROZEN] == 9
    assert unpack(item, parts) == data
