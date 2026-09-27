"""Storm days and the storm-ranked archive planners.

The warning tallies, registries and CDX listings here are synthetic; the counting
itself is the weights package's (tested with real IEM rows in tests/weights/).
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.cli import main
from snowlight.sources.stations import archive, storms
from snowlight.sources.stations.registry import load_registry
from snowlight.weights.count import Tally, YearCounts

PAGE_URL = "https://www.wbtv.com/weather/closings/"
EXPORT = "https://s3.amazonaws.com/grayfilestore-wbtv/closingsData/closings_WBTV.json"
CDX_HEADER = ["timestamp", "original", "statuscode", "mimetype", "length", "digest"]


def _registry(tmp_path: Path) -> Path:
    folder = tmp_path / "sources"
    folder.mkdir()
    platform = {
        "id": "graydemo",
        "name": "Demo (synthetic)",
        "operator": "Nobody",
        "adapter": "gray",
        "poll_minutes": 10,
        "terms": {"automated_access": "unread", "summary": "synthetic", "evidence": []},
        "notes": "synthetic",
    }
    station = {
        "id": "graydemo-wbtv",
        "platform": "graydemo",
        "call_sign": "WBTV",
        "name": "synthetic",
        "market": "Charlotte",
        "dma": None,
        "states": ["NC"],
        "counties": {"basis": "observed", "source": "synthetic", "fips": ["37119", "37179"]},
        "page_url": PAGE_URL,
        "data_url": EXPORT,
        "archive_urls": [PAGE_URL, EXPORT],
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
    }
    content = {"platform": platform, "stations": [station]}
    (folder / "graydemo.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return folder


def _artifact(tmp_path: Path) -> Path:
    """An artifact with no downloaded capture yet (an empty manifest)."""
    root = tmp_path / "artifact"
    (root / "snapshots").mkdir(parents=True)
    (root / "snapshots" / "manifest.jsonl").write_text("", encoding="utf-8")
    return root


def _tally() -> Tally:
    tally = Tally(years=[2024])
    counts = YearCounts()
    counts.by_code["WW.Y"][date(2025, 1, 6)].add("NCZ071")
    counts.by_code["WS.W"][date(2025, 1, 10)].add("NCZ071")
    counts.by_code["WW.Y"][date(2025, 1, 10)].add("NCZ071")
    counts.by_code["FF.W"][date(2025, 1, 21)].add("NCC119")
    tally.counties["37119"][2024] = counts
    other = YearCounts()
    other.by_code["WS.W"][date(2025, 1, 10)].add("NCZ072")
    tally.counties["37179"][2024] = other
    return tally


def test_county_days_keep_winter_and_cold_codes_at_their_weight() -> None:
    days = storms.county_days(_tally())
    # The flash flood day is left out; 10 January takes the warning's weight.
    assert days == {
        "37119": {date(2025, 1, 6): 0.25, date(2025, 1, 10): 1.0},
        "37179": {date(2025, 1, 10): 1.0},
    }


def test_station_score_is_the_market_mean_for_the_school_day(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    found = storms.StormDays.build(registry, storms.county_days(_tally()))
    # The mean over the market's two counties: both under the warning on the 10th,
    # one under the advisory on the 6th.
    assert list(found.days("graydemo-wbtv")) == [
        (date(2025, 1, 10), 1.0),
        (date(2025, 1, 6), 0.125),
    ]
    # 9 January 21:00 UTC is the afternoon before: closings for the 10th are posted.
    assert found.score("graydemo-wbtv", datetime(2025, 1, 9, 21, tzinfo=UTC)) == 1.0
    assert found.score("graydemo-wbtv", datetime(2025, 1, 10, 13, tzinfo=UTC)) == 1.0
    assert found.score("graydemo-wbtv", datetime(2025, 1, 10, 17, tzinfo=UTC)) == 0.0
    assert found.score("graydemo-other", datetime(2025, 1, 10, 13, tzinfo=UTC)) == 0.0
    assert storms.school_day(datetime(2025, 1, 5, 23, tzinfo=UTC)) == date(2025, 1, 6)


def test_plan_snapshots_takes_storm_days_before_size(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    found = storms.StormDays.build(registry, storms.county_days(_tally()))
    rows = [
        CDX_HEADER,
        ["20250103140000", PAGE_URL, "200", "text/html", "90000", "A"],
        ["20250110130000", PAGE_URL, "200", "text/html", "40000", "B"],
        ["20250106120000", PAGE_URL, "200", "text/html", "30000", "C"],
    ]
    path = tmp_path / "cdx.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    captures = {"graydemo-wbtv": archive.read_cdx(path)}
    by_size = archive.plan_snapshots(captures)
    assert by_size == [{"timestamp": "20250103140000", "url": PAGE_URL}]
    by_storm = archive.plan_snapshots(captures, archive.PlanOptions(per_season=2, storms=found))
    assert by_storm == [
        {"timestamp": "20250110130000", "url": PAGE_URL},
        {"timestamp": "20250106120000", "url": PAGE_URL},
    ]


def test_plan_follow_asks_an_unread_station_for_its_storm_days(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    found = storms.StormDays.build(registry, storms.county_days(_tally()))
    root = _artifact(tmp_path)
    listing = root / "cdx" / "listing.json"
    listing.parent.mkdir(parents=True)
    rows = [
        CDX_HEADER,
        ["20250103140000", EXPORT + "?rnd=1&arc-site=wbtv", "200", "application/json", "9000", "A"],
        ["20250110120000", EXPORT + "?rnd=2&arc-site=wbtv", "200", "application/json", "85", "B"],
        ["20250110121000", EXPORT + "?rnd=3&arc-site=wbtv", "200", "application/json", "85", "C"],
        ["20250106120000", PAGE_URL, "200", "text/html", "30000", "D"],
    ]
    listing.write_text(json.dumps(rows), encoding="utf-8")
    plan = archive.plan_follow(registry, root, per_season=0, storms=found)
    # The warning day's export first (one per URL and day), then the advisory day's
    # page; the large capture of a quiet day is not asked for.
    assert plan == [
        {"timestamp": "20250110120000", "url": EXPORT + "?rnd=2&arc-site=wbtv"},
        {"timestamp": "20250106120000", "url": PAGE_URL},
    ]
    plain = archive.plan_follow(registry, root, per_season=0)
    assert plain[0] == {"timestamp": "20250103140000", "url": EXPORT + "?rnd=1&arc-site=wbtv"}


def test_cli_plan_ranks_by_storm_days_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _registry(tmp_path)
    cdx = tmp_path / "cdx"
    cdx.mkdir()
    rows = [
        CDX_HEADER,
        ["20250103140000", PAGE_URL, "200", "text/html", "90000", "A"],
        ["20250110130000", PAGE_URL, "200", "text/html", "40000", "B"],
        ["20250106120000", PAGE_URL, "200", "text/html", "30000", "C"],
    ]
    (cdx / "listing.json").write_text(json.dumps(rows), encoding="utf-8")
    # The storm days come from a synthetic tally instead of the cached IEM files.
    monkeypatch.setattr(storms, "load_county_days", lambda: storms.county_days(_tally()))
    args = ["stations", "--registry", str(folder), "archive", "plan", str(cdx)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["snapshots"] == [
        {"timestamp": "20250110130000", "url": PAGE_URL}
    ]
    assert main([*args, "--by-size"]) == 0
    assert json.loads(capsys.readouterr().out)["snapshots"] == [
        {"timestamp": "20250103140000", "url": PAGE_URL}
    ]
