"""Tests for IEM snapshots (events in effect at a time) and range files, on real slices.

``fixtures/iem-snapshot-*.json`` and ``fixtures/iem-range-*.zip`` are slices of
real IEM responses (see ``fixtures/provenance.json``). The malformed inputs
below are synthetic variants of them, one defect each.
"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from snowlight.sources.nws.iem import (
    EVENTS_STATUS_URL,
    WATCHWARN_URL,
    ArchiveFormatError,
    range_url,
    read_day_file,
    read_snapshot,
    snapshot_url,
)
from snowlight.weather.build import make_archive

if TYPE_CHECKING:
    from weather.conftest import Kit

FIXTURES = Path(__file__).parent / "fixtures"
MAY_SNAPSHOT = FIXTURES / "iem-snapshot-2024-04-30T0000Z.json"
NEW_YEAR_SNAPSHOT = FIXTURES / "iem-snapshot-2025-01-01T0000Z.json"
S0 = datetime(2024, 4, 30, tzinfo=UTC)


def test_snapshot_url_names_the_minute_in_utc() -> None:
    at = datetime(2024, 4, 29, 19, 0, 42, tzinfo=UTC).astimezone()
    assert snapshot_url(at) == f"{EVENTS_STATUS_URL}?valid=2024-04-29T19:00Z"


def test_range_url_asks_for_one_office_and_code() -> None:
    url = range_url("HGX", "FL", "W", date(2024, 4, 1), date(2024, 6, 1))
    assert url.startswith(WATCHWARN_URL + "?accept=shapefile&")
    assert "sts=2024-04-01T00:00Z&ets=2024-06-01T00:00Z" in url
    assert "limitps=1&phenomena=FL&significance=W" in url
    assert "location_group=wfo&wfo=HGX" in url
    assert url.endswith("&simple=1&addsvs=1")
    with pytest.raises(ValueError, match="three-letter"):
        range_url("KHGX", "FL", "W", date(2024, 4, 1), date(2024, 6, 1))
    with pytest.raises(ValueError, match="end after it starts"):
        range_url("HGX", "FL", "W", date(2024, 6, 1), date(2024, 6, 1))


def test_reads_a_real_snapshot_one_event_per_key() -> None:
    events = {event.event_key: event for event in read_snapshot(MAY_SNAPSHOT)}
    raw = json.loads(MAY_SNAPSHOT.read_text())["data"]
    assert len(raw) == 9
    assert sorted(events) == [
        "ABQ.FW.A.0025.2024",
        "AFC.FA.A.0002.2024",
        "CYS.HW.W.0021.2024",
        "HGX.FL.W.0052.2024",
        "LCH.FL.W.0035.2024",
        "LCH.FL.W.0055.2024",
        "LCH.FL.W.0063.2024",
        "LSX.FL.W.0047.2024",
    ]
    flood = events["HGX.FL.W.0052.2024"]
    assert (flood.wfo, flood.phenomena, flood.significance, flood.etn, flood.vtec_year) == (
        "HGX",
        "FL",
        "W",
        52,
        2024,
    )
    assert flood.first == datetime(2024, 4, 29, 7, 38, tzinfo=UTC)
    assert flood.last_expire == datetime(2024, 6, 28, 19, 2, tzinfo=UTC)
    assert flood.states == {"TX"}
    # LCH 35's product was issued before the begin time it set: the earlier one counts.
    sabine = events["LCH.FL.W.0035.2024"]
    assert sabine.first == datetime(2024, 4, 10, 14, 14, tzinfo=UTC)
    assert sabine.states == {"TX", "LA"}
    # CYS HW.W 21 is listed twice (EXP and CAN rows): merged into one event.
    wind = events["CYS.HW.W.0021.2024"]
    assert wind.first == datetime(2024, 4, 29, 8, 34, tzinfo=UTC)
    assert wind.last_expire == datetime(2024, 5, 1, tzinfo=UTC)
    assert events["AFC.FA.A.0002.2024"].states == {"AK"}


def test_marine_locations_have_no_state() -> None:
    events = {event.event_key: event for event in read_snapshot(NEW_YEAR_SNAPSHOT)}
    assert events["AFC.SC.Y.1181.2024"].states == frozenset()
    storm = events["BTV.WS.W.0010.2024"]
    assert storm.first == datetime(2024, 12, 31, 20, 31, tzinfo=UTC)
    assert storm.states == {"NY", "VT"}


def _variant(tmp_path: Path, edit: str, value: object) -> Path:
    """A copy of the real May snapshot with one field of its first row replaced."""
    document = json.loads(MAY_SNAPSHOT.read_text())
    if edit == "data":
        document["data"] = value
    else:
        document["data"][0][edit] = value
    path = tmp_path / "variant.json"
    path.write_text(json.dumps(document))
    return path


@pytest.mark.parametrize(
    ("edit", "value", "message"),
    [
        ("data", None, "no data table"),
        ("data", ["row"], "is not an object"),
        ("wfo", None, "wfo is missing"),
        ("eventid", "25", "not a whole number"),
        ("year", True, "not a whole number"),
        ("expire", 20240430, "not a timestamp"),
        ("issue", "30 April", "issue '30 April'"),
    ],
)
def test_malformed_snapshots_are_errors(
    tmp_path: Path, edit: str, value: object, message: str
) -> None:
    with pytest.raises(ArchiveFormatError, match=message):
        read_snapshot(_variant(tmp_path, edit, value))


def test_unreadable_snapshots_are_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_bytes(b"\xff not json")
    with pytest.raises(ArchiveFormatError, match="not JSON"):
        read_snapshot(broken)


def test_missing_times_leave_the_event_open(tmp_path: Path) -> None:
    """Synthetic: IEM gave no begin, product or expiry time for the first row."""
    document = json.loads(MAY_SNAPSHOT.read_text())
    document["data"] = [
        {**document["data"][0], "issue": None, "expire": "", "issue_product_id": None}
    ]
    path = tmp_path / "open.json"
    path.write_text(json.dumps(document))
    [event] = read_snapshot(path)
    assert (event.first, event.last_expire) == (None, None)


def test_archive_caches_snapshots_and_finalises_them(kit: "Kit") -> None:
    kit.clock.now = datetime(2024, 5, 1, tzinfo=UTC)
    with kit.cache() as cache:
        archive = make_archive(cache, kit.cache_dir)
        first = archive.snapshot(S0 + timedelta(seconds=30))
        assert first.at == S0
        assert first.final is False
        assert archive.snapshot(S0) is first
        assert first.file.path == archive.snapshot_path(S0)
        assert first.file.path.name == "2024-04-30T0000Z.json"
        assert [s.at for s in archive.loaded_snapshots()] == [S0]
        with pytest.raises(ValueError, match="in the future"):
            archive.snapshot(datetime(2024, 5, 2, tzinfo=UTC))
        with pytest.raises(ValueError, match="aware"):
            archive.snapshot(datetime(2024, 4, 30))
    kit.clock.now = datetime(2024, 9, 1, tzinfo=UTC)
    with kit.cache() as cache:
        again = make_archive(cache, kit.cache_dir).snapshot(S0)
        assert again.file.downloaded is True  # a provisional copy is asked for again
        assert again.final is True
    kit.clock.now = datetime(2025, 9, 1, tzinfo=UTC)
    with kit.cache() as cache:
        assert make_archive(cache, kit.cache_dir).snapshot(S0).file.downloaded is False
    assert kit.server.hits[snapshot_url(S0)] == 2


def test_archive_caches_range_files(kit: "Kit") -> None:
    spec = ("HGX", "FL", "W", date(2024, 4, 1), date(2024, 6, 1))
    kit.clock.now = datetime(2024, 6, 10, tzinfo=UTC)  # 21 days after the range: not yet
    with kit.cache() as cache:
        archive = make_archive(cache, kit.cache_dir)
        source = archive.range(*spec)
        assert source.final is False
        assert archive.range(*spec) is source
        assert source.label == "range HGX.FL.W 2024-04-01..2024-06-01"
        assert source.file.path == archive.range_path(*spec)
        assert {row.event_key for row in source.rows} == {"HGX.FL.W.0052.2024"}
        sliced = read_day_file(FIXTURES / "iem-range-HGX-FL.W-2024-04-01_2024-06-01.zip")
        assert len(source.rows) == len(sliced) == 13
        with pytest.raises(ValueError, match="not an archived code"):
            archive.range("HGX", "MA", "W", date(2024, 4, 1), date(2024, 6, 1))
        with pytest.raises(ValueError, match="has not started"):
            archive.range("HGX", "FL", "W", date(2024, 7, 1), date(2024, 8, 1))
    kit.clock.now = datetime(2024, 6, 10, 2, tzinfo=UTC)
    with kit.cache() as cache:
        assert make_archive(cache, kit.cache_dir).range(*spec).file.downloaded is True
    kit.clock.now = datetime(2024, 8, 1, tzinfo=UTC)
    with kit.cache() as cache:
        final = make_archive(cache, kit.cache_dir).range(*spec)
        assert final.final is True
    assert kit.server.hits[range_url(*spec)] == 3
