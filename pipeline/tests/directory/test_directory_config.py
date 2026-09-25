"""Tests for directory.yaml and the build report."""

import copy
from pathlib import Path
from typing import Any

import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import ValidationError

from snowlight.directory.config import DEFAULT_CONFIG_PATH, DirectoryConfig, load_config
from snowlight.directory.filters import Reason
from snowlight.directory.report import ReconciliationError, reconcile, render_markdown

CONTIGUOUS_EXCLUDED = {"02", "15"}


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    loaded = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_real_config_loads() -> None:
    config = load_config()
    assert len(config.sources) == 7
    states = config.filters.state_fips
    assert len(states) == 49  # 48 contiguous states + DC
    assert not CONTIGUOUS_EXCLUDED & set(states)
    assert "11" in states
    assert all(int(code) < 60 for code in states)  # no territories
    assert config.tiles.minzoom == 9
    assert config.tiles.maxzoom == 14
    for key, source in config.sources.items():
        pinned = [c for c in source.candidates if c.sha256]
        assert pinned, f"{key} has no pinned release"
        assert all(c.url.startswith("https://nces.ed.gov/") for c in source.candidates)
    private = config.sources["private_school_geocodes"].candidates
    assert [c.school_year for c in private] == ["2024-2025", "2023-2024"]


def _mutated(raw: dict[str, Any], path: list[str | int], value: Any) -> dict[str, Any]:
    data = copy.deepcopy(raw)
    target: Any = data
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data


CANDIDATE = ["sources", "pss", "candidates", 0]


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ([*CANDIDATE, "url"], "http://nces.ed.gov/x.zip", "https"),
        ([*CANDIDATE, "sha256"], "ABC", "64 lowercase hex"),
        ([*CANDIDATE, "school_year"], "2023-2025", "2024-2025"),
        ([*CANDIDATE, "members"], {"header": "x"}, "table"),
        (["filters", "state_fips"], ["01", "01"], "distinct"),
        (["filters", "bounds", "west"], 0.0, "ordered"),
        (["tiles", "minzoom"], 15, "minzoom"),
        (["sources", "pss"], KeyError, "missing sources"),
        (["surprise"], 1, "Extra inputs"),
    ],
)
def test_config_validation(
    raw: dict[str, Any], path: list[str | int], value: Any, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        DirectoryConfig.model_validate(_mutated(raw, path, value))


def test_load_config_from_path(tmp_path: Path, raw: dict[str, Any]) -> None:
    path = tmp_path / "d.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert load_config(path).tiles.layer == "schools"


# Synthetic frames below: reconciliation arithmetic, not NCES content.
def _frame(states: list[str | None], reasons: list[str | None]) -> pl.DataFrame:
    return pl.DataFrame(
        {"state": states, "drop_reason": reasons},
        schema={"state": pl.String, "drop_reason": pl.String},
    )


def test_reconcile_counts_by_state() -> None:
    frame = _frame(
        ["AL", "AL", "AK", None], [None, "status_closed", "outside_continental_us", None]
    )
    reasons = [Reason.NO_COORDINATES, Reason.OUTSIDE_CONTINENTAL_US, Reason.STATUS_CLOSED]
    result = reconcile(frame, 4, "synthetic", reasons)
    assert result["kept"] == 2
    # Every applicable filter is listed, in order, even when it dropped nothing.
    assert list(result["dropped"].items()) == [
        ("no_coordinates", 0),
        ("outside_continental_us", 1),
        ("status_closed", 1),
    ]
    assert result["by_state"]["AL"] == {
        "source_rows": 2,
        "kept": 1,
        "dropped": {"status_closed": 1},
    }
    assert result["by_state"]["unknown"]["kept"] == 1


def test_reconcile_refuses_mismatches() -> None:
    frame = _frame(["AL"], [None])
    with pytest.raises(ReconciliationError, match="assembled from 2"):
        reconcile(frame, 2, "synthetic", [])
    with pytest.raises(ReconciliationError, match="undocumented"):
        reconcile(_frame(["AL"], ["because"]), 1, "synthetic", list(Reason))
    with pytest.raises(ReconciliationError, match="undocumented"):
        reconcile(_frame(["AL"], ["status_closed"]), 1, "synthetic", [Reason.NO_COORDINATES])


def test_render_markdown_tables() -> None:
    section = reconcile(
        _frame(["AL", "AK"], [None, "outside_continental_us"]),
        2,
        "synthetic",
        [Reason.OUTSIDE_CONTINENTAL_US],
    )
    report = {
        "generated_at": "2026-09-24T23:00:00Z",
        "public": section,
        "private": section,
        "districts": section,
        "notes": ["a note"],
        "outputs": {"points.bin": {"bytes": 29, "gzip_bytes": 40}},
        "tileset_check": {
            "tiles": 3,
            "feature_instances": 7,
            "schools_per_zoom": {"9": 2},
            "string_pool_pairs_separated": 1,
        },
    }
    text = render_markdown(report)
    assert "| Public schools | 2 | 1 | 1 |" in text
    assert "| AK | 0 / 1 | 0 / 1 | 0 / 1 |" in text
    assert "| public | `outside_continental_us` | 1 |" in text
    assert "- a note" in text
    assert "| points.bin | 29 | 40 |" in text
    assert "Decoded 3 tiles holding 7 features" in text
    assert "z9: 2" in text
