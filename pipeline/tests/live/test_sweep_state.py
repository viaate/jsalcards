"""The sweep keeps only what servers asked of it in the state folder (S8-B fix S2, S4).

Every source here is SYNTHETIC.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from snowlight.live.cadence import Cadence
from snowlight.live.ledger import Outcome
from snowlight.live.pool import PassResult, RequestLog, SourceResult
from snowlight.live.sweep import keep_holds, report, summary
from snowlight.sources.stations.registry import load_registry

NOW = datetime(2026, 11, 16, 11, tzinfo=UTC)


def test_a_sweep_keeps_only_the_holds_so_the_live_reader_still_reads_the_rest(
    tmp_path: Path,
) -> None:
    registry = load_registry()
    read, waiting, refused, kept = sorted(registry.stations)[:4]
    path = tmp_path / "cadence.json"
    live = Cadence(registry.stations, {}, registry.poll_minutes, path=path)
    live.record(NOW - timedelta(hours=1), [(kept, Outcome.OK, None)])  # the live reader's
    live.save()
    sources = (
        SourceResult(read, Outcome.OK, 1.0, 1.0, 200),
        SourceResult(waiting, Outcome.DEFERRED, 1.0, 2.0, 503, 290.0),
        SourceResult(refused, Outcome.BLOCKED, 1.0, 3.0, 403),
    )
    swept = Cadence(registry.stations, {}, registry.poll_minutes, path=path)
    keep_holds(swept, PassResult(NOW, 3.0, sources, 1))
    after = Cadence(registry.stations, {}, registry.poll_minutes, path=path)
    assert read not in after.clocks  # not recorded as read: the live reader still reads it
    assert after.held_until(waiting, NOW) == NOW + timedelta(seconds=292)
    assert after.held_until(refused, NOW) == NOW + timedelta(hours=24)
    assert after.clocks[kept].outcome is Outcome.OK  # the live reader's own clock is kept


def test_the_summary_line_puts_the_held_back_count_after_the_outcomes() -> None:
    sources = (SourceResult("synthetic-a", Outcome.OK, 1.0, 1.0, 200),)
    found = report(PassResult(NOW, 1.0, sources, 1), RequestLog(), Counter(), label="t")
    line = summary("t", 1, found, 2)
    assert line.endswith("outcomes {'ok': 1}, 2 held back by a server's wait\n")
    assert "robots reads (0 requests), outcomes" in line
