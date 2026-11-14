"""The record's tests (each-school, spec section 14 "record"). P0 adds the evidence store's
``record`` kind and its caps; P2a1 adds record.py's own tests here.

SYNTHETIC record days only: codes, ids, counts and times.
"""

import json
import math
import random
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from predict import world
from predict.test_frozen import FakeD1
from predict.test_live_read import ZERO
from snowlight.directory.points import Points
from snowlight.live import evidence
from snowlight.live.evidence import (
    BACKUP,
    MORNING,
    PRIMARY,
    EvidenceError,
    EvidenceStore,
    Offer,
    PartialPushError,
    item_of,
)
from snowlight.predict import record
from snowlight.predict.config import PIPELINE_ROOT, PredictConfig
from snowlight.predict.labels import WEATHER_REASONS
from snowlight.predict.live_read import ReadDay, ReadRow
from snowlight.predict.record import (
    Call,
    Cause,
    Previous,
    RecordDay,
    RecordError,
    RecordRow,
    RecordRun,
    Scope,
    SourceKind,
    Units,
)
from snowlight.predict.serve import CHARTER, PRIVATE
from snowlight.predict.situations import WeatherClass
from snowlight.schemas.live import DayIndex, DayTimeline
from snowlight.schemas.stats import ReadAuditDay, ReadClass
from snowlight.schemas.vocab import Reason, Status

NOW = datetime(2026, 12, 3, 12, tzinfo=UTC)
LIVE = {"GITHUB_WORKFLOW": "live-read", "GITHUB_RUN_ID": "77"}
PREDICT = {"GITHUB_WORKFLOW": "predict", "GITHUB_RUN_ID": "78"}
RECORD_JOB = {"GITHUB_WORKFLOW": "each-school record", "GITHUB_RUN_ID": "79"}


def _store(api: FakeD1, env: dict[str, str]) -> EvidenceStore:
    return EvidenceStore(api, env, lambda: NOW)


def _items(api: FakeD1) -> dict[str, int]:
    """The item rows each database holds."""
    return {
        name: int(api.dbs[uuid].execute("SELECT COUNT(*) FROM items").fetchone()[0])
        for name, uuid in sorted(api.names.items())
    }


def _record_day(key: str, rows: int, *, salt: str = "") -> Offer:
    """A SYNTHETIC record day: codes, ids, counts and times only."""
    lines = [
        json.dumps({"unit": f"{9_900_000 + n}", "call": "C", "source": 7, "n": n, "s": salt})
        for n in range(rows)
    ]
    return Offer(evidence.RECORD, key, ("\n".join(lines) + "\n").encode())


def _stored(*offers: Offer) -> int:
    return sum(math.ceil(item_of(o, "t")[0].packed * 4 / 3) for o in offers)


def test_only_the_record_job_keeps_the_record() -> None:
    api = FakeD1()
    day = _record_day("2026-12-01", 3)
    for env in (LIVE, PREDICT, {}):
        with pytest.raises(EvidenceError, match="does not keep"):
            _store(api, env).push([day], (evidence.RECORD,))
    with pytest.raises(EvidenceError, match="does not keep"):
        _store(api, RECORD_JOB).push([], (MORNING,))
    assert evidence.RECORD in evidence.KINDS
    assert evidence.WRITERS["each-school record"] == {evidence.RECORD}
    assert all(
        evidence.RECORD not in kinds
        for name, kinds in evidence.WRITERS.items()
        if name != "each-school record"
    )
    reports = _store(api, RECORD_JOB).push([day], (evidence.RECORD,))
    assert [(r.database, r.kept) for r in reports] == [(PRIMARY, 1), (BACKUP, 1)]
    assert _store(api, RECORD_JOB).pull(evidence.RECORD) == {"2026-12-01": day.data}


@pytest.mark.parametrize(
    "row",
    [
        b'{"unit": "9900001", "u": "https://x.invalid/"}\n',
        b'{"unit": "9900001", "u": "HTTP://X.INVALID/"}\n',
        b'{"unit": "9900001", "u": "www.x.invalid/closings"}\n',
        b'{"unit": "9900001", "u": "WWW.X.INVALID"}\n',
    ],
)
def test_the_record_holds_no_address(row: bytes) -> None:
    api = FakeD1()
    bad = Offer(evidence.RECORD, "2026-12-01", row)
    with pytest.raises(EvidenceError, match="holds an address"):
        _store(api, RECORD_JOB).push([_record_day("2026-11-30", 2), bad], (evidence.RECORD,))
    # nothing was written, the good day included
    assert set(_items(api).values()) <= {0}


def test_the_record_kinds_caps_refuse_an_oversized_write(monkeypatch: pytest.MonkeyPatch) -> None:
    assert evidence.RECORD_DAY_BYTES == 2 * 1024 * 1024
    # under a tenth of the room left below the warning on Nov 13 2026 (731,934 B held)
    assert evidence.RECORD_TOTAL_BYTES <= (evidence.WARN_BYTES - 731_934) // 10
    api = FakeD1()
    first = _record_day("2026-12-01", 40, salt="a")
    monkeypatch.setattr(evidence, "RECORD_DAY_BYTES", 2 * len(first.data) + 1)
    _store(api, RECORD_JOB).push([first], (evidence.RECORD,))
    # A second version of the same day fits; a third would pass the day's cap (every version
    # of a key counts), so nothing of that push is written, another day's version included.
    second = _record_day("2026-12-01", 40, salt="b")
    assert [r.kept for r in _store(api, RECORD_JOB).push([second], (evidence.RECORD,))] == [1, 1]
    third = _record_day("2026-12-01", 40, salt="c")
    other = _record_day("2026-12-02", 3)
    with pytest.raises(EvidenceError, match=r"2026-12-01: refused, .* over its"):
        _store(api, RECORD_JOB).push([other, third], (evidence.RECORD,))
    assert _items(api) == {
        PRIMARY: 2,
        BACKUP: 2,
    }
    # The total cap counts stored bytes of every record day a database holds.
    held = _stored(first, second)
    monkeypatch.setattr(evidence, "RECORD_TOTAL_BYTES", held + _stored(other) - 1)
    with pytest.raises(EvidenceError, match=r"record: refused, .* over its"):
        _store(api, RECORD_JOB).push([other], (evidence.RECORD,))
    monkeypatch.setattr(evidence, "RECORD_TOTAL_BYTES", held + _stored(other))
    assert [r.kept for r in _store(api, RECORD_JOB).push([other], (evidence.RECORD,))] == [1, 1]


def test_the_caps_count_what_the_copy_step_fills_in_from_the_other_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeD1()
    _store(api, RECORD_JOB).push([], (evidence.RECORD,))  # both exist
    one = _record_day("2026-12-01", 40, salt="a")
    two = _record_day("2026-12-02", 40, salt="b")
    # The databases part: each holds one day the other lacks.
    api.broken = {PRIMARY}
    with pytest.raises(PartialPushError):
        _store(api, RECORD_JOB).push([one], (evidence.RECORD,))
    api.broken = {BACKUP}
    with pytest.raises(PartialPushError):
        _store(api, RECORD_JOB).push([two], (evidence.RECORD,))
    api.broken = set()
    assert _items(api) == {
        PRIMARY: 1,
        BACKUP: 1,
    }
    # Each alone is under the total cap, but the copy step would leave both holding both.
    monkeypatch.setattr(evidence, "RECORD_TOTAL_BYTES", _stored(one, two) - 1)
    with pytest.raises(EvidenceError, match=r"record: refused, a database would hold"):
        _store(api, RECORD_JOB).push([], (evidence.RECORD,))
    assert _items(api) == {
        PRIMARY: 1,
        BACKUP: 1,
    }
    # The day cap too: two versions of one day, one in each database.
    monkeypatch.setattr(evidence, "RECORD_TOTAL_BYTES", 30_000_000)
    again = _record_day("2026-12-01", 40, salt="c")
    monkeypatch.setattr(evidence, "RECORD_DAY_BYTES", len(one.data) + len(again.data) - 1)
    api.broken = {BACKUP}
    with pytest.raises(PartialPushError):
        _store(api, RECORD_JOB).push([again], (evidence.RECORD,))
    api.broken = set()
    with pytest.raises(EvidenceError, match=r"2026-12-01: refused, a database would hold"):
        _store(api, RECORD_JOB).push([], (evidence.RECORD,))
    monkeypatch.setattr(evidence, "RECORD_DAY_BYTES", len(one.data) + len(again.data))
    monkeypatch.setattr(evidence, "RECORD_TOTAL_BYTES", _stored(one, two, again))
    reports = _store(api, RECORD_JOB).push([], (evidence.RECORD,))
    assert sum(r.copied for r in reports) == 3
    assert _items(api) == {
        PRIMARY: 3,
        BACKUP: 3,
    }


# --- P2a1: the record rows (record.py) ----------------------------------------------------------
# SYNTHETIC districts, schools, timelines and read days only.

NON_WEATHER: Final = (int(Reason.HEAT), int(Reason.POWER_OUTAGE), 8, 9, 41)
"""SYNTHETIC: stated causes that are not the weather (heat, a power outage, codes above 7)."""

RULE = PredictConfig.load(PIPELINE_ROOT / "config" / "predict.yaml").labels
THU = date(2026, 12, 3)
WED = date(2026, 12, 2)
DIGEST = "a" * 64
# SYNTHETIC districts: 9900001 schools 0-3, 9900002 schools 4-5, 9900003 school 6,
# 9900004 schools 7-9 (none of them alerted on the read day).
UNITS = Units(
    districts=("9900001", "9900002", "9900003", "9900004"),
    eligible=(
        np.array([0, 1, 2, 3], dtype=np.int64),
        np.array([4, 5], dtype=np.int64),
        np.array([6], dtype=np.int64),
        np.array([7, 8, 9], dtype=np.int64),
    ),
    content=DIGEST,
    stamp=world.STAMP,
    digest=DIGEST,
)
AT = 7 * 60  # 07:00 local, inside the morning
type Change = tuple[int, int, Status | None, int | None]


def _timeline(day: date = THU, changes: Sequence[Change] = (), **extra: Any) -> DayTimeline:
    """SYNTHETIC: (school, minute, status, reason code) changes."""
    ordered = sorted(changes, key=lambda c: (c[0], c[1]))
    schools = sorted({c[0] for c in ordered})
    gaps = tuple(s - (schools[i - 1] if i else -1) - 1 for i, s in enumerate(schools))
    shifted = [c for c in ordered if c[2] in (Status.DELAYED, Status.EARLY_DISMISSAL)]
    body: dict[str, Any] = {
        "schema_version": 1,
        "day": day,
        "generated_at": datetime.combine(day + timedelta(days=1), time(8), tzinfo=UTC),
        "directory": world.STAMP,
        "content_sha256": DIGEST,
        "final": True,
        "gaps": gaps,
        "counts": tuple(sum(1 for c in ordered if c[0] == s) for s in schools),
        "minutes": tuple(c[1] for c in ordered),
        "statuses": tuple(c[2] for c in ordered),
        "reasons": tuple(c[3] for c in ordered),
        "shifts": tuple(60 for _ in shifted),
        "clocks": tuple(600 for _ in shifted),
        **extra,
    }
    return DayTimeline.model_validate(body)


def _row(district: str, label: str, weather: int = 1, **extra: Any) -> ReadRow:
    read = label in ("no_school", "delayed", "unnamed", "unknown")
    body: dict[str, Any] = {
        "district": district,
        "weather": weather,
        "after": False,
        "label": label,
        "why": "partly_lit" if label == "unknown" else ("not_covered" if not read else None),
        "tier": "A" if read else None,
        "market": "Dallas-Fort Worth" if read else None,
        "sources": ("list-b", "list-a") if read else (),
        "slot": "12:30" if read else None,
        "health": 950 if read else None,
        **extra,
    }
    return ReadRow.model_validate(body, strict=False)


def _read(
    day: date = THU,
    rows: Sequence[ReadRow] = (),
    no_school: Sequence[str] = (),
    *,
    unclassed: bool = False,
    content: str = DIGEST,
) -> ReadDay:
    classes = [ReadClass.model_validate({**ZERO, "weather": "none", "median_health": None})]
    if unclassed:
        classes.append(
            ReadClass.model_validate(
                {**ZERO, "weather": "unclassed", "alerted": 1, "not_covered": 1,
                 "median_health": None}
            )
        )  # fmt: skip
    return ReadDay(
        schema_version=1,
        day=day,
        content=content,
        rows=tuple(rows),
        no_school=tuple(no_school),
        audit=ReadAuditDay(day=day, held=False, classes=tuple(classes)),
    )


def _rows(
    read: ReadDay,
    changes: Sequence[Change] = (),
    before: ReadDay | None = None,
    previous: Previous | None = None,
) -> dict[str, RecordRow]:
    found = record.record_rows(
        RecordDay(read.day, read, _timeline(read.day, changes), before, previous), UNITS, RULE
    )
    assert [r.unit for r in found] == sorted(r.unit for r in found)
    return {r.unit: r for r in found}


def test_a_labeled_read_row_is_a_complete_whole_weather_row() -> None:
    read = _read(rows=[_row("9900001", "no_school", weather=5, after=True)])
    snow = int(Reason.WINTER_STORM)
    got = _rows(read, [(0, AT, Status.CLOSED, snow), (1, AT, Status.CLOSED, None),
                       (2, AT, Status.CLOSED, None)])["9900001"]  # fmt: skip
    assert got.call is Call.CLOSED
    assert got.source_kind is SourceKind.LIVE_READ
    assert got.source_complete
    assert not got.closings_only
    assert got.scope is Scope.WHOLE
    assert (got.klass, got.weather, got.situation, got.after_weather, got.after) == (
        "warning",
        5,
        "snow_warning",
        True,
        True,  # a closing for the weather the day before is a closing
    )
    assert got.cause is Cause.WEATHER
    assert got.weather_day
    assert got.agrees
    assert not got.taken_back
    assert not got.fit_usable  # a day after
    assert (got.lit, got.eligible, got.reasons) == (3, 4, (snow,))
    assert (got.tier, got.market, got.sources, got.slot) == (
        "A",
        record.market_code("Dallas-Fort Worth"),
        ("list-a", "list-b"),
        "12:30",
    )
    assert (got.read, got.why, got.tropical) == (None, None, False)


def test_remote_only_when_every_school_lit_no_school_was_remote_and_delayed_and_unnamed() -> None:
    read = _read(rows=[_row("9900001", "no_school"), _row("9900002", "delayed"),
                       _row("9900003", "unnamed")])  # fmt: skip
    got = _rows(read, [(s, AT, Status.REMOTE, None) for s in (0, 1, 2)]
                + [(4, AT, Status.DELAYED, None), (5, AT, Status.DELAYED, None)])  # fmt: skip
    assert got["9900001"].call is Call.REMOTE
    assert got["9900001"].cause is Cause.ANY
    assert got["9900002"].call is Call.DELAYED
    assert got["9900002"].weather_day
    # an outcome-blind read that named nothing is unnamed, never open, and no weather day
    unnamed = got["9900003"]
    assert (unnamed.call, unnamed.weather_day, unnamed.lit) == (Call.UNNAMED, False, 0)
    assert unnamed.source_complete
    assert not unnamed.closings_only
    mixed = _rows(read, [(0, AT, Status.REMOTE, None), (1, AT, Status.CLOSED, None)])
    assert mixed["9900001"].call is Call.CLOSED


def test_a_no_alert_closing_is_a_closings_only_row_and_no_weather_day() -> None:
    got = _rows(_read(), [(7, AT, Status.CLOSED, None), (8, AT, Status.CLOSED, None)], _read(WED))
    row = got["9900004"]
    assert (row.klass, row.weather, row.situation) == ("none", 0, "none")
    assert row.source_kind is SourceKind.LIVE_MAP
    assert row.closings_only
    assert not row.source_complete
    assert (row.call, row.scope, row.lit, row.eligible) == (Call.CLOSED, Scope.WHOLE, 2, 3)
    # no reason named on a day with no alert: not a weather closing (labels.py's rule)
    assert row.cause is Cause.ANY
    assert not row.weather_day
    # the same closing for snow is one
    snow = int(Reason.WINTER_STORM)
    named = _rows(_read(), [(7, AT, Status.CLOSED, snow), (8, AT, Status.CLOSED, snow)])
    assert named["9900004"].weather_day
    assert named["9900004"].cause is Cause.WEATHER


@pytest.mark.parametrize(
    "code", [int(Reason.POWER_OUTAGE), int(Reason.HEAT), 8, 41]
)  # fmt: skip
def test_a_stated_cause_that_is_not_the_weather_never_counts_as_a_weather_day(code: int) -> None:
    # alerted, closed whole, but for a power outage, heat or a code above 7
    read = _read(rows=[_row("9900001", "unknown", weather=5)])
    got = _rows(read, [(s, AT, Status.CLOSED, code) for s in (0, 1, 2)])["9900001"]
    assert (got.call, got.scope, got.cause, got.weather_day) == (
        Call.CLOSED, Scope.WHOLE, Cause.NAMED, False,
    )  # fmt: skip
    assert got.reasons == (code,)
    assert (got.read, got.why) == ("unknown", "partly_lit")
    assert got.closings_only
    assert not got.source_complete
    # one school closed for snow does not make it a weather day either
    mixed = _rows(read, [(0, AT, Status.CLOSED, int(Reason.WINTER_STORM)),
                         (1, AT, Status.CLOSED, code), (2, AT, Status.CLOSED, code)])  # fmt: skip
    assert (mixed["9900001"].cause, mixed["9900001"].weather_day) == (Cause.NAMED, False)
    assert mixed["9900001"].reasons == tuple(sorted({int(Reason.WINTER_STORM), code}))
    # even while the weather alone would make the call, a school lit with it for another
    # cause makes the cause named and the morning no weather day
    most = _rows(read, [(0, AT, Status.CLOSED, None), (1, AT, Status.CLOSED, None),
                        (2, AT, Status.CLOSED, code)])["9900001"]  # fmt: skip
    assert (most.cause, most.weather_day, most.lit, most.reasons) == (
        Cause.NAMED, False, 3, (code,),
    )  # fmt: skip


def test_no_row_names_a_stated_cause_and_is_a_weather_day() -> None:
    codes: list[int | None] = [None, *range(9)]
    read = _read(rows=[_row("9900001", "no_school", weather=1), _row("9900002", "unknown")])
    for first in codes:
        for second in codes:
            changes: list[Change] = [
                (0, AT, Status.CLOSED, first), (1, AT, Status.CLOSED, second),
                (2, AT, Status.CLOSED, first), (4, AT, Status.CLOSED, second),
                (7, AT, Status.DELAYED, first), (8, AT, Status.CLOSED, second),
            ]  # fmt: skip
            for row in _rows(read, changes).values():
                assert not (row.cause is Cause.NAMED and row.weather_day), (first, second, row)


@pytest.mark.parametrize("code", NON_WEATHER)
@pytest.mark.parametrize("label", ["no_school", "delayed"])
def test_a_read_row_lit_for_a_cause_that_is_not_the_weather_is_no_weather_day(
    code: int, label: str
) -> None:
    # alerted and read; at 09:30 only schools naming a non-weather cause are lit with the
    # call (the label, read at the day's last change, saw them later with no reason)
    status = Status.CLOSED if label == "no_school" else Status.DELAYED
    end = RULE.read_until.hour * 60 + RULE.read_until.minute
    changes: list[Change] = [(s, AT, status, code) for s in (0, 1, 2)]
    changes += [(s, end + 30, status, None) for s in (0, 1, 2)]
    read = _read(rows=[_row("9900001", label, weather=5)])
    got = _rows(read, changes)["9900001"]
    assert got.source_kind is SourceKind.LIVE_READ
    assert got.call is (Call.CLOSED if label == "no_school" else Call.DELAYED)
    assert (got.cause, got.weather_day, got.reasons) == (Cause.NAMED, False, (code,))
    assert not got.fit_usable
    # one weather-lit school beside them does not make it a weather day either
    mixed = [*changes[:2], (2, AT, status, None)]
    got = _rows(read, mixed)["9900001"]
    assert (got.cause, got.weather_day) == (Cause.NAMED, False)


def test_a_read_row_the_09_30_map_does_not_give_keeps_its_label_and_is_no_weather_day() -> None:
    end = RULE.read_until.hour * 60 + RULE.read_until.minute
    read = _read(rows=[_row("9900001", "no_school", weather=5)])
    # posted after 09:30: the label (the day's last change) said no school, the morning view
    # held nothing
    late = [(s, end + 15, Status.REMOTE, None) for s in (0, 1, 2)]
    got = _rows(read, late)["9900001"]
    assert (got.call, got.agrees, got.weather_day, got.lit) == (Call.REMOTE, False, False, 3)
    assert (got.cause, got.scope, got.source_complete) == (Cause.ANY, Scope.WHOLE, True)
    assert not got.fit_usable
    # delayed at 09:30, closed later: the label's call is kept, flagged
    upgraded: list[Change] = [(s, AT, Status.DELAYED, None) for s in (0, 1, 2)]
    upgraded += [(s, end + 60, Status.CLOSED, int(Reason.WINTER_STORM)) for s in (0, 1, 2)]
    got = _rows(read, upgraded)["9900001"]
    assert (got.call, got.agrees, got.weather_day) == (Call.CLOSED, False, False)
    assert (got.cause, got.reasons) == (Cause.WEATHER, (int(Reason.WINTER_STORM),))
    # and a delay the morning view shows as a closing: the map's own call is kept beside it
    read = _read(rows=[_row("9900001", "delayed", weather=5)])
    got = _rows(read, [(s, AT, Status.CLOSED, None) for s in (0, 1, 2)])["9900001"]
    assert (got.call, got.agrees, got.weather_day, got.lit) == (Call.DELAYED, False, False, 0)
    assert got.map_call is Call.CLOSED
    # a share at 09:30 is the map's call too, and nothing lit at 09:30 is none
    got = _rows(read, [(0, AT, Status.DELAYED, None)])["9900001"]
    assert (got.call, got.agrees, got.map_call) == (Call.DELAYED, False, Call.DELAYED)
    assert _rows(read, late)["9900001"].map_call is None


@pytest.mark.parametrize("code", NON_WEATHER)
@pytest.mark.parametrize("label", ["no_school", "delayed", "unknown", "unnamed", "not_read", None])
@pytest.mark.parametrize("weather", [1, 5])
def test_a_cause_stated_after_09_30_on_an_unchanged_status_is_no_weather_day(
    code: int, label: str | None, weather: int
) -> None:
    # SYNTHETIC: every school shows its call with no reason (alerted) or a weather reason (no
    # read row: no alert) at 07:00, and the same status names a cause that is not the weather
    # at 10:00
    end = RULE.read_until.hour * 60 + RULE.read_until.minute
    status = Status.DELAYED if label == "delayed" else Status.CLOSED
    first = int(Reason.WINTER_STORM) if label is None or weather == 5 else None
    # without the later cause it is a weather day
    plain = [(s, AT, status, first) for s in (0, 1, 2, 3)]
    read = _read(rows=[] if label is None else [_row("9900001", label, weather=weather)])
    assert _rows(read, plain)["9900001"].weather_day
    changes: list[Change] = [(s, AT, status, first) for s in (0, 1, 2, 3)]
    changes += [(s, end + 30, status, code) for s in (0, 1, 2, 3)]
    got = _rows(read, changes)["9900001"]
    assert (got.weather_day, got.cause) == (False, Cause.NAMED), got
    assert code in got.reasons
    assert got.call is (Call.DELAYED if label == "delayed" else Call.CLOSED)
    assert got.agrees
    assert not got.fit_usable
    # one school of four doing so is enough
    one = [*changes[:4], (0, end + 30, status, code)]
    got = _rows(read, one)["9900001"]
    assert (got.weather_day, got.cause) == (False, Cause.NAMED), got
    assert code in got.reasons
    # and so is a school lit with a call only after 09:30 for that cause
    posted = [*changes[:3], (3, end + 30, status, code)]
    got = _rows(read, posted)["9900001"]
    assert (got.weather_day, got.cause, got.reasons[-1]) == (False, Cause.NAMED, code), got
    # a stated cause before the morning, taken back to no reason by 09:30, still counts
    early: list[Change] = [(s, AT - 60, status, code) for s in (0, 1, 2, 3)]
    early += [(s, AT, status, first) for s in (0, 1, 2, 3)]
    got = _rows(read, early)["9900001"]
    assert (got.weather_day, got.cause) == (False, Cause.NAMED), got


CODES: Final[tuple[int | None, ...]] = (None, *range(8), 8, 9, 41)
LABELS: Final = ("no_school", "delayed", "unnamed", "unknown", "not_read")


def test_every_weather_day_is_lit_for_the_weather_at_09_30_and_names_no_other_cause() -> None:
    end = RULE.read_until.hour * 60 + RULE.read_until.minute
    seen = 0
    for label in LABELS:
        for weather in (1, 5, 7):
            read = _read(rows=[_row("9900001", label, weather=weather)])
            for code in CODES:
                for status in (Status.CLOSED, Status.REMOTE, Status.DELAYED):
                    for minute in (AT, end + 30):
                        changes: list[Change] = [(s, minute, status, code) for s in (0, 1, 2)]
                        changes += [(7, AT, status, code), (8, AT, status, None)]
                        for row in _rows(read, changes).values():
                            seen += 1
                            calls = [c for c in changes if c[1] < end and c[0] in _schools(row)]
                            if row.weather_day:
                                assert row.lit > 0, row
                                assert row.agrees, row
                                assert row.cause is not Cause.NAMED, row
                                assert row.call in record.MORNING_CALLS, row
                                assert row.lit / row.eligible >= min(
                                    RULE.no_school_share, RULE.delayed_share
                                ), row
                            named = {c[3] for c in calls} - {None, 0, 1, 2}
                            tropical = {3, 4, 5}
                            if calls and all(
                                c[3] is not None and c[3] not in (0, 1, 2) and (
                                    c[3] not in tropical or weather != 7
                                )
                                for c in calls
                            ):  # fmt: skip
                                # every school lit at 09:30 names a cause that is not the
                                # weather that morning
                                assert not row.weather_day, row
                            if named - tropical:
                                assert not row.weather_day or row.cause is not Cause.NAMED
    assert seen > 500


def _schools(row: RecordRow) -> set[int]:
    return {int(s) for s in UNITS.eligible[UNITS.districts.index(row.unit)].tolist()}


@pytest.mark.parametrize("code", [8, 9, 41])
def test_a_read_unnamed_district_the_map_lit_is_never_written_unnamed(code: int) -> None:
    # labels read a code above 7 as dark, so the read row is unnamed while the map lit it
    read = _read(rows=[_row("9900001", "unnamed", weather=1)])
    got = _rows(read, [(s, AT, Status.CLOSED, code) for s in (0, 1, 2, 3)])["9900001"]
    assert (got.call, got.source_kind, got.cause, got.weather_day) == (
        Call.CLOSED, SourceKind.LIVE_MAP, Cause.NAMED, False,
    )  # fmt: skip
    assert (got.read, got.closings_only, got.source_complete) == ("unnamed", True, False)
    assert not got.fit_usable
    # a status taken back later: the morning call stands, marked taken back
    end = RULE.read_until.hour * 60 + RULE.read_until.minute
    back: list[Change] = [(s, AT, Status.CLOSED, None) for s in (0, 1, 2)]
    back += [(s, end + 60, None, None) for s in (0, 1, 2)]
    got = _rows(read, back)["9900001"]
    assert (got.call, got.read, got.taken_back) == (Call.CLOSED, "unnamed", True)


def test_a_closing_taken_back_later_is_marked() -> None:
    end = RULE.read_until.hour * 60 + RULE.read_until.minute
    closing = [(7, AT, Status.CLOSED, None), (8, AT, Status.CLOSED, None)]
    assert not _rows(_read(), closing)["9900004"].taken_back
    back = [*closing, (8, end + 120, None, None)]
    assert _rows(_read(), back)["9900004"].taken_back
    # changed to another status is not taken back
    moved = [*closing, (8, end + 120, Status.EARLY_DISMISSAL, None)]
    assert not _rows(_read(), moved)["9900004"].taken_back
    read = _read(rows=[_row("9900001", "no_school", weather=5, after=False)])
    wed = Previous(WED, None)
    whole = [(s, AT, Status.CLOSED, None) for s in (0, 1, 2)]
    kept = _rows(read, whole, _read(WED), wed)["9900001"]
    assert kept.fit_usable
    taken = _rows(read, [*whole, (0, end + 300, None, None)], _read(WED), wed)["9900001"]
    assert (taken.taken_back, taken.fit_usable) == (True, False)


def test_a_part_of_a_district_is_a_share() -> None:
    got = _rows(_read(), [(7, AT, Status.CLOSED, int(Reason.WINTER_STORM))])["9900004"]
    assert (got.scope, got.lit, got.eligible, got.call) == (Scope.SHARE, 1, 3, Call.CLOSED)
    assert not got.weather_day
    delayed = _rows(_read(), [(7, AT, Status.DELAYED, None)])["9900004"]
    assert (delayed.scope, delayed.call) == (Scope.SHARE, Call.DELAYED)
    # an early dismissal is not a morning call
    assert _rows(_read(), [(7, AT, Status.EARLY_DISMISSAL, None)]) == {}


def test_the_morning_call_is_read_at_the_read_window_s_end() -> None:
    end = RULE.read_until.hour * 60 + RULE.read_until.minute
    cleared = [(s, AT, Status.CLOSED, None) for s in (7, 8)] + [
        (s, end + 300, None, None) for s in (7, 8)
    ]
    assert _rows(_read(), cleared)["9900004"].call is Call.CLOSED
    early = [(s, AT, Status.CLOSED, None) for s in (7, 8)] + [
        (s, end - 30, None, None) for s in (7, 8)
    ]
    assert _rows(_read(), early) == {}
    # posted at 09:30 or later: kept from the day's last change, not the morning's call
    late = [(s, end, Status.CLOSED, int(Reason.WINTER_STORM)) for s in (7, 8)]
    row = _rows(_read(), late)["9900004"]
    assert (row.call, row.agrees, row.map_call, row.weather_day, row.lit) == (
        Call.CLOSED, False, None, False, 2,
    )  # fmt: skip
    # the evening before counts (a timeline minute below 0)
    night = [(s, -120, Status.CLOSED, None) for s in (7, 8)]
    assert _rows(_read(), night)["9900004"].call is Call.CLOSED


def test_the_weather_day_after_comes_from_the_read_row_or_the_previous_read_day() -> None:
    closing = [(7, AT, Status.CLOSED, None), (8, AT, Status.CLOSED, None)]
    before = _read(WED, no_school=["9900004"])
    got = _rows(_read(), closing, before)["9900004"]
    assert (got.after_weather, got.situation) == (True, "none_after")
    assert _rows(_read(), closing, _read(WED))["9900004"].after_weather is False
    # not known: neither is its situation, since the class has an after situation
    unknown = _rows(_read(), closing)["9900004"]
    assert (unknown.after_weather, unknown.situation, unknown.klass) == (None, None, "none")
    # a read day that is not the previous school day is not read for it
    monday = date(2026, 11, 30)
    old = _rows(_read(), closing, _read(monday, no_school=["9900004"]))["9900004"]
    assert old.after_weather is None
    # a warning has no after situation, but the flag is kept, and an unknown one does not hide
    # the situation
    read = _read(rows=[_row("9900001", "no_school", weather=5, after=True)])
    row = _rows(read, [(s, AT, Status.CLOSED, None) for s in (0, 1)])["9900001"]
    assert (row.after_weather, row.situation) == (True, "snow_warning")
    read = _read(rows=[_row("9900001", "no_school", weather=5, after=None)])
    row = _rows(read, [(s, AT, Status.CLOSED, None) for s in (0, 1)])["9900001"]
    assert (row.after_weather, row.situation) == (None, "snow_warning")
    read = _read(rows=[_row("9900001", "no_school", weather=1, after=None)])
    row = _rows(read, [(s, AT, Status.CLOSED, None) for s in (0, 1)])["9900001"]
    assert (row.after_weather, row.situation, row.klass) == (None, None, "advisory")


def test_the_day_after_flag_is_true_to_the_map_for_any_closing() -> None:
    # SYNTHETIC: 9900004 closed 2 of 3 on Wednesday and again on Thursday, no alert and no
    # reason named either day (labels' weather flag stays false: not a weather closing)
    closing = [(7, AT, Status.CLOSED, None), (8, AT, Status.CLOSED, None)]
    wed = Previous(WED, _timeline(WED, closing))
    got = _rows(_read(), closing, _read(WED), wed)["9900004"]
    assert (got.after, got.after_weather, got.situation) == (True, False, "none")
    assert not got.fit_usable
    # Wednesday's own record row says the same district closed whole
    wed_row = _rows(_read(WED), closing)["9900004"]
    assert (wed_row.call, wed_row.scope) == (Call.CLOSED, Scope.WHOLE)
    # remote counts, and so does a closing for a stated cause that is not the weather
    for status, code in ((Status.REMOTE, None), (Status.CLOSED, int(Reason.POWER_OUTAGE))):
        prior = Previous(WED, _timeline(WED, [(7, AT, status, code), (8, AT, status, code)]))
        assert _rows(_read(), closing, None, prior)["9900004"].after is True
    # a delay, a share under the no-school share, or a map that lit nothing is no day after
    end = RULE.read_until.hour * 60 + RULE.read_until.minute
    for changes in (
        [(7, AT, Status.DELAYED, None), (8, AT, Status.DELAYED, None)],
        [(7, AT, Status.CLOSED, None)],
        [(7, AT, Status.CLOSED, None), (8, end + 30, Status.DELAYED, None)],
    ):
        prior = Previous(WED, _timeline(WED, changes))
        assert _rows(_read(), closing, None, prior)["9900004"].after is False, changes
    assert _rows(_read(), closing, None, Previous(WED, None))["9900004"].after is False
    # not known: no previous map, another day's map, or another directory's timeline
    assert _rows(_read(), closing)["9900004"].after is None
    monday = date(2026, 11, 30)
    assert _rows(_read(), closing, None, Previous(monday, None))["9900004"].after is None
    other = Previous(WED, _timeline(WED, closing, content_sha256="c" * 64))
    assert _rows(_read(), closing, None, other)["9900004"].after is None
    # a read row carries it too
    read = _read(rows=[_row("9900001", "no_school", weather=1)])
    prior = Previous(WED, _timeline(WED, [(s, AT, Status.CLOSED, None) for s in (0, 1)]))
    row = _rows(read, [(s, AT, Status.CLOSED, None) for s in (0, 1)], None, prior)["9900001"]
    assert (row.after, row.after_weather, row.situation) == (True, False, "advisory")


@pytest.mark.parametrize("read_wed", [True, False])
def test_a_previous_day_closing_posted_after_09_30_is_a_day_after(read_wed: bool) -> None:
    # SYNTHETIC: on Wednesday 9900002 closed for snow at 10:00 local (after 09:30), whole
    end = RULE.read_until.hour * 60 + RULE.read_until.minute
    snow = int(Reason.WINTER_STORM)
    late = [(s, end + 30, Status.CLOSED, snow) for s in (4, 5)]
    wed_read = _read(
        WED, rows=[_row("9900002", "no_school", weather=5)] if read_wed else [],
        no_school=["9900002"],
    )  # fmt: skip
    # Wednesday's own row says it closed, whole (a read row, or a map row posted late)
    wed_row = _rows(wed_read, late)["9900002"]
    assert (wed_row.call, wed_row.scope, wed_row.agrees, wed_row.weather_day) == (
        Call.CLOSED, Scope.WHOLE, False, False,
    )  # fmt: skip
    # so Thursday's row is a day after, by the map and by labels' flag
    closing = [(s, AT, Status.CLOSED, snow) for s in (4, 5)]
    thu = _rows(_read(), closing, wed_read, Previous(WED, _timeline(WED, late)))["9900002"]
    assert (thu.after, thu.after_weather, thu.situation) == (True, True, "none_after")
    assert not thu.fit_usable
    # the map alone says it (no read day before), and so does Wednesday's read row alone
    # (Wednesday's map not known)
    assert _rows(_read(), closing, None, Previous(WED, _timeline(WED, late)))["9900002"].after
    if read_wed:
        bare = _read(WED, rows=[_row("9900002", "no_school", weather=5)])
        assert _rows(_read(), closing, bare)["9900002"].after is True
    # labels' weather flag alone makes it a day after too
    flagged = _read(rows=[_row("9900001", "no_school", weather=5, after=True)])
    got = _rows(flagged, [(s, AT, Status.CLOSED, None) for s in (0, 1, 2)],
                None, Previous(WED, None))["9900001"]  # fmt: skip
    assert (got.after, got.after_weather) == (True, True)


def test_a_row_says_no_weather_day_after_that_is_no_day_after() -> None:
    read = _read(rows=[_row("9900001", "no_school", weather=5, after=False)])
    whole = [(s, AT, Status.CLOSED, None) for s in (0, 1, 2)]
    body = _rows(read, whole, _read(WED), Previous(WED, None))["9900001"].model_dump(mode="json")
    for after in (False, None):
        flags = {"after": after, "after_weather": True, "situation": "snow_warning"}
        with pytest.raises(ValueError, match="a day after a weather closing it cannot be"):
            RecordRow.model_validate_json(json.dumps({**body, **flags, "fit_usable": False}))
    for change in ({"map_call": None}, {"map_call": "delayed"}, {"map_call": "remote"}):
        with pytest.raises(ValueError, match="does not make"):
            RecordRow.model_validate_json(json.dumps({**body, **change}), strict=False)


@pytest.mark.parametrize("label", [None, "unnamed", "unknown", "not_read"])
def test_a_closing_posted_only_after_09_30_is_kept_and_never_a_weather_day(
    label: str | None,
) -> None:
    end = RULE.read_until.hour * 60 + RULE.read_until.minute
    snow = int(Reason.WINTER_STORM)
    read = _read(rows=[] if label is None else [_row("9900001", label, weather=5)])
    late = [(s, end + 30, Status.CLOSED, snow) for s in (0, 1, 2, 3)]
    got = _rows(read, late, _read(WED), Previous(WED, None))["9900001"]
    assert (got.call, got.scope, got.lit, got.reasons) == (Call.CLOSED, Scope.WHOLE, 4, (snow,))
    assert (got.source_kind, got.source_complete, got.closings_only) == (
        SourceKind.LIVE_MAP, False, True,
    )  # fmt: skip
    assert (got.agrees, got.map_call, got.weather_day, got.fit_usable) == (
        False, None, False, False,
    )  # fmt: skip
    assert got.read == label
    # a share posted late, and a late stated cause
    got = _rows(read, [(0, end + 30, Status.DELAYED, 7)])["9900001"]
    assert (got.call, got.scope, got.cause, got.reasons) == (
        Call.DELAYED, Scope.SHARE, Cause.NAMED, (7,),
    )  # fmt: skip
    # taken back before the day was over: nothing was shown at 09:30 or at its end, so only
    # a read unnamed row is kept, marked taken back (never fit-usable)
    back = _rows(read, [*late, *((s, end + 90, None, None) for s in (0, 1, 2, 3))])
    if label != "unnamed":
        assert back == {}
    else:
        assert _rows(read)["9900001"].fit_usable is False  # not a day before known
        got = back["9900001"]
        assert (got.call, got.taken_back, got.fit_usable, got.reasons) == (
            Call.UNNAMED, True, False, (snow,),
        )  # fmt: skip
        kept = _rows(read, [], _read(WED), Previous(WED, None))["9900001"]
        assert (kept.call, kept.taken_back, kept.fit_usable) == (Call.UNNAMED, False, True)


def test_a_district_with_no_class_when_the_read_day_holds_unclassed_ones_is_unknown() -> None:
    got = _rows(_read(unclassed=True), [(7, AT, Status.CLOSED, None), (8, AT, Status.CLOSED, None)])
    row = got["9900004"]
    assert (row.klass, row.weather, row.situation) == ("unknown", None, None)
    assert not row.weather_day
    snow = int(Reason.WINTER_STORM)
    named = _rows(
        _read(unclassed=True), [(7, AT, Status.CLOSED, snow), (8, AT, Status.CLOSED, snow)]
    )
    assert named["9900004"].weather_day  # a named weather reason needs no class


@pytest.mark.parametrize(
    ("weather", "key", "tropical"),
    [
        (WeatherClass.ADVISORY, "advisory", False),
        (WeatherClass.COLD, "cold", False),
        (WeatherClass.LAKE_SNOW, "warning", False),
        (WeatherClass.SNOW_WARNING, "warning", False),
        (WeatherClass.ICE, "warning", False),
        (WeatherClass.BLIZZARD, "warning", False),
        (WeatherClass.TROPICAL, "warning", True),
    ],
)
def test_each_class_is_named_as_the_serving_classes_name_it(
    weather: WeatherClass, key: str, tropical: bool
) -> None:
    read = _read(rows=[_row("9900001", "no_school", weather=int(weather))])
    row = _rows(read, [(s, AT, Status.CLOSED, None) for s in (0, 1)])["9900001"]
    assert (row.klass, row.weather, row.tropical) == (key, int(weather), tropical)
    flood = _rows(_read(), [(7, AT, Status.CLOSED, int(Reason.FLOODING))] * 1
                  + [(8, AT, Status.CLOSED, int(Reason.FLOODING))])["9900004"]  # fmt: skip
    # a tropical reason on a day that is not tropical: kept, flagged, never a weather day
    assert (flood.tropical, flood.weather_day, flood.cause) == (True, False, Cause.WEATHER)
    # and so when it is named only after 09:30 on the same status
    if weather is not WeatherClass.TROPICAL:
        end = RULE.read_until.hour * 60 + RULE.read_until.minute
        later: list[Change] = [(s, AT, Status.CLOSED, None) for s in (0, 1)]
        later += [(s, end + 30, Status.CLOSED, int(Reason.FLOODING)) for s in (0, 1)]
        row = _rows(read, later)["9900001"]
        assert (row.tropical, row.weather_day, row.cause, row.reasons) == (
            True, False, Cause.WEATHER, (int(Reason.FLOODING),),
        )  # fmt: skip


def test_unread_and_not_alerted_districts_with_nothing_lit_have_no_row() -> None:
    read = _read(rows=[_row("9900001", "not_read"), _row("9900002", "unknown")])
    assert _rows(read) == {}
    got = _rows(read, [(4, AT, Status.CLOSED, None), (5, AT, Status.CLOSED, None)])
    assert list(got) == ["9900002"]
    assert (got["9900002"].read, got["9900002"].klass) == ("unknown", "advisory")
    assert got["9900002"].weather_day  # alerted, no reason named: labels.py's rule


def test_another_directory_s_day_is_refused_never_guessed() -> None:
    with pytest.raises(RecordError, match="another directory"):
        record.record_rows(RecordDay(THU, _read(content="b" * 64), _timeline()), UNITS, RULE)
    other = _timeline(content_sha256="c" * 64)
    with pytest.raises(RecordError, match="not this directory's"):
        record.record_rows(RecordDay(THU, _read(), other), UNITS, RULE)
    with pytest.raises(RecordError, match="names"):
        record.record_rows(RecordDay(WED, _read(), None), UNITS, RULE)
    # the same content under another stamp is the same indexes
    restamped = world.STAMP.model_copy(update={"generated_on": date(2026, 10, 24)})
    assert (
        record.record_rows(RecordDay(THU, _read(), _timeline(directory=restamped)), UNITS, RULE)
        == []
    )
    # with no digest on either side, the stamp decides
    bare = Units(UNITS.districts, UNITS.eligible, UNITS.content, world.STAMP, None)
    assert bare.indexes(_timeline(directory=world.STAMP))
    assert not bare.indexes(_timeline(directory=restamped))


def test_eligible_schools_follow_the_serving_rule() -> None:
    # district 0: a public school, a charter and a private one; district 1: a charter only;
    # a private school with no district
    points = Points(
        lon_e6=np.zeros(5, dtype=np.int32),
        lat_e6=np.zeros(5, dtype=np.int32),
        district=np.array([0, 0, 0, 1, record.NO_DISTRICT], dtype=np.uint32),
        kind=np.array([0, CHARTER, PRIVATE, CHARTER, PRIVATE], dtype=np.uint8),
        district_count=2,
    )
    found = record.eligible_schools(points, 2)
    assert [f.tolist() for f in found] == [[0], [3]]


def test_a_day_s_bytes_are_codes_only_and_read_back() -> None:
    read = _read(rows=[_row("9900001", "no_school")])
    rows = list(_rows(read, [(s, AT, Status.CLOSED, None) for s in (0, 1, 7, 8)]).values())
    data = record.day_bytes(rows)
    assert data == record.day_bytes(list(reversed(rows)))
    assert record.rows_of(data) == rows
    assert b"://" not in data
    assert b"www." not in data
    assert record.day_bytes([]) == b""
    for bad in ("https://x.invalid/", "a list name", "x" * 65):
        with pytest.raises(RecordError, match="not a code"):
            record.day_bytes([rows[0].model_copy(update={"market": bad})])
    with pytest.raises(RecordError, match="more than one day"):
        record.day_bytes([rows[0], rows[0].model_copy(update={"day": WED})])
    # the record job keeps them (the record kind's writer)
    api = FakeD1()
    offer = Offer(evidence.RECORD, THU.isoformat(), data)
    assert [r.kept for r in _store(api, RECORD_JOB).push([offer], (evidence.RECORD,))] == [1, 1]
    assert _store(api, RECORD_JOB).pull(evidence.RECORD) == {THU.isoformat(): data}
    # a morning with no row is kept too, and is held from then on
    _store(api, RECORD_JOB).push([Offer(evidence.RECORD, WED.isoformat(), b"")], (evidence.RECORD,))
    assert record.held_days(_store(api, RECORD_JOB)) == {THU.isoformat(), WED.isoformat()}


def test_the_table_holds_every_row_with_every_field(tmp_path: Path) -> None:
    read = _read(rows=[_row("9900001", "no_school"), _row("9900003", "unnamed")])
    rows = list(_rows(read, [(s, AT, Status.CLOSED, 7) for s in (0, 1, 7, 8)]).values())
    path = tmp_path / "record.parquet"
    assert record.write_table(rows, path) == len(rows) == 3
    frame = pl.read_parquet(path)
    assert tuple(frame.columns) == record.COLUMNS == (*RecordRow.model_fields, "code")
    assert frame["code"].to_list() == [None, None, None]
    assert frame["unit"].to_list() == ["9900001", "9900003", "9900004"]
    assert frame.filter(pl.col("unit") == "9900004")["reasons"].to_list() == [[7]]
    assert record.write_table([], path) == 0


def test_counts_line_says_counts_only() -> None:
    read = _read(rows=[_row("9900001", "no_school"), _row("9900003", "unnamed")])
    changes: list[Change] = [(s, AT, Status.CLOSED, None) for s in (0, 1)]
    changes += [(7, AT, Status.CLOSED, 7), (8, AT, Status.CLOSED, 7)]
    rows = list(_rows(read, changes).values())
    assert record.counts_line(THU, rows) == (
        "predict each-school record: 2026-12-03: 3 rows (closed 2, unnamed 1); 2 from the read"
        " labels, 1 from the map alone; 1 weather days, 1 for a stated cause that is not the"
        " weather; 0 the day after a closing; 0 read calls the 09:30 map does not give;"
        " 0 fit-usable"
    )


def _generated_rows(seed: int) -> list[RecordRow]:
    """SYNTHETIC: one random day's rows (labels, classes, statuses, codes and minutes)."""
    return _generated(seed)[0]


def _generated(seed: int) -> tuple[list[RecordRow], list[Change]]:
    """SYNTHETIC: one random day's rows and the day's changes."""
    rng = random.Random(seed)  # noqa: S311 - SYNTHETIC rows, not a secret
    end = RULE.read_until.hour * 60 + RULE.read_until.minute
    rows = [
        _row(
            d,
            rng.choice(LABELS),
            weather=rng.choice((1, 2, 5, 7)),
            after=rng.choice((None, False, True)),
        )
        for d in UNITS.districts
        if rng.random() < 0.6
    ]
    changes: list[Change] = []
    for school in range(10):
        if rng.random() < 0.7:
            status = rng.choice(
                (Status.CLOSED, Status.REMOTE, Status.DELAYED, Status.EARLY_DISMISSAL)
            )
            code = rng.choice(CODES)
            changes.append((school, rng.choice((AT, end + 30)), status, code))
            later = rng.choice((None, Status.CLOSED))
            if rng.random() < 0.3 and (later, None) != (status, code):
                changes.append((school, end + 200, later, None))
            elif rng.random() < 0.3 and (again := rng.choice(CODES)) != code:
                # the same status names another cause later (a stated cause, or a weather one)
                changes.append((school, end + 100, status, again))
    before = _read(WED, no_school=[d for d in UNITS.districts if rng.random() < 0.3])
    prior = [(s, AT, Status.CLOSED, None) for s in range(10) if rng.random() < 0.5]
    previous = rng.choice((None, Previous(WED, None), Previous(WED, _timeline(WED, prior))))
    return list(_rows(_read(rows=rows), changes, before, previous).values()), changes


@pytest.mark.parametrize("seed", range(60))
def test_no_weather_day_names_a_cause_that_is_not_the_weather_at_any_change(seed: int) -> None:
    rows, changes = _generated(seed)
    for row in rows:
        mine = _schools(row)
        called = {c[0] for c in changes if c[0] in mine and c[2] in record.CALLED}
        codes = {c[3] for c in changes if c[0] in called and c[2] in record.CALLED} - {None}
        stated = codes - {int(r) for r in Reason if r in WEATHER_REASONS}
        if row.weather_day:
            assert not stated, (row, changes)
        if stated:
            assert row.cause is Cause.NAMED, (row, changes)
        if row.call is not Call.UNNAMED:
            assert set(row.reasons) <= codes, (row, changes)
        assert row.after_weather is not True or row.after is True


@pytest.mark.parametrize("seed", range(60))
def test_fit_usable_is_never_set_on_a_row_a_fit_may_not_use(seed: int) -> None:
    for row in _generated_rows(seed):
        if not row.source_complete or row.scope is not Scope.WHOLE or row.closings_only:
            assert not row.fit_usable, row
        if row.cause is Cause.NAMED or row.tropical or not row.agrees or row.taken_back:
            assert not row.fit_usable, row
        if row.after is not False or row.after_weather is True:
            assert not row.fit_usable, row
        if row.fit_usable:
            assert row.weather_day or row.call is Call.UNNAMED
            assert row.source_kind is SourceKind.LIVE_READ
        if row.weather_day:
            assert row.cause is not Cause.NAMED
            assert row.lit > 0
            assert row.agrees


def test_a_row_that_says_a_weather_day_it_cannot_be_or_a_wrong_fit_flag_is_refused() -> None:
    read = _read(rows=[_row("9900001", "no_school", weather=5, after=False)])
    whole = [(s, AT, Status.CLOSED, None) for s in (0, 1, 2)]
    good = _rows(read, whole, _read(WED), Previous(WED, None))["9900001"]
    assert good.fit_usable
    body = good.model_dump(mode="json")
    for change in (
        {"cause": "named", "fit_usable": False},
        {"lit": 0},
        {"agrees": False, "fit_usable": False},
        {"call": "unnamed", "weather_day": True},
        {"fit_usable": False},
        {"after": None},
        {"closings_only": True, "source_complete": False},
        {"scope": "share"},
        {"scope": "unknown"},
        {"cause": "named", "call": "unnamed", "weather_day": False, "map_call": None},
    ):
        with pytest.raises(ValueError, match=r"cannot be|fit_usable"):
            RecordRow.model_validate_json(json.dumps({**body, **change}), strict=False)


def test_the_fit_rule_takes_each_of_its_clauses() -> None:
    usable: dict[str, Any] = {
        "source_complete": True, "scope": "whole", "agrees": True, "cause": "any",
        "tropical": False, "after": False, "after_weather": False, "taken_back": False,
        "call": "closed", "weather_day": True,
    }  # fmt: skip
    assert set(usable) == set(record.FIT_FIELDS)
    assert record.fit_rule(usable)
    assert record.fit_rule({**usable, "after_weather": None})
    assert record.fit_rule({**usable, "call": "unnamed", "weather_day": False})
    for change in (
        {"source_complete": False},
        {"scope": "share"},
        {"scope": "unknown"},
        {"agrees": False},
        {"cause": "named"},
        {"cause": "named", "call": "unnamed", "weather_day": False},
        {"tropical": True},
        {"after": True},
        {"after": None},
        {"after_weather": True},
        {"taken_back": True},
        {"weather_day": False},
    ):
        assert not record.fit_rule({**usable, **change}), change


def test_a_market_is_kept_as_a_code_never_its_name() -> None:
    from snowlight.sources.stations.registry import load_registry  # noqa: PLC0415

    stations = list(load_registry().stations.values())
    markets = sorted({s.market for s in stations})
    assert len(markets) > 100
    for start in range(0, len(markets), len(UNITS.districts)):
        rows = [
            _row(d, "no_school", weather=5, market=m, sources=(stations[n % len(stations)].id,))
            for n, (d, m) in enumerate(zip(UNITS.districts, markets[start:], strict=False))
        ]
        read = _read(rows=rows)
        data = record.day_bytes(
            list(_rows(read, [(s, AT, Status.CLOSED, None) for s in range(10)]).values())
        )
        for row in rows:
            assert row.market is not None
            assert row.market.encode() not in data
            assert f'"market":"{record.market_code(row.market)}"'.encode() in data
    # every registry source id is a code the record may hold
    record.day_bytes([])
    for station in stations:
        record._checked(station.id, "registry")
    assert record.market_code(None) is None
    assert record.market_code("New York") != record.market_code("New York ")


def test_take_back_days_and_rows_are_left_out_of_the_table(tmp_path: Path) -> None:
    learn = PredictConfig.load(PIPELINE_ROOT / "config" / "predict.yaml").learn
    closing = [(s, AT, Status.CLOSED, None) for s in (0, 1, 7, 8)]
    kept = {
        day.isoformat(): record.day_bytes(list(_rows(_read(day), closing).values()))
        for day in (WED, THU)
    }
    assert len(record.kept_rows(kept, learn)) == 4
    no_wed = learn.model_copy(update={"excluded_days": (WED,)})
    assert {(r.day, r.unit) for r in record.kept_rows(kept, no_wed)} == {
        (THU, "9900001"), (THU, "9900004"),
    }  # fmt: skip
    one = learn.model_copy(update={"excluded_rows": ((THU, "9900004"),)})
    assert (THU, "9900004") not in {(r.day, r.unit) for r in record.kept_rows(kept, one)}
    assert len(record.kept_rows(kept, one)) == 3
    assert record.write_table(record.kept_rows(kept, one), tmp_path / "r.parquet") == 3


COUNTS = re.compile(
    r"^predict each-school record: (?P<day>\S+): (?P<n>\d+) rows \((?P<said>[^)]*)\); (?P<read>\d+)"
    r" from the read labels, (?P<map>\d+) from the map alone; (?P<weather>\d+) weather days,"
    r" (?P<named>\d+) for a stated cause that is not the weather; (?P<after>\d+) the day after a"
    r" closing; (?P<differ>\d+) read calls the 09:30 map does not give; (?P<usable>\d+) fit-usable$"
)


@pytest.mark.parametrize("seed", range(40))
def test_the_counts_said_equal_the_record_s_rows(seed: int, tmp_path: Path) -> None:
    rows = _generated_rows(seed)
    line = record.counts_line(THU, rows)
    found = COUNTS.match(line)
    assert found is not None, line
    assert int(found["n"]) == len(rows)
    said = {} if found["said"] == "none" else {
        call: int(n) for call, n in (part.rsplit(" ", 1) for part in found["said"].split(", "))
    }  # fmt: skip
    assert said == {c.value: n for c in Call if (n := sum(r.call is c for r in rows))}
    assert int(found["read"]) == sum(r.source_kind is SourceKind.LIVE_READ for r in rows)
    assert int(found["map"]) == sum(r.source_kind is SourceKind.LIVE_MAP for r in rows)
    assert int(found["weather"]) == sum(r.weather_day for r in rows)
    assert int(found["named"]) == sum(r.cause is Cause.NAMED for r in rows)
    assert int(found["after"]) == sum(r.after is True for r in rows)
    assert int(found["differ"]) == sum(not r.agrees for r in rows)
    assert int(found["usable"]) == sum(r.fit_usable for r in rows)
    # the table holds every kept day's rows, each read back from its bytes
    other = _generated_rows(seed + 1000)
    kept = {
        THU.isoformat(): record.day_bytes(rows),
        WED.isoformat(): record.day_bytes([r.model_copy(update={"day": WED}) for r in other]),
    }
    learn = PredictConfig.load(PIPELINE_ROOT / "config" / "predict.yaml").learn
    path = tmp_path / "record.parquet"
    assert record.write_table(record.kept_rows(kept, learn), path) == len(rows) + len(other)
    frame = pl.read_parquet(path)
    assert frame.height == len(rows) + len(other)
    assert frame.filter(pl.col("day") == THU)["unit"].to_list() == sorted(r.unit for r in rows)


def _write_read(folder: Path, read: ReadDay) -> None:
    path = folder / "rows" / f"{read.day.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(read.to_bytes())


class FakeHost:
    """SYNTHETIC live host: timelines by day (a day missing answers 404, an exception in
    ``broken`` raises) and an index listing the days given."""

    def __init__(
        self,
        timelines: dict[date, DayTimeline],
        listed: Sequence[date] | None = None,
        *,
        broken: Sequence[date] = (),
        index_broken: bool = False,
    ) -> None:
        self.timelines = timelines
        self.listed = sorted(timelines) if listed is None else list(listed)
        self.broken = set(broken)
        self.index_broken = index_broken

    def timeline(self, day: date) -> DayTimeline | None:
        if day in self.broken:
            raise RecordError(f"{day}: the timeline answered HTTP 503")
        return self.timelines.get(day)

    def index(self) -> DayIndex | None:
        if self.index_broken:
            raise RecordError("live/days/index.json answered HTTP 503")
        return DayIndex.model_validate(
            {
                "schema_version": 1,
                "generated_at": NOW + timedelta(days=30),
                "days": [
                    {"day": day, "schools": 1, "final": True}
                    for day in sorted(set(self.listed), reverse=True)
                ],
            },
            strict=False,
        )


def test_a_run_writes_new_final_days_and_leaves_the_rest(tmp_path: Path) -> None:
    # Tue-Fri and the next Monday
    days = [date(2026, 12, 1) + timedelta(days=n) for n in (0, 1, 2, 3, 6)]
    for day in days:
        _write_read(tmp_path, _read(day, rows=[_row("9900001", "no_school")]))
    monday = date(2026, 11, 30)  # the previous school day of Tuesday (no read day)
    closing = [(0, AT, Status.CLOSED, None)]
    timelines = {
        monday: _timeline(monday, closing),
        days[0]: _timeline(days[0], closing),
        days[1]: _timeline(days[1], closing, content_sha256="d" * 64),
        days[2]: _timeline(days[2], closing, final=False),
        days[4]: _timeline(days[4], closing),
    }
    said: list[str] = []
    host = FakeHost(timelines, broken=[days[3]])
    run = RecordRun(tmp_path, UNITS, RULE, host, frozenset(), said.append)
    found = run.new_days()
    assert [day for day, _ in found] == [days[0]]
    [tuesday] = record.rows_of(found[0][1])
    assert tuesday.call is Call.CLOSED
    assert tuesday.after is False  # Monday lit 1 of 4: under the share
    # another directory's day is said and left, never guessed
    assert any(
        "2026-12-02: the timeline is not this directory's day: left for a later run" in line
        for line in said
    )
    assert any("2026-12-03: its timeline is not final yet" in line for line in said)
    assert any(
        "2026-12-04: the timeline answered HTTP 503: left for a later run" in line for line in said
    )
    # Monday waits too (its previous school day answered an error)
    assert any("2026-12-07: 2026-12-04" in line and "left for a later run" in line for line in said)
    assert any("counts" not in line and "rows (closed 1)" in line for line in said)
    # a held day is never written again; only the newest days are looked at, and the rest said
    held = RecordRun(tmp_path, UNITS, RULE, host, frozenset({days[0].isoformat()}), said.append)
    assert held.new_days() == []
    said.clear()
    newest = RecordRun(tmp_path, UNITS, RULE, host, frozenset(), said.append, days=2)
    assert newest.new_days() == []
    assert any("3 older labeled days not held wait for a later run" in line for line in said)


def test_a_day_the_host_holds_no_timeline_of_is_quiet_only_when_its_index_says_so(
    tmp_path: Path,
) -> None:
    thu = THU
    _write_read(tmp_path, _read(thu, rows=[_row("9900001", "no_school")]))
    wed = _timeline(WED, [(s, AT, Status.CLOSED, None) for s in (0, 1)])
    said: list[str] = []

    def one(host: FakeHost) -> list[tuple[date, bytes]]:
        return RecordRun(tmp_path, UNITS, RULE, host, frozenset(), said.append).new_days()

    # not listed while the index was written after the day: the map lit nothing that day
    [(day, data)] = one(FakeHost({WED: wed}))
    [row] = record.rows_of(data)
    assert (day, row.call, row.lit, row.agrees, row.after) == (thu, Call.CLOSED, 0, False, True)
    assert not row.weather_day
    # listed but answering 404 (a transient answer, or a file not there yet): it waits
    assert one(FakeHost({WED: wed}, listed=[WED, thu])) == []
    assert any("lists its timeline but holds none" in line for line in said)
    # no index that reads: it waits, and the index's failure is said
    said.clear()
    assert one(FakeHost({WED: wed}, index_broken=True)) == []
    assert any("the day index: live/days/index.json answered HTTP 503" in line for line in said)
    assert any("not final yet: left for a later run" in line for line in said)
    # the previous school day answering an error: the day waits
    assert one(FakeHost({WED: wed}, broken=[WED])) == []
    # the previous school day older than every day the index lists, and no timeline: after is
    # not known; within the index's days and not listed: the map lit nothing that day
    [(_, data)] = one(FakeHost({thu: _timeline(thu, [(0, AT, Status.CLOSED, None)])}))
    assert record.rows_of(data)[0].after is None
    later = FakeHost(
        {thu: _timeline(thu, [(0, AT, Status.CLOSED, None)])}, listed=[WED - timedelta(days=1), thu]
    )
    [(_, data)] = one(later)
    assert record.rows_of(data)[0].after is False


def test_a_day_that_does_not_read_waits_and_the_others_go_on(tmp_path: Path) -> None:
    for day in (WED, THU):
        _write_read(tmp_path, _read(day, rows=[_row("9900001", "no_school")]))
    (tmp_path / "rows" / f"{WED.isoformat()}.json").write_text("{not json", encoding="utf-8")
    said: list[str] = []
    host = FakeHost({THU: _timeline(THU, [(0, AT, Status.CLOSED, None)])})
    found = RecordRun(tmp_path, UNITS, RULE, host, frozenset(), said.append).new_days()
    assert [day for day, _ in found] == [THU]
    assert record.rows_of(found[0][1])[0].after_weather is False  # its read row's own flag
    assert any(f"{WED}: ValidationError: left for a later run" in line for line in said)
    assert any(f"previous read day {WED} does not read" in line for line in said)
    # only the error's kind is said: never the private file's bytes
    assert not any("not json" in line for line in said)


def test_a_day_left_for_long_is_warned_of(tmp_path: Path) -> None:
    old = THU - timedelta(days=record.STUCK_DAYS + 1)
    for day in (old, THU):
        _write_read(tmp_path, _read(day, rows=[_row("9900001", "no_school")]))
    said: list[str] = []
    host = FakeHost({THU: _timeline(THU, [(0, AT, Status.CLOSED, None)])}, broken=[old])
    RecordRun(tmp_path, UNITS, RULE, host, frozenset(), said.append).new_days()
    assert any(
        line.startswith("::warning::") and f"{old} is still not written 8 days on" in line
        for line in said
    )


WORKFLOW = PIPELINE_ROOT.parent / ".github" / "workflows" / "each-school-record.yml"


def test_the_record_job_is_its_own_daily_workflow_and_only_reads_the_predict_caches() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # GITHUB_WORKFLOW is the workflow's name: the one writer of the record kind
    assert workflow["name"] == "each-school record"
    assert evidence.WRITERS[workflow["name"]] == {evidence.RECORD}
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"schedule"}
    assert len(triggers["schedule"]) == 1
    group = workflow["concurrency"]["group"]
    assert group == "each-school-record"
    assert "predict" not in group.split("-")
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["permissions"] == {
        "contents": "read", "actions": "read", "deployments": "read",
    }  # fmt: skip
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    uses = [str(step.get("uses", "")) for step in steps]
    assert not any("cache/save" in u or u.startswith("actions/cache@") for u in uses)
    assert not any("upload-artifact" in u for u in uses)
    # setup-uv saves a cache of its own when asked: never (the repository's cache room is
    # shared with the predict chain's caches)
    for step in steps:
        if "setup-uv" in str(step.get("uses", "")):
            assert step["with"]["enable-cache"] is False, step
    restores = [step for step in steps if "cache/restore" in str(step.get("uses", ""))]
    assert restores
    for step in restores:
        keys = [step["with"]["key"], *str(step["with"].get("restore-keys", "")).split()]
        assert all(k.startswith(("predict-reads-", "predict-frozen-")) for k in keys), keys
    runs = [str(step.get("run", "")) for step in steps]
    assert any("snowlight predict each-school record" in r for r in runs)
    # the past records (P2d) need no read record: they run whether the cache matched or not,
    # after the live step whatever it did, with setup-uv and the sync unconditional
    (past,) = [s for s in steps if "snowlight predict each-school past" in str(s.get("run", ""))]
    assert past["if"] == "${{ !cancelled() }}"
    assert steps.index(past) == len(steps) - 1
    for step in steps:
        if "setup-uv" in str(step.get("uses", "")) or "uv sync" in str(step.get("run", "")):
            assert "if" not in step, step
    assert not any("predict run" in r or "predict learn" in r or "publish" in r for r in runs)


def test_no_pass_and_no_learning_step_reads_the_record() -> None:
    root = PIPELINE_ROOT / "snowlight" / "predict"
    for name in (
        "serve.py",
        "learn.py",
        "live_labels.py",
        "anchor.py",
        "anchor_labels.py",
        "forecast_adjust.py",
        "live_read.py",
        "frozen.py",
        "publish.py",
        "drill.py",
    ):
        text = (root / name).read_text(encoding="utf-8")
        assert "predict.record" not in text, name
        assert "import record" not in text, name
        assert "state_records" not in text, name


# --- past records (each-school P2d) -------------------------------------------------------------


def _past(day: date, unit: str = "9900001", **change: Any) -> record.PastDay:
    body: dict[str, Any] = {
        "version": 1, "day": day, "unit": unit, "weather": None, "klass": "unknown",
        "after": None, "after_weather": None, "situation": None, "call": Call.CLOSED,
        "source_kind": SourceKind.PAST_RECORDS, "source_complete": False, "closings_only": True,
        "scope": Scope.WHOLE, "cause": Cause.WEATHER, "weather_day": True, "fit_usable": False,
        "reasons": (), "tropical": None, "sources": ("ky-summary-2024-25",), "code": "W",
    }  # fmt: skip
    return record.PastDay.model_validate(body | change)


def _count(  # noqa: PLR0913, PLR0917 - one synthetic count
    unit: str, year: str, code: str, days: int, other: int | None = 0, unsure: int | None = 0
) -> record.YearCount:
    return record.YearCount(
        version=1, unit=unit, year=year, code=code, days=days, not_weather=other,
        unconfirmed=unsure, source_kind=SourceKind.PAST_RECORDS, sources=("ky-trend-2025-26",),
        covid=year == "2020-21", disaster=None,
    )  # fmt: skip


def test_a_live_row_is_never_of_the_past_records_kind() -> None:
    read = _read(rows=[_row("9900001", "no_school")])
    (row, *_) = _rows(read, [(s, AT, Status.CLOSED, 7) for s in (0, 1)]).values()
    with pytest.raises(ValueError, match="past records' kind"):
        RecordRow.model_validate(row.model_dump() | {"source_kind": SourceKind.PAST_RECORDS})


def test_past_rows_fit_only_by_their_own_rule_and_never_while_closings_only() -> None:
    known = _past(
        date(2025, 1, 7), klass="warning", weather=3, tropical=False, after=False,
        source_complete=True, closings_only=False, fit_usable=True,
    )  # fmt: skip
    assert record.past_fit_rule(known)
    for change in (
        {"after": None},
        {"klass": "unknown", "weather": None, "tropical": None},
        {"scope": Scope.SHARE},
        {"cause": Cause.NAMED, "weather_day": False},
        {"tropical": True},
    ):
        with pytest.raises(ValueError, match="fit_usable"):
            record.PastDay.model_validate(known.model_dump() | change)
    # a closings-only source is never complete, so never fit-usable
    assert not record.past_fit_rule(_past(date(2025, 1, 7)))


def test_the_kept_record_reads_live_days_past_days_and_yearly_counts_apart(
    tmp_path: Path,
) -> None:
    learn = PredictConfig.load(PIPELINE_ROOT / "config" / "predict.yaml").learn
    closing = [(s, AT, Status.CLOSED, None) for s in (0, 1, 7, 8)]
    live = list(_rows(_read(WED), closing).values())
    past = [_past(WED, "9900001"), _past(date(2025, 1, 7), "9900004")]
    counts = [_count("9900001", "2020-21", "W", 1), _count("9900001", "2021-22", "W", 2)]
    kept = {
        WED.isoformat(): record.day_bytes(live),
        "past/ky-summary-2024-25/v1/days": record.lines_bytes(past, "t"),
        "past/ky-trend-2025-26/v1/counts": record.lines_bytes(counts, "t"),
    }
    rows = record.kept_rows(kept, learn)
    assert rows == [*live, *past]
    assert record.kept_counts(kept) == counts
    # a live take-back day leaves the live rows out, never a state's past row of that day
    no_wed = learn.model_copy(update={"excluded_days": (WED,)})
    assert record.kept_rows(kept, no_wed) == past
    path = tmp_path / "record.parquet"
    assert record.write_table(rows, path, record.kept_counts(kept)) == len(live) + len(past)
    frame = pl.read_parquet(path)
    assert tuple(frame.columns) == record.COLUMNS
    on_wed = frame.filter(pl.col("day") == WED)
    # by day, district, then kind: a district's live row before its past row of the day
    assert list(zip(on_wed["unit"], on_wed["source_kind"], strict=True)) == [
        ("9900001", "live_map"), ("9900001", "past_records"), ("9900004", "live_map"),
    ]  # fmt: skip
    pasts = frame.filter(pl.col("source_kind") == "past_records")
    assert pasts["code"].to_list() == ["W", "W"]
    assert pasts["agrees"].to_list() == [None, None]
    assert pasts["eligible"].to_list() == [None, None]
    assert pasts["klass"].to_list() == ["unknown", "unknown"]
    assert not any(pasts["fit_usable"].to_list())
    years = pl.read_parquet(path.with_name(record.COUNTS_NAME))
    assert tuple(years.columns) == record.COUNT_COLUMNS
    assert years["days"].to_list() == [1, 2]
    assert years["covid"].to_list() == [True, False]


def test_a_past_record_key_holds_no_address_and_strings_are_codes() -> None:
    with pytest.raises(RecordError, match="not a code"):
        record.lines_bytes([_past(WED, code="W W")], "t")


def test_the_record_reads_only_each_files_newest_edition() -> None:
    learn = PredictConfig.load(PIPELINE_ROOT / "config" / "predict.yaml").learn
    old = [_past(date(2025, 1, 7), "9900001")]
    new = [_past(date(2025, 1, 7), "9900001", cause=Cause.NAMED, weather_day=False)]
    kept = {
        "past/ky-summary-2024-25/v1/days": record.lines_bytes(old, "t"),
        "past/ky-summary-2024-25/v2/days": record.lines_bytes(new, "t"),
        "past/ky-summary-2024-25/v1/counts": record.lines_bytes(
            [_count("9900001", "2024-25", "W", 1)], "t"
        ),
        "past/ky-summary-2024-25/v2/counts": record.lines_bytes(
            [_count("9900001", "2024-25", "W", 1, 0, 1)], "t"
        ),
        "past/ky-summary-2024-25/v12/counts": record.lines_bytes(
            [_count("9900001", "2024-25", "W", 1, 1)], "t"
        ),
        "past/ky-summary-2025-26/v9/counts": record.lines_bytes(
            [_count("9900001", "2025-26", "W", 2)], "t"
        ),
        "past/ky-summary-2025-26/v10/counts": record.lines_bytes(
            [_count("9900001", "2025-26", "W", 3)], "t"
        ),
        "past/ky-summary-2025-26/v1/days": record.lines_bytes([_past(date(2026, 1, 7))], "t"),
    }
    said: list[str] = []
    rows = record.kept_rows(kept, learn, said.append)
    # v2 of one file (never v1), and the other file's only edition
    assert rows == [*new, _past(date(2026, 1, 7))]
    # v12 is newer than v2 and v10 than v9 (by number, never by text, which puts v12 before
    # v2 and v10 before v9)
    counts = {c.year: c for c in record.kept_counts(kept, said.append)}
    assert set(counts) == {"2024-25", "2025-26"}
    assert (counts["2024-25"].not_weather, counts["2024-25"].unconfirmed) == (1, 0)
    assert counts["2025-26"].days == 3
    assert said == []
    assert record.past_key("ky-summary-2024-25", 3, record.PAST_DAYS) == (
        "past/ky-summary-2024-25/v3/days"
    )


def test_a_past_key_that_does_not_read_is_warned_of_and_left_out_never_the_record() -> None:
    learn = PredictConfig.load(PIPELINE_ROOT / "config" / "predict.yaml").learn
    good = [_past(date(2025, 1, 7))]
    body = json.loads(record.lines_bytes(good, "t"))
    body.pop("code")  # a row of an older model, say
    kept = {
        "past/ky-summary-2024-25/v1/days": (json.dumps(body) + "\n").encode(),
        "past/ky-summary-2025-26/v1/days": record.lines_bytes(good, "t"),
        "past/ky-summary-2025-26/v1/counts": b"not json\n",
        "past/ky-summary-2025-26/days": record.lines_bytes(good, "t"),  # no edition
        "past/ky-summary-2025-26/v1/counts.bak": b"",
    }
    said: list[str] = []
    assert record.kept_rows(kept, learn, said.append) == good
    assert record.kept_counts(kept, said.append) == []
    assert said == [
        "::warning::predict each-school record: past/ky-summary-2025-26/days: not a past record"
        " key, left out",
        "::warning::predict each-school record: past/ky-summary-2025-26/v1/counts.bak: not a"
        " past record key, left out",
        "::warning::predict each-school record: past/ky-summary-2024-25/v1/days:"
        " ValidationError, its rows do not read; left out",
        "::warning::predict each-school record: past/ky-summary-2025-26/days: not a past record"
        " key, left out",
        "::warning::predict each-school record: past/ky-summary-2025-26/v1/counts.bak: not a"
        " past record key, left out",
        "::warning::predict each-school record: past/ky-summary-2025-26/v1/counts:"
        " ValidationError, its rows do not read; left out",
    ]


def test_a_year_count_holds_no_more_days_not_the_weather_than_it_counts() -> None:
    assert _count("9900001", "2025-26", "W", 3, 1).not_weather == 1
    assert _count("9900001", "2025-26", "W", 3, 1, 2).unconfirmed == 2
    with pytest.raises(ValueError, match="more days not the weather than counted"):
        _count("9900001", "2025-26", "W", 1, 2)
    with pytest.raises(ValueError, match="more days not the weather than counted"):
        _count("9900001", "2025-26", "W", 2, 1, 2)
    # an undated count cannot be checked: both None, never one of them, never 0 for unknown
    assert _count("9900001", "2021-22", "W", 2, None, None).not_weather is None
    for other, unsure in ((None, 0), (0, None)):
        with pytest.raises(ValueError, match="checked for one cause and not the other"):
            _count("9900001", "2021-22", "W", 2, other, unsure)


def _past_offer(file_id: str, kind: str, rows: int) -> Offer:
    """A SYNTHETIC past record key's offer (the past keys go through the record kind's caps)."""
    found = [_past(date(2025, 1, 6 + n % 20), f"{9_900_000 + n}") for n in range(rows)]
    return Offer(evidence.RECORD, record.past_key(file_id, 1, kind), record.lines_bytes(found, "t"))


def test_the_record_kinds_caps_hold_a_past_key_too(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeD1()
    days = _past_offer("ky-summary-2024-25", record.PAST_DAYS, 30)
    over = _past_offer("ky-summary-2025-26", record.PAST_DAYS, 31)
    monkeypatch.setattr(evidence, "RECORD_DAY_BYTES", len(days.data))
    # one past key over the day cap: nothing of the push is written, the key at the cap included
    with pytest.raises(EvidenceError, match=r"past/ky-summary-2025-26/v1/days: refused, .* over"):
        _store(api, RECORD_JOB).push([days, over], (evidence.RECORD,))
    assert set(_items(api).values()) <= {0}
    # a past key at the cap is kept and read back
    assert [r.kept for r in _store(api, RECORD_JOB).push([days], (evidence.RECORD,))] == [1, 1]
    # past keys count toward the total cap with the live days
    live = _record_day("2026-12-01", 3)
    monkeypatch.setattr(evidence, "RECORD_TOTAL_BYTES", _stored(days, live) - 1)
    with pytest.raises(EvidenceError, match=r"record: refused, .* over its"):
        _store(api, RECORD_JOB).push([live], (evidence.RECORD,))
    monkeypatch.setattr(evidence, "RECORD_TOTAL_BYTES", _stored(days, live))
    assert [r.kept for r in _store(api, RECORD_JOB).push([live], (evidence.RECORD,))] == [1, 1]
