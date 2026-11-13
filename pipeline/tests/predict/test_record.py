"""The record's tests (each-school, spec section 14 "record"). P0 adds the evidence store's
``record`` kind and its caps; P2a1 adds record.py's own tests here.

SYNTHETIC record days only: codes, ids, counts and times.
"""

import json
import math
from datetime import UTC, datetime

import pytest

from predict.test_frozen import FakeD1
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
