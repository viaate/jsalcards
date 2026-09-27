"""The IEM school-year files: requests, reading, open tropical rows and caching.

Rows come from ``fixtures/iem-*.csv``, real lines of IEM's answers (see
``fixtures/provenance.json``).
"""

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import pytest

from snowlight.weights import archive

if TYPE_CHECKING:
    from weights.conftest import Kit


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_school_years_and_windows() -> None:
    assert archive.school_years() == list(range(2015, 2026))
    assert archive.school_year_label(2025) == "2025-26"
    assert archive.school_year_label(2099) == "2099-00"
    assert archive.request_window(2024) == (date(2024, 8, 1), date(2025, 6, 17))


def test_year_url_asks_for_every_code_and_state() -> None:
    query = parse_qs(urlsplit(archive.year_url(2024)).query)
    assert query["accept"] == ["csv"]
    assert query["sts"] == ["2024-08-01T00:00Z"]
    assert query["ets"] == ["2025-06-17T00:00Z"]
    pairs = list(
        zip(
            query["phenomena"][0].split(","),
            query["significance"][0].split(","),
            strict=True,
        )
    )
    assert ("WS", "W") in pairs
    assert ("LE", "W") in pairs
    assert ("LE", "Y") in pairs
    assert len(pairs) == 12
    states = query["states"][0].split(",")
    assert "DC" in states
    assert "AK" not in states
    assert len(states) == 49


def test_read_rows_keeps_county_and_zone_rows(kit: "Kit") -> None:
    rows, stats = archive.read_rows(kit.text("iem-2024-2025.csv"))
    assert stats.polygon_rows == 1  # BOX.FF.W.0015.2024's storm-based polygon
    assert stats.kept == len(rows) == stats.rows - 1
    assert stats.ended_before_start == 0
    ri = [row for row in rows if row.event_key == "BOX.WS.W.0001.2025" and row.ugc == "RIZ001"]
    assert len(ri) == 1
    row = ri[0]
    assert row.code == "WS.W"
    assert row.status == "CAN"
    assert row.begin == _utc("2025-01-19T18:00")
    assert row.end == _utc("2025-01-20T11:46")
    assert row.product_issued == _utc("2025-01-19T06:42")
    assert row.product_id == "202501190642-KBOX-WWUS41-WSWBOX"
    assert row.state == "RI"
    assert stats.by_code["WS.W"] >= 8
    assert 0 < stats.longest_row_days < 14


def test_read_rows_skips_other_states(kit: "Kit") -> None:
    rows, stats = archive.read_rows(kit.text("iem-2024-2025.csv"), states={"FL"})
    assert {row.state for row in rows} == {"FL"}
    assert stats.outside_states["RI"] > 0


def test_open_tropical_rows_end_with_their_event(kit: "Kit") -> None:
    rows, stats = archive.read_rows(kit.text("iem-2021-2022.csv"))
    closed = {row.ugc: row for row in stats.closed_tropical}
    assert set(closed) == {"LAZ056", "LAZ059", "LAZ065", "LAZ066", "LAZ067"}
    for row in closed.values():
        assert row.status == "EXA"
        assert row.recorded_end == _utc("2021-09-20T15:28")
        assert row.end == _utc("2021-08-30T21:19")
    kept = {row.ugc: row for row in rows if row.ugc in closed}
    assert all(row.end == _utc("2021-08-30T21:19") for row in kept.values())
    assert stats.longest_row_days < 4  # was 21 days before the open rows were ended


def _header() -> str:
    return ",".join(archive.REQUIRED_COLUMNS)


def _line(**values: str) -> str:
    base = {
        "wfo": "BOX",
        "utc_issue": "2025-01-19 18:00",
        "utc_expire": "2025-01-20 11:46",
        "utc_prodissue": "2025-01-19 06:42",
        "phenomena": "WS",
        "gtype": "C",
        "significance": "W",
        "eventid": "1",
        "status": "CAN",
        "ugc": "RIZ001",
        "product_id": "202501190642-KBOX-WWUS41-WSWBOX",
        "vtec_year": "2025",
    }
    base.update(values)
    return ",".join(base[column] for column in archive.REQUIRED_COLUMNS)


def test_read_rows_rejects_malformed_files() -> None:
    """Synthetic lines built from the real row above, each broken one way."""
    with pytest.raises(archive.ArchiveCsvError, match="missing columns"):
        archive.read_rows("wfo,ugc\nBOX,RIZ001\n")
    bad = [
        (_line(phenomena="TO"), "was not asked for"),
        (_line(utc_issue="yesterday"), "is not YYYY-MM-DD HH:MM"),
        (_line(eventid="one"), "is not a whole number"),
        (_line(ugc="RI001"), "gtype"),
    ]
    for line, message in bad:
        with pytest.raises(archive.ArchiveCsvError, match=message):
            archive.read_rows(f"{_header()}\n{line}\n")


def test_rows_withdrawn_before_they_began_are_kept(kit: "Kit") -> None:
    # BOX.WW.Y.0022.2018 on RIZ001 was upgraded (11:20 AM EST) before its 4 PM start.
    rows, stats = archive.read_rows(kit.text("iem-2018-2019.csv"))
    withdrawn = [row for row in rows if row.end <= row.begin]
    assert [(row.event_key, row.ugc, row.status) for row in withdrawn] == [
        ("BOX.WW.Y.0022.2018", "RIZ001", "UPG")
    ]
    assert withdrawn[0].end == _utc("2018-11-15T16:20")
    assert stats.ended_before_start == 1
    assert stats.kept == stats.rows == len(rows)


def test_open_tropical_row_without_an_ended_row_is_kept() -> None:
    """Synthetic: one open tropical row whose event has no other row."""
    line = _line(phenomena="TR", status="CON", wfo="NHC", eventid="1009")
    rows, stats = archive.read_rows(f"{_header()}\n{line}\n")
    assert len(rows) == 1
    assert stats.closed_tropical[0].end is None


def test_open_tropical_row_ended_before_it_began_is_kept() -> None:
    """Synthetic: an open row that begins after its event's last explicit end."""
    ended = _line(phenomena="TR", status="CAN", wfo="NHC", eventid="9", ugc="RIZ002")
    late = _line(
        phenomena="TR",
        status="EXA",
        wfo="NHC",
        eventid="9",
        utc_issue="2025-01-21 00:00",
        utc_expire="2025-01-30 00:00",
    )
    rows, stats = archive.read_rows(f"{_header()}\n{ended}\n{late}\n")
    assert [row.ugc for row in rows] == ["RIZ002", "RIZ001"]
    assert rows[1].end == _utc("2025-01-20T11:46")  # the event's last explicit end
    assert stats.ended_before_start == 1
    assert stats.closed_tropical[0].end == _utc("2025-01-20T11:46")


def test_load_year_caches_a_final_file(kit: "Kit") -> None:
    cache = kit.cache()
    loaded = archive.load_year(cache, 2024)
    assert loaded.final
    assert loaded.label == "2024-25"
    assert loaded.file.path == archive.year_path(kit.cache_dir, 2024)
    again = archive.load_year(kit.cache(), 2024)
    assert again.rows == loaded.rows
    assert kit.server.hits[archive.year_url(2024)] == 1


def test_load_year_refetches_a_provisional_file(kit: "Kit") -> None:
    kit.now = datetime(2025, 6, 20, tzinfo=UTC)
    first = archive.load_year(kit.cache(), 2024)
    assert not first.final
    kit.now += timedelta(hours=2)
    archive.load_year(kit.cache(), 2024)
    assert kit.server.hits[archive.year_url(2024)] == 2


def test_load_year_refuses_the_future(kit: "Kit") -> None:
    with pytest.raises(ValueError, match="has not started"):
        archive.load_year(kit.cache(), 2027)


def test_load_years(kit: "Kit") -> None:
    files = archive.load_years(kit.cache(), [2018, 2024])
    assert [file.year for file in files] == [2018, 2024]
