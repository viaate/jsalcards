"""Each live source's read cause, kept in the cadence and counted in ``live state export``'s
``read causes:`` line (predict-next LIVE-READS, LEAD-1). Every list here is made up for the
tests (SYNTHETIC)."""

import argparse
import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from live.test_cold_census import ledger_with_rows
from snowlight.live import causes as causes_module
from snowlight.live import cli as live_cli
from snowlight.live.cadence import Cadence
from snowlight.live.causes import Cause, cause_of, causes_line, kept_causes, tally
from snowlight.live.ledger import Outcome
from snowlight.live.pool import PassResult, SourceResult
from snowlight.live.reads import keep_pass
from snowlight.live.state import ARCHIVE
from snowlight.sources.stations.fetch import RunResult
from snowlight.sources.stations.model import HealthStatus, SourceHealth

NOW = datetime(2026, 1, 16, 12, tzinfo=UTC)


def result(
    outcome: Outcome,
    status: int | None = None,
    *,
    health: HealthStatus | None = None,
    in_health: int | None = None,
) -> SourceResult:
    """SYNTHETIC: one source's read of a pass, with a last health record when ``health``."""
    found = RunResult()
    if health is not None:
        found.health.append(
            SourceHealth(
                source_id="tv", url=None, checked_at=NOW, status=health, rows=0,
                http_status=in_health, reason="synthetic" if health is not HealthStatus.EMPTY
                else None,
            )
        )  # fmt: skip
    return SourceResult("tv", outcome, 1.0, 1.0, http_status=status, result=found)


@pytest.mark.parametrize(
    ("read", "cause"),
    [
        (result(Outcome.OK, 200), Cause.OK),
        (result(Outcome.NOT_MODIFIED, 304), Cause.OK),
        (result(Outcome.EMPTY, 200), Cause.EMPTY),
        (result(Outcome.ERROR, 200, health=HealthStatus.STALE, in_health=200), Cause.STALE),
        (result(Outcome.BLOCKED, 401), Cause.REFUSED_401),
        (result(Outcome.BLOCKED, 403), Cause.REFUSED_403),
        (result(Outcome.BLOCKED, None), Cause.REFUSED_403),
        (result(Outcome.DEFERRED, 429), Cause.REFUSED_429),
        (result(Outcome.ERROR, 429), Cause.REFUSED_429),
        (result(Outcome.ERROR, None, health=HealthStatus.ERROR, in_health=404), Cause.HTTP_4XX),
        (result(Outcome.ERROR, 503), Cause.HTTP_5XX),
        (result(Outcome.ERROR, None), Cause.NO_ANSWER),
        (result(Outcome.LATE), Cause.TIMEOUT),
        (result(Outcome.DEFERRED, None), Cause.DEFERRED),
        (result(Outcome.PARTIAL, 200), Cause.PARTIAL),
        (result(Outcome.ERROR, 302), Cause.ERROR),
    ],
)
def test_each_cause(read: SourceResult, cause: Cause) -> None:
    assert cause_of(read) is cause


def test_keep_pass_keeps_each_cause_in_the_cadence(tmp_path: Path) -> None:
    path = tmp_path / "cadence.json"
    cadence = Cadence({}, {}, lambda _station: 30, path=path)
    reads = (
        SourceResult("tv", Outcome.BLOCKED, 1.0, 1.0, http_status=401),
        SourceResult("radio", Outcome.LATE, 0.0, 0.0),
    )
    keep_pass(cadence, PassResult(NOW, 2.0, reads, 1))
    assert kept_causes(tmp_path) == {"radio": "timeout", "tv": "refused_401"}
    # read again, the cause survives, and an old file without causes still reads
    again = Cadence({}, {}, lambda _station: 30, path=path)
    assert again.clocks["tv"].cause == "refused_401"
    document = json.loads(path.read_text())
    for value in document["sources"].values():
        del value["cause"]
    path.write_text(json.dumps(document))
    old = Cadence({}, {}, lambda _station: 30, path=path)
    assert old.clocks["tv"].cause is None
    assert old.clocks["tv"].outcome is Outcome.BLOCKED
    assert kept_causes(tmp_path) == {}


def coverage_files(folder: Path) -> tuple[Path, Path]:
    """SYNTHETIC coverage files: tv and radio carry archive audiences (tier A), paper and
    board are county-proven (tier B; tv too, which stays A)."""
    folder.mkdir(parents=True, exist_ok=True)
    audiences = folder / "audiences.json.gz"
    sources = folder / "read-sources.json.gz"
    audiences.write_bytes(
        gzip.compress(
            json.dumps(
                {"schema_version": 3, "season": 2025, "audiences": {"tv": ["3600001"], "radio": []}}
            ).encode()
        )
    )
    sources.write_bytes(
        gzip.compress(
            json.dumps(
                {
                    "schema_version": 3,
                    "counties": {"36001": ["paper", "tv"], "36003": ["board"], "36005": ["gone"]},
                    "captures": {},
                    "closing_rows": {},
                }
            ).encode()
        )
    )
    return sources, audiences


def test_the_line_counts_by_tier_with_no_ids(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    ledger_with_rows(state / "ledger.sqlite")  # tv, radio, paper and board
    cadence = Cadence({}, {}, lambda _station: 30, path=state / "cadence.json")
    reads = (
        SourceResult("tv", Outcome.BLOCKED, 1.0, 1.0, http_status=403),
        SourceResult("paper", Outcome.OK, 1.0, 1.0, http_status=200),
        SourceResult("elsewhere", Outcome.DEFERRED, 1.0, 1.0, http_status=429),
    )
    keep_pass(cadence, PassResult(NOW, 2.0, reads, 1))
    sources, audiences = coverage_files(tmp_path / "coverage")
    line = causes_line(state, NOW, read_sources=sources, audiences=audiences)
    assert line == (
        "read causes: A 2 lists: refused_403 1, never read 0, dark 1; "
        "B 3 lists: ok 1, never read 1, dark 1; "
        "other 1 lists: refused_429 1, never read 0, dark 1"
    )
    for name in ("tv", "radio", "paper", "board", "gone", "elsewhere", "3600001"):
        assert name not in line
    # 45 days on, every list is dark
    later = causes_line(state, NOW + timedelta(days=46), read_sources=sources, audiences=audiences)
    assert "A 2 lists: refused_403 1, never read 0, dark 2" in later


def test_tally_counts_never_read_and_dark() -> None:
    found = tally({"A": {"a", "b"}, "B": {"c"}}, {"a": "ok"}, {"a": NOW, "c": None}, NOW)
    assert found["A"]["ok"] == 1
    assert found["A"]["never read"] == 1
    assert found["A"]["dark"] == 1
    assert found["B"]["dark"] == 1
    assert found["B"]["never read"] == 0
    assert found["other"]["lists"] == 0


def _export(state: Path, out: Path, capsys: Any) -> tuple[int, bytes, str]:
    out.mkdir()
    args = argparse.Namespace(state_action="export", state=state, out=out, config=None)
    code = live_cli.run_state(args)
    return code, (out / ARCHIVE).read_bytes(), capsys.readouterr().out


def test_the_export_prints_the_line_and_a_failure_leaves_it_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    ledger_with_rows(state / "ledger.sqlite")
    code, data, out = _export(state, tmp_path / "a", capsys)
    assert code == 0
    assert "read causes: A " in out

    def broken(*_args: object, **_kwargs: object) -> dict[str, str]:
        raise OSError("synthetic")

    monkeypatch.setattr(causes_module, "kept_causes", broken)
    again, same, said = _export(state, tmp_path / "b", capsys)
    assert again == 0
    assert same == data
    assert "read causes: unreadable (OSError)" in said
    # the cadence file and the ledger are read only
    assert not (state / "cadence.json").exists()
