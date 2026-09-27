"""The ``stations robots`` and ``stations coverage`` commands, offline.

Every server here is synthetic (an in-memory httpx transport). Reference files
are the real slices in fixtures/reference/ and the NWS county shapefile slice the
weather tests use (tests/weather/fixtures/c_18mr25.zip, see its provenance.json).
"""

import json
import shutil
from pathlib import Path

import httpx
import polars as pl
import pytest

from snowlight.cli import main
from snowlight.sources.stations import cli as stations_cli
from snowlight.sources.stations import coverage
from snowlight.sources.stations import fetch as fetch_module
from snowlight.sources.stations.http import USER_AGENT
from snowlight.sources.stations.registry import DEFAULT_REGISTRY_DIR, load_registry

TESTS = Path(__file__).resolve().parents[1]
REFERENCE = TESTS / "stations" / "fixtures" / "reference"
COUNTIES = TESTS / "weather" / "fixtures" / "c_18mr25.zip"


def _robots(request: httpx.Request) -> httpx.Response:
    if request.url.host == "s3.amazonaws.com":
        return httpx.Response(403)
    if request.url.path == "/robots.txt":
        body = (
            b"User-agent: ClaudeBot\nDisallow: /\n\n"
            b"User-agent: *\nDisallow: /api/\nCrawl-Delay: 10\n"
        )
        return httpx.Response(200, content=body)
    return httpx.Response(599)


def test_robots_update_records_the_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "sources"
    shutil.copytree(DEFAULT_REGISTRY_DIR, folder)
    monkeypatch.setattr(
        stations_cli,
        "make_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(_robots), headers={"User-Agent": USER_AGENT}
        ),
    )
    monkeypatch.setattr(fetch_module, "DEFAULT_CACHE_DIR", tmp_path / "cache")
    wanted = ["gray-kctv", "hearst-kmbc"]
    code = main(["stations", "--registry", str(folder), "robots", "--update", "--only", *wanted])
    assert code == 0
    out = capsys.readouterr().out
    assert "gray-kctv https://s3.amazonaws.com/" in out
    registry = load_registry(folder)
    kctv = registry.stations["gray-kctv"].robots
    export = next(check for check in kctv if check.url.startswith("https://s3.amazonaws.com/"))
    assert export.state.value == "unavailable"
    assert export.allowed
    kmbc = registry.stations["hearst-kmbc"].robots
    assert kmbc[0].allowed
    assert kmbc[0].crawl_delay == 10.0
    assert kmbc[0].disallowed_agents == ("claudebot",)
    # Stations not asked for keep what the registry already recorded.
    before = load_registry(DEFAULT_REGISTRY_DIR)
    assert registry.stations["gray-kait"].robots == before.stations["gray-kait"].robots


def test_coverage_command_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    references = {
        "dma": REFERENCE / "usa-tvdma-county.slice.csv",
        "gazetteer": REFERENCE / "2025_Gaz_counties_national.slice.zip",
        "ct": REFERENCE / "ct_cou_to_cousub_crosswalk.xlsx",
        "shapes": COUNTIES,
        "states": REFERENCE / "state.txt",
    }
    monkeypatch.setattr(stations_cli, "_references", lambda _cache, _root: references)
    directory = tmp_path / "schools.parquet"
    pl.DataFrame(
        {
            "state": ["MO", "KS", "VT"],
            "county_fips": ["29095", "20091", "50015"],
            "county_name": ["Jackson County", "Johnson County", "Lamoille County"],
        }
    ).write_parquet(directory)
    out = tmp_path / "out"
    code = main(
        [
            "stations",
            "coverage",
            "--directory",
            str(directory),
            "--health",
            str(tmp_path / "missing.json"),
            "--out-dir",
            str(out),
            "--no-weights",
        ]
    )
    assert code == 0
    assert "0 of 3 schools covered by a working source" in capsys.readouterr().out
    document = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    assert document["national"] == {
        "schools": 3,
        "covered": 0,
        "share": 0.0,
        "meets_target": False,
    }
    assert document["weights"] is None
    assert document["stations"]["gray-kctv"]["state"] == "not_read"
    assert document["health_generated_at"] is None
    assert (out / "coverage.png").read_bytes()[:4] == b"\x89PNG"


def test_county_shapes_reads_fips_named_files() -> None:
    shapes = coverage.county_shapes(COUNTIES)
    assert "50015" in shapes


def test_coverage_command_reports_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["stations", "--registry", str(tmp_path), "coverage"])
    assert code == 1
    assert "stations coverage failed" in capsys.readouterr().err
