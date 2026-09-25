"""Tests for the ``snowlight alerts`` command and the build helpers behind it.

The network is the in-memory fixture server (see conftest.py). The schools
tables written here are synthetic (ids ``synthetic-*``, placed inside real
fixture zones), except in ``test_cli_schools_for_a_past_date``, which uses the
real NCES rows in ``fixtures/nces-schools.json``.
"""

import json
from dataclasses import replace
from datetime import date, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import polars as pl
import pytest
from shapely.geometry import Point

from snowlight.cli import main
from snowlight.sources.nws.alerts import ACTIVE_URL
from snowlight.sources.nws.http import sha256_file
from snowlight.weather.build import (
    WeatherBuildError,
    ZoneFootprint,
    backfill,
    build_live,
    check_places,
    live_index,
)
from snowlight.weather.publish import FORBIDDEN_IN_PUBLISHED, Rendered, render
from snowlight.weather.timezones import LocalWindow

if TYPE_CHECKING:
    from weather.conftest import Kit

FIXTURES = Path(__file__).parent / "fixtures"


def _paths(tmp_path: Path) -> list[str]:
    return [
        "--cache-dir",
        str(tmp_path / "cache"),
        "--out-dir",
        str(tmp_path / "site"),
        "--manifest",
        str(tmp_path / "manifests" / "alerts.json"),
    ]


def test_build_live_writes_the_file_and_its_manifest(offline: "Kit", tmp_path: Path) -> None:
    with offline.cache() as cache:
        result = build_live(
            cache,
            cache_dir=offline.cache_dir,
            out_dir=tmp_path / "site",
            manifest_path=tmp_path / "manifest.json",
        )
        again = build_live(
            cache,
            cache_dir=offline.cache_dir,
            out_dir=tmp_path / "site",
            manifest_path=tmp_path / "manifest.json",
        )
    assert (result.features, result.kept, result.published) == (12, 7, 7)
    assert result.dropped == {"event not on the allowlist": 3, "outside the contiguous states": 2}
    assert result.not_modified is False
    assert again.not_modified is True
    published = result.path.read_bytes()
    assert result.path == tmp_path / "site" / "live" / "alerts.json"
    assert not any(needle in published.decode().lower() for needle in FORBIDDEN_IN_PUBLISHED)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["feed"]["request"] == ACTIVE_URL
    assert manifest["feed"]["file"]["sha256"]
    assert manifest["feed"]["updated"] == "2026-09-25T00:09:38Z"
    assert manifest["kept"] == 7
    assert manifest["output"]["alerts"] == 7
    assert len(manifest["dropped"]) == 5
    ids = {entry["id"] for entry in json.loads(published)["alerts"]}
    assert ids == {entry["id"] for entry in manifest["published"]}
    members = [m for entry in manifest["published"] for m in entry["members"]]
    assert all(m["nws_id"].startswith("urn:oid:") for m in members)
    ffw = next(m for m in members if m["event"] == "Flash Flood Warning")
    assert ffw["vtec"] == ["O.NEW.KABQ.FF.W.0185"]
    assert ffw["zones"] == ["county NMC009", "county NMC041"]
    assert {f["release"]["valid_from"] for f in manifest["boundaries"]["files"]} == {"2026-04-16"}
    assert manifest["output"]["validated_against"] == "snowlight.schemas.live.AlertsFile"


def test_build_live_refuses_a_file_the_shared_schema_rejects(
    offline: "Kit", tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synthetic: the renderer is made to emit a schema version the schema does not know."""
    real = render

    def wrong_version(*args: Any, **kwargs: Any) -> Rendered:
        rendered = real(*args, **kwargs)
        return replace(rendered, data=rendered.data.replace(b'"schema":1', b'"schema":2'))

    monkeypatch.setattr("snowlight.weather.build.render", wrong_version)
    with offline.cache() as cache, pytest.raises(WeatherBuildError, match="shared schema"):
        build_live(cache, cache_dir=offline.cache_dir, out_dir=tmp_path / "site")
    assert not (tmp_path / "site" / "live" / "alerts.json").exists()


def test_live_index_answers_the_weather_check(offline: "Kit") -> None:
    with offline.cache() as cache:
        index = live_index(cache, offline.cache_dir)
    # Two polygons, the flash flood warning's county list, and 1 + 1 + 1 + 3 + 5 zones.
    assert len(index) == 2 + 1 + 11


def test_backfill_caches_the_days_and_releases(offline: "Kit") -> None:
    offline.serve_days_without_rows(date(2026, 1, 4), date(2026, 1, 28))
    with offline.cache() as cache:
        result = backfill(cache, date(2026, 1, 26), date(2026, 1, 26), cache_dir=offline.cache_dir)
    # From the day before 21 days before the local day starts (05:00 UTC), to the next UTC day.
    assert result.days == 24
    assert result.downloaded == 24
    assert result.final == 24
    assert result.rows > 0
    assert (result.snapshots, result.ranges, result.carried) == (1, 0, 0)
    with offline.cache() as cache, pytest.raises(ValueError, match="before the start"):
        backfill(cache, date(2026, 1, 26), date(2026, 1, 25), cache_dir=offline.cache_dir)


def test_cli_live(offline: "Kit", tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["alerts", "live", *_paths(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "feed: 12 alerts" in out
    assert "kept 7; dropped 5" in out
    assert (tmp_path / "site" / "live" / "alerts.json").is_file()
    offline.server.queue(ACTIVE_URL, 403)
    assert main(["alerts", "live", *_paths(tmp_path)]) == 1
    assert "HTTP 403" in capsys.readouterr().err
    assert main(["alerts", "live", *_paths(tmp_path), "--max-bytes", "100"]) == 1
    assert "budget" in capsys.readouterr().err


def test_cli_check_live(offline: "Kit", tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    catalog = offline.catalog()
    zones = catalog.boundaries_for("zone", date(2026, 9, 25))
    assert zones is not None
    point = zones.areas["NCZ204"].representative_point()
    args = ["alerts", "check", "--cache-dir", str(tmp_path / "c"), "--live"]
    where = ["--lat", str(point.y), "--lon", str(point.x), "--date", "2026-09-25"]
    assert main([*args, *where]) == 0
    captured = capsys.readouterr()
    [line] = captured.out.splitlines()
    record = json.loads(line)
    assert record["event"] == "Coastal Flood Warning"
    assert (record["coverage"], record["basis"], record["precision"]) == (
        "covered",
        "zone",
        "exact",
    )
    assert record["zones"] == ["America/New_York"]
    assert "1 alerts covered the place, 0 uncertain" in captured.err
    assert "2026-09-25T04:00:00Z to 2026-09-26T04:00:00Z (America/New_York)" in captured.err
    # Without --date it is today where the place is: the fixture clock reads
    # 00:09 UTC on 25 September, still the 24th in New York.
    assert main([*args, *where[:4]]) == 0
    assert "2026-09-24T04:00:00Z to 2026-09-25T04:00:00Z" in capsys.readouterr().err
    county_only = [*args, "--county", "35009", "--tz", "America/Denver", "--date", "2026-09-24"]
    assert main(county_only) == 0
    captured = capsys.readouterr()
    [flood] = [json.loads(line) for line in captured.out.splitlines()]
    assert (flood["event"], flood["coverage"]) == ("Flash Flood Warning", "uncertain")
    assert "no point given" in captured.err


def test_cli_check_archive(
    offline: "Kit", tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    offline.serve_days_without_rows(date(2026, 1, 4), date(2026, 1, 27))
    zones = offline.catalog().boundaries_for("zone", date(2026, 1, 26))
    assert zones is not None
    point = zones.areas["MEZ013"].representative_point()
    argv = ["alerts", "check", "--cache-dir", str(tmp_path / "c"), "--date", "2026-01-26"]
    argv += ["--lat", str(point.y), "--lon", str(point.x), "--from", "06:00", "--to", "09:00"]
    assert main(argv) == 0
    [line] = capsys.readouterr().out.splitlines()
    assert json.loads(line)["key"] == "vtec:GYX.WS.W.0001.2026"


def test_cli_check_errors(
    offline: "Kit", tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = ["alerts", "check", "--cache-dir", str(tmp_path / "c"), "--live"]
    assert main(base) == 2
    assert main([*base, "--lat", "30"]) == 2
    assert "give --lat and --lon" in capsys.readouterr().err
    assert main([*base, "--county", "99999"]) == 1
    assert "time zone unknown" in capsys.readouterr().err
    offline.server.queue(ACTIVE_URL, 403)
    assert main([*base, "--county", "35009", "--tz", "America/Denver"]) == 1
    assert "HTTP 403" in capsys.readouterr().err
    for bad in (["--date", "2026-13-01"], ["--from", "6am"], ["--to", "25:00"], ["--county", "1"]):
        with pytest.raises(SystemExit) as info:
            main([*base, *bad])
        assert info.value.code == 2


def test_cli_backfill(offline: "Kit", tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    offline.serve_days_without_rows(date(2026, 1, 20), date(2026, 1, 28))
    argv = ["alerts", "backfill", "--cache-dir", str(tmp_path / "c")]
    argv += ["--start", "2026-01-26", "--end", "2026-01-26", "--lookback-days", "3"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "6 day files (6 downloaded, 6 final)" in out
    assert "1 snapshots; 0 range files for 0 events" in out
    assert main([*argv[:4], "--start", "2026-01-26", "--end", "2026-01-20"]) == 1
    assert "before the start" in capsys.readouterr().err


def test_cli_schools(offline: "Kit", tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    zones = offline.catalog().boundaries_for("zone", date(2026, 9, 25))
    assert zones is not None
    inside = zones.areas["NCZ204"].representative_point()
    montana = zones.areas["MTZ303"].representative_point()
    schools = pl.DataFrame(
        {
            "id": ["synthetic-1", "synthetic-2", "synthetic-3", "synthetic-4"],
            "county_fips": ["37055", None, "04001", "30073"],
            "lat": [inside.y, 40.0, 34.5, montana.y],
            "lon": [inside.x, -100.0, -109.4, montana.x],
        }
    )
    table = tmp_path / "schools.parquet"
    schools.write_parquet(table)
    out = tmp_path / "matches.parquet"
    argv = ["alerts", "schools", "--cache-dir", str(tmp_path / "c"), "--live"]
    argv += ["--schools", str(table), "--out", str(out), "--date", "2026-09-25"]
    assert main(argv) == 0
    message = capsys.readouterr().out
    assert "4 schools checked for 2026-09-25" in message
    assert "2 covered by 2 alerts; 0 more uncertain" in message
    # synthetic-3 is in Apache County, Arizona (Mountain with or without daylight
    # time): it is checked in both zones. Only synthetic-2 has no zone at all.
    assert "1 skipped (time zone unknown)" in message
    matches = pl.read_parquet(out)
    assert matches.select("id", "event", "coverage", "zones").sort("id").rows() == [
        ("synthetic-1", "Coastal Flood Warning", "covered", ["America/New_York"]),
        ("synthetic-4", "High Wind Watch", "covered", ["America/Denver"]),
    ]
    manifest = json.loads((tmp_path / "matches.json").read_text())
    assert manifest["unchecked_ids"] == ["synthetic-2"]
    assert manifest["counts"]["covered_schools"] == 2
    assert manifest["window"] == {
        "date": "2026-09-25",
        "label": "2026-09-25",
        "from": "00:00",
        "to": "00:00",
    }
    assert manifest["output"]["sha256"] == sha256_file(out)
    assert manifest["sources"]["source"] == "live"
    assert manifest["sources"]["feed"]["file"]["url"] == ACTIVE_URL
    assert main(argv[:-2]) == 0
    assert "for today in each school's time zone" in capsys.readouterr().out
    assert main([*argv[:-4], "--schools", str(tmp_path / "missing.parquet")]) == 1
    assert "error" in capsys.readouterr().err


def test_check_places_joins_the_answers_of_every_possible_zone(offline: "Kit") -> None:
    """A place whose time zone is not settled is covered only if every zone's window agrees."""
    with offline.cache() as cache:
        index = live_index(cache, offline.cache_dir)
    zones = offline.catalog().boundaries_for("zone", date(2026, 9, 25))
    assert zones is not None
    point = zones.areas["NYZ074"].representative_point()
    place = pl.DataFrame({"county_fips": [None], "lat": [point.y], "lon": [point.x]})
    # The Coastal Flood Watch begins at 21:00 UTC on 25 September: 17:00 in New
    # York, 16:00 in Chicago. From 16:00 to 16:30 it is in effect only in Chicago.
    early = LocalWindow(date(2026, 9, 25), time(16), time(16, 30))
    both = ["America/New_York", "America/Chicago"]
    [only] = check_places(index, place, [both], early).rows(named=True)
    assert (only["event"], only["coverage"], only["zones"]) == (
        "Coastal Flood Watch",
        "uncertain",
        both,
    )
    late = LocalWindow(date(2026, 9, 25), time(18), time(19))
    [sure] = check_places(index, place, [both], late).rows(named=True)
    assert sure["coverage"] == "covered"
    assert check_places(index, place, [()], late).height == 0
    with pytest.raises(ValueError, match="one list of time zones"):
        check_places(index, place, [], late)


def test_cli_schools_for_a_past_date(
    offline: "Kit", tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The round 1 failure, end to end: real NCES rows, 2025-01-21, the archive."""
    offline.serve_days_without_rows(date(2024, 12, 30), date(2025, 1, 23))
    rows = json.loads((FIXTURES / "nces-schools.json").read_text())
    schools = pl.DataFrame(
        {
            "id": [row["id"] for row in rows],
            "county_fips": [row["county_fips"] for row in rows],
            "lat": [float(row["lat"]) for row in rows],
            "lon": [float(row["lon"]) for row in rows],
        }
    )
    table = tmp_path / "schools.parquet"
    schools.write_parquet(table)
    out = tmp_path / "matches.parquet"
    argv = ["alerts", "schools", "--cache-dir", str(tmp_path / "c"), "--date", "2025-01-21"]
    assert main([*argv, "--schools", str(table), "--out", str(out)]) == 0
    message = capsys.readouterr().out
    assert "11 schools checked for 2025-01-21" in message
    assert "0 skipped (time zone unknown)" in message
    matches = pl.read_parquet(out)
    answers = {
        school: sorted(group["coverage"].to_list()) for (school,), group in matches.group_by("id")
    }
    assert answers == {
        "00541083": ["uncertain"] * 3,  # Lake Castle Private School, New Orleans
        "482115002117": ["uncertain"] * 3,  # Lee High School, Baytown
        "482115012492": ["uncertain"] * 3,  # Impact Early College High School, Baytown
        "220028300858": ["covered"] * 3,  # Einstein Charter, on the edge of two warned zones
    }
    manifest = json.loads((tmp_path / "matches.json").read_text())
    assert manifest["sources"]["source"] == "archive"
    days = manifest["sources"]["archive_days"]
    # UTC day files from 21 days before the day before, through the day after.
    first = date(2024, 12, 30)
    assert [day["day"] for day in days] == [str(first + timedelta(n)) for n in range(24)]
    assert all(day["file"]["sha256"] and day["file"]["url"] for day in days)
    assert manifest["sources"]["simplified_tolerance_deg"] == 0.0075
    # Snapshots at midnight after the first day file and at New Year's midnight.
    snapshots = manifest["sources"]["snapshots"]
    assert [s["at"] for s in snapshots] == ["2024-12-31T00:00:00Z", "2025-01-01T00:00:00Z"]
    assert all(s["file"]["sha256"] and s["file"]["url"] for s in snapshots)
    # The New Year snapshot names a warning numbered in 2024: its rows come from a range file.
    carried = manifest["sources"]["carried_events"]
    assert list(carried) == ["BTV.WS.W.0010.2024"]
    assert carried["BTV.WS.W.0010.2024"]["reasons"] == ["numbered in 2024, listed in 2025"]
    [source] = manifest["sources"]["range_files"]
    assert (source["office"], source["code"], source["first"], source["end"]) == (
        "BTV",
        "WS.W",
        "2024-12-01",
        "2025-02-01",
    )


def test_places_outside_every_zone_are_checked_at_a_stand_in(offline: "Kit") -> None:
    """A synthetic point just seaward of the real NCZ204 outline (Hatteras Island)."""
    with offline.cache() as cache:
        index = live_index(cache, offline.cache_dir)
    zones = offline.catalog().boundaries_for("zone", date(2026, 9, 25))
    assert zones is not None
    island = zones.areas["NCZ204"]
    inland = island.representative_point()
    # Walk east from inside the zone until just past its outline.
    offshore = next(
        Point(inland.x + step / 1000, inland.y)
        for step in range(1, 2000)
        if island.distance(Point(inland.x + step / 1000, inland.y)) > 0.002
    )
    footprint = ZoneFootprint(zones)
    lat = np.array([inland.y, offshore.y, offshore.y, np.nan])
    lon = np.array([inland.x, offshore.x, offshore.x + 1.0, np.nan])
    moved = footprint.stand_ins(lat, lon)
    assert moved[0] is None  # inside a zone
    assert moved[2] is None  # a degree out to sea: too far to stand in
    assert moved[3] is None  # no point
    stand_in = moved[1]
    assert stand_in is not None
    assert island.covers(Point(stand_in[1], stand_in[0]))
    assert Point(stand_in[1], stand_in[0]).distance(offshore) < 0.01
    place = pl.DataFrame({"county_fips": [None], "lat": [offshore.y], "lon": [offshore.x]})
    window = LocalWindow(date(2026, 9, 25))
    eastern = [["America/New_York"]]
    assert check_places(index, place, eastern, window).height == 0
    [found] = check_places(index, place, eastern, window, [stand_in]).rows(named=True)
    assert (found["event"], found["coverage"]) == ("Coastal Flood Warning", "uncertain")
    with pytest.raises(ValueError, match="one stand-in"):
        check_places(index, place, eastern, window, [])


def test_cli_check_finds_the_flood_warning_round_2_missed(
    offline: "Kit", capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The round 2 review's command, on real slices: HGX Flood Warning 52, in effect since
    2024-04-29, covered this point in Chambers County, TX, from 02:30 UTC on 2024-05-21."""
    offline.serve_days_without_rows(date(2024, 4, 29), date(2024, 5, 22))
    argv = ["alerts", "check", "--cache-dir", str(tmp_path / "c"), "--county", "48071"]
    assert main([*argv, "--lat", "29.875", "--lon", "-94.755", "--date", "2024-05-21"]) == 0
    captured = capsys.readouterr()
    [line] = captured.out.splitlines()
    record = json.loads(line)
    assert (record["key"], record["event"], record["coverage"], record["basis"]) == (
        "vtec:HGX.FL.W.0052.2024",
        "Flood Warning",
        "covered",
        "polygon",
    )
    assert (record["start"], record["end"]) == ("2024-05-21T02:30:00Z", "2024-05-22T19:03:00Z")
    assert record["zones"] == ["America/Chicago"]
    assert "1 alerts covered the place, 0 uncertain" in captured.err


def _school_rows() -> pl.DataFrame:
    rows = json.loads((FIXTURES / "nces-schools.json").read_text())
    return pl.DataFrame(
        {
            "id": [row["id"] for row in rows],
            "county_fips": [row["county_fips"] for row in rows],
            "lat": [float(row["lat"]) for row in rows],
            "lon": [float(row["lon"]) for row in rows],
        }
    )


@pytest.mark.parametrize("day", [date(2024, 5, 21), date(2025, 1, 1)])
def test_cli_check_and_schools_agree_school_by_school(
    offline: "Kit", tmp_path: Path, capsys: pytest.CaptureFixture[str], day: date
) -> None:
    """Both commands read the archive for the same span, so a school gets one answer.

    The schools are the real NCES rows in ``fixtures/nces-schools.json``.
    """
    offline.serve_days_without_rows(day - timedelta(days=23), day + timedelta(days=1))
    schools = _school_rows()
    table = tmp_path / "schools.parquet"
    schools.write_parquet(table)
    out = tmp_path / "matches.parquet"
    base = ["--cache-dir", str(tmp_path / "c"), "--date", day.isoformat()]
    assert main(["alerts", "schools", *base, "--schools", str(table), "--out", str(out)]) == 0
    capsys.readouterr()
    matches = pl.read_parquet(out)
    unchecked = json.loads(out.with_suffix(".json").read_text())["unchecked_ids"]
    columns = ["key", "coverage", "basis", "precision", "start", "end", "traces", "zones"]
    answered = 0
    for school, fips, lat, lon in schools.iter_rows():
        argv = ["alerts", "check", *base, "--county", fips, "--lat", str(lat), "--lon", str(lon)]
        code = main(argv)
        captured = capsys.readouterr()
        if school in unchecked:
            assert code == 1
            assert "time zone unknown" in captured.err
            continue
        assert code == 0
        from_check = [json.loads(line) for line in captured.out.splitlines()]
        from_schools = [
            {
                **row,
                "start": row["start"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": None if row["end"] is None else row["end"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            for row in matches.filter(pl.col("id") == school).select(columns).iter_rows(named=True)
        ]
        assert [{k: r[k] for k in columns} for r in from_check] == from_schools
        answered += bool(from_schools)
    covered = set(matches.filter(pl.col("coverage") == "covered")["id"].to_list())
    if day == date(2024, 5, 21):
        # Four under river Flood Warnings; Riceville under the ARX Tornado Watch.
        assert covered == {
            "480967004642",
            "01323483",
            "171818002089",
            "481701001472",
            "192415001409",
        }
    else:
        assert covered == {"500039700171"}
    assert answered == len(covered)
