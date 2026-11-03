"""The ledger's cold census in ``live state export`` (predict-next CALL-TIME-1): the standing rows
whose ``lo`` is unknown from a cold start, counted read only, never raising. Every list and row
here is made up for the tests (SYNTHETIC)."""

import argparse
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from snowlight.live import cli as live_cli
from snowlight.live import ledger as ledger_module
from snowlight.live.ledger import Ledger, Outcome, SeenRow, cold_census
from snowlight.live.state import ARCHIVE


def ledger_with_rows(path: Path) -> None:
    """SYNTHETIC: one list read first on Jan 14 (a cold start), read again after a 40-hour gap
    with a new row (cold, nothing in the 36 h before); a second list's first read (cold rows),
    one of which is back after 3 h on a later day (seen again cold, with a good read in the 36 h
    before)."""
    found = Ledger(path)
    start = datetime(2026, 1, 14, 12, tzinfo=UTC)
    row = SeenRow(name="Synthetic", text="closed")
    found.observe("tv", Outcome.OK, start, [row])
    later = start + timedelta(hours=40)
    found.observe("tv", Outcome.OK, later, [row, replace(row, name="Other")])
    found.observe("radio", Outcome.ERROR, later)
    # a second list's row away from 16:00 to the next day, back after 3 h on a later day
    rows = [row, replace(row, name="Two"), replace(row, name="Three")]
    found.observe("paper", Outcome.OK, start - timedelta(hours=8), rows)
    found.observe("paper", Outcome.OK, start + timedelta(hours=4), rows[1:])
    found.observe("paper", Outcome.OK, start + timedelta(hours=24), rows)
    # a cold row with a row stamp 2 hours before its first sighting: dated by it, never
    # withheld as unknown_start, so never counted; one stamped 40 hours before is
    stamped = SeenRow(name="Stamped", text="closed", row_stamp=start - timedelta(hours=10))
    old = SeenRow(name="Old", text="closed", row_stamp=start - timedelta(hours=48))
    found.observe("board", Outcome.OK, start - timedelta(hours=8), [stamped, old])
    found.close()


def test_the_cold_census_counts_rows_and_never_raises(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite"
    assert cold_census(path) == "ledger cold census: no ledger"
    ledger_with_rows(path)
    line = cold_census(path)
    assert line == (
        "ledger cold census: 6 rows present with lo unknown from a cold start and no row stamp "
        "dating them (unknown_start) (5 with no good read of their source in the 36 h before: a "
        "first read or a gap; 1 with one: back after 3 h on a later day, or a tied successor; 0 "
        "before what good_reads keeps) in 3 sources; by first-seen UTC day: 2026-01-14 4, "
        "2026-01-15 1, 2026-01-16 1"
    )
    assert ledger_module.last_outcomes(path) == {
        "board": "ok", "paper": "ok", "radio": "error", "tv": "ok"
    }  # fmt: skip
    before = path.read_bytes()
    assert cold_census(path) == line
    assert path.read_bytes() == before
    path.write_bytes(b"not a database")
    assert cold_census(path).startswith("ledger cold census: unreadable (")


def test_the_census_line_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    ledger_with_rows(state / "ledger.sqlite")
    assert live_cli.census_line(state).startswith("ledger cold census: 6 rows")

    def broken(*_args: object, **_kwargs: object) -> str:
        raise sqlite3.OperationalError("synthetic")

    monkeypatch.setattr(ledger_module, "cold_census", broken)
    assert live_cli.census_line(state) == "ledger cold census: unreadable (OperationalError)"


def _export(state: Path, out: Path, capsys: Any) -> tuple[int, bytes, str]:
    out.mkdir()
    args = argparse.Namespace(state_action="export", state=state, out=out, config=None)
    code = live_cli.run_state(args)
    return code, (out / ARCHIVE).read_bytes(), capsys.readouterr().out


def test_the_state_export_is_unchanged_when_the_census_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    ledger_with_rows(state / "ledger.sqlite")
    code, data, out = _export(state, tmp_path / "a", capsys)
    assert code == 0
    assert "ledger cold census: 6 rows present" in out

    def broken(*_args: object, **_kwargs: object) -> str:
        raise sqlite3.OperationalError("synthetic")

    monkeypatch.setattr(ledger_module, "cold_census", broken)
    again, same, said = _export(state, tmp_path / "b", capsys)
    assert again == 0
    assert same == data
    assert "ledger cold census: unreadable (OperationalError)" in said
