"""The gate's NWS days include the current school year's file, as the closure seasons do.

Everything here is SYNTHETIC: the weights build and the current file are replaced by stubs.
"""

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from snowlight.sources.stations import gate, gate_cli, seasons
from snowlight.weights import archive as weights_archive
from snowlight.weights import count as weights_count


def test_the_current_school_years_warnings_are_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    built = SimpleNamespace(tally="built", catalog="catalog", counties="counties")
    monkeypatch.setattr(gate_cli, "count_weather", lambda _cache: built)
    monkeypatch.setattr(seasons, "current_years", lambda _today: [2026])
    monkeypatch.setattr(weights_archive, "load_years", lambda _cache, years: years)
    monkeypatch.setattr(weights_count, "count_years", lambda *_args: "current")
    days: dict[str, dict[str, dict[str, dict[date, float]]]] = {
        "built": {"winter": {"12045": {date(2025, 1, 21): 1.0}}},
        "current": {"tropical": {"12045": {date(2026, 10, 8): 0.5}}},
    }
    monkeypatch.setattr(gate, "group_days", lambda tally: days[tally])
    cache: Any = object()
    found = gate_cli.county_hazard_days(cache, ("winter", "tropical"), date(2026, 10, 13))
    assert found["12045"] == {date(2025, 1, 21): 1.0, date(2026, 10, 8): 0.5}
