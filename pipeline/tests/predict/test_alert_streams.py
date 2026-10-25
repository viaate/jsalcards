"""Past alerts as known at 21:00 from each event's product stream (IEM VTEC event records)."""

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import pytest

from snowlight.predict.alert_streams import (
    EventKey,
    Product,
    StreamError,
    Words,
    district_row_days,
    event_keys,
    expand_ugcs,
    fetch_events,
    label_class_report,
    parse_key,
    parse_record,
    read_cached,
    row_days,
    school_row_days,
    segments,
    words_of,
    zone_state,
    zones_named,
)
from snowlight.predict.alerts_history import HistoryRow, Reach
from snowlight.predict.situations import WeatherClass, Window, school_class
from snowlight.sources.nws.elevation import Band

FIXTURES = Path(__file__).parent / "fixtures"
OKX = EventKey("OKX", "WW", "Y", 2, 2023)
NEW_YORK = ZoneInfo("America/New_York")
SNAPSHOT = datetime(2023, 2, 27, 21, 0, tzinfo=NEW_YORK)
"""21:00 on D-1 for 2023-02-28."""


def okx_products() -> tuple[Product, ...]:
    record = json.loads((FIXTURES / "iem-vtec-okx-ww-y-0002-2023.json").read_text())
    return parse_record(record)


def test_ugc_lines_expand_ranges_and_carry_the_state() -> None:
    found = expand_ugcs("CTZ005>008-NJZ002-004-103>105-\n107-NYZ068>071-270415-")
    assert found == frozenset(
        {"CTZ005", "CTZ006", "CTZ007", "CTZ008", "NJZ002", "NJZ004", "NJZ103", "NJZ104",
         "NJZ105", "NJZ107", "NYZ068", "NYZ069", "NYZ070", "NYZ071"}
    )  # fmt: skip
    with pytest.raises(StreamError):
        expand_ugcs("004-270415-")


def test_segments_keep_zones_vtec_headlines_and_description() -> None:
    text = (
        "WWUS41 KOKX 272039\nWSWOKX\n\nURGENT - WINTER WEATHER MESSAGE\n\n"
        "NJZ006-104>108-\n281015-\n/O.CON.KOKX.WW.Y.0002.230227T2300Z-230228T1800Z/\n"
        "Hudson-Eastern Bergen-\n339 PM EST Mon Feb 27 2023\n\n"
        "...WINTER WEATHER ADVISORY REMAINS IN EFFECT UNTIL 1 PM EST\nTUESDAY...\n\n"
        "* WHAT...Snow and sleet expected.\n\n* WHERE...Hudson County.\n\n"
        "PRECAUTIONARY/PREPAREDNESS ACTIONS...\n\nSlow down.\n\n&&\n\n$$\n"
    )
    (only,) = segments(text)
    assert only.ugcs == frozenset({"NJZ006", "NJZ104", "NJZ105", "NJZ106", "NJZ107", "NJZ108"})
    assert [v.action for v in only.vtecs] == ["CON"]
    assert only.headlines == ("WINTER WEATHER ADVISORY REMAINS IN EFFECT UNTIL 1 PM EST TUESDAY",)
    assert "Snow and sleet" in only.description
    assert "Slow down" not in only.description


def test_okx_advisory_at_21_is_the_latest_product_before_it() -> None:
    products = okx_products()
    assert len(products) == 6
    assert "NYZ078" in zones_named(OKX, products)
    state = zone_state(OKX, products, "NYZ078", SNAPSHOT)
    assert state is not None
    # The season file's first end said 10 AM; at 21:00 the latest product (3:39 PM) said 1 PM.
    assert state.end == datetime(2023, 2, 28, 18, 0, tzinfo=UTC)
    assert state.start == datetime(2023, 2, 27, 23, 0, tzinfo=UTC)
    assert state.action == "CON"
    assert not state.withdrawn
    assert state.words.snow
    assert not state.words.sleet
    assert not state.words.mix
    assert not state.words.rain
    # A product after 21:00 moved the end back to 10 AM and named sleet: not known at 21:00.
    later = zone_state(OKX, products, "NYZ078", datetime(2023, 2, 28, 9, 0, tzinfo=UTC))
    assert later is not None
    assert later.end == datetime(2023, 2, 28, 15, 0, tzinfo=UTC)
    assert later.words.sleet


def test_upgraded_zones_are_withdrawn_from_the_upgrade_on() -> None:
    products = okx_products()
    before = zone_state(OKX, products, "CTZ009", datetime(2023, 2, 27, 0, 30, tzinfo=UTC))
    assert before is not None
    assert not before.withdrawn
    assert before.event() is not None
    after = zone_state(OKX, products, "CTZ009", SNAPSHOT)
    assert after is not None
    assert after.withdrawn
    assert after.action == "UPG"
    assert after.event() is None


def test_a_zone_no_product_names_by_then_has_no_state() -> None:
    products = okx_products()
    assert zone_state(OKX, products, "NYZ078", datetime(2023, 2, 26, 20, 0, tzinfo=UTC)) is None
    assert zone_state(OKX, products, "TXZ001", SNAPSHOT) is None


def test_dropping_products_after_the_snapshot_changes_nothing_at_it() -> None:
    """Sentinel (plan T2): the state at 21:00 is the same with every later product removed."""
    products = okx_products()
    early = tuple(p for p in products if p.issued <= SNAPSHOT)
    for ugc in sorted(zones_named(OKX, products)):
        assert zone_state(OKX, products, ugc, SNAPSHOT) == zone_state(OKX, early, ugc, SNAPSHOT)


def test_an_unset_begin_reads_as_the_product_time_and_began_keeps_the_stated_one() -> None:
    record = {
        "report": {
            "valid": "2024-01-15T20:00:00Z",
            "product_id": "a",
            "text": "XXZ001-160900-\n/O.NEW.KABC.WS.W.0001.240116T0300Z-240116T1800Z/\n"
            "...WINTER STORM WARNING IN EFFECT...\n* WHAT...Heavy snow.\n$$",
        },
        "svs": [
            {
                "valid": "2024-01-16T01:00:00Z",
                "product_id": "b",
                "text": "XXZ001-160900-\n/O.EXT.KABC.WS.W.0001.000000T0000Z-240116T2100Z/\n"
                "...WINTER STORM WARNING NOW IN EFFECT...\n* WHAT...Snow, mixing with "
                "freezing rain.\n$$",
            }
        ],
    }
    key = EventKey("ABC", "WS", "W", 1, 2024)
    state = zone_state(key, parse_record(record), "XXZ001", datetime(2024, 1, 16, 2, tzinfo=UTC))
    assert state is not None
    assert state.start == datetime(2024, 1, 16, 1, 0, tzinfo=UTC)
    assert state.began == datetime(2024, 1, 16, 3, 0, tzinfo=UTC)
    assert state.end == datetime(2024, 1, 16, 21, 0, tzinfo=UTC)
    assert state.words.freezing_rain
    assert state.words.snow
    assert state.first_issued == datetime(2024, 1, 15, 20, 0, tzinfo=UTC)


def test_type_words() -> None:
    assert words_of("Mixed precipitation expected.").mix
    assert words_of("Rain changing to snow overnight.").mix
    assert words_of("rain and snow").mix
    found = words_of("Light freezing rain and freezing drizzle, a light glaze of ice.")
    assert found.freezing_rain
    assert found.freezing_drizzle
    assert found.ice
    assert not found.rain
    assert words_of("Snow showers.") == Words(snow=True)
    assert set(Words().as_json()) == {
        "snow", "sleet", "freezing_rain", "freezing_drizzle", "rain", "mix", "ice",
    }  # fmt: skip


def test_elevation_lines_come_from_the_latest_segment() -> None:
    record = {
        "report": {
            "valid": "2026-10-20T19:51:00Z",
            "product_id": "a",
            "text": "CAZ323-210400-\n/O.NEW.KHNX.WW.Y.0005.261021T1800Z-261022T1800Z/\n"
            "...WINTER WEATHER ADVISORY IN EFFECT ABOVE 8,000 FEET FROM 11 AM\nWEDNESDAY TO "
            "11 AM PDT THURSDAY...\n\n* WHAT...Snow.\n\n* WHERE...Yosemite NP outside of the "
            "valley.\n$$",
        }
    }
    key = EventKey("HNX", "WW", "Y", 5, 2026)
    state = zone_state(key, parse_record(record), "CAZ323", datetime(2026, 10, 21, 4, tzinfo=UTC))
    assert state is not None
    assert state.elevation is not None
    assert state.elevation.bands == (Band(8000, None),)


def test_event_keys_take_rows_a_snapshot_can_know_of() -> None:
    def row(issued: str, start: str, end: str, key: str = "OKX.WW.Y.0002.2023") -> HistoryRow:
        def at(text: str) -> datetime:
            return datetime.fromisoformat(text).replace(tzinfo=UTC)

        return HistoryRow(2022, key, "NYZ078", 1.0, "WW.Y", at(issued), at(start), at(end), at(end))

    day = date(2023, 2, 28)
    rows = [
        row("2023-02-27T20:39", "2023-02-27T23:00", "2023-02-28T18:00"),
        # Issued after 06:00 UTC on D: no snapshot of D knows it.
        row("2023-02-28T08:43", "2023-02-28T09:00", "2023-02-28T18:00", "OKX.WW.Y.0003.2023"),
        # Ended before the window.
        row("2023-02-26T20:00", "2023-02-26T23:00", "2023-02-27T12:00", "OKX.WW.Y.0004.2023"),
        # Its recorded start moved a day later: kept (the superset).
        row("2023-02-27T20:00", "2023-03-01T12:00", "2023-03-01T18:00", "OKX.WS.W.0001.2023"),
    ]
    # The event whose recorded span meets the window comes first.
    assert event_keys(rows, [day]) == [OKX, parse_key("OKX.WS.W.0001.2023")]
    with pytest.raises(StreamError):
        parse_key("OKX.WW.Y")


def test_fetch_one_a_second_with_a_cap(tmp_path: Path) -> None:
    keys = [EventKey("OKX", "WW", "Y", n, 2023) for n in (1, 2, 3, 4)]
    keys[0].path(tmp_path).parent.mkdir(parents=True)
    keys[0].path(tmp_path).write_text("{}")
    asked: list[dict[str, str]] = []
    pauses: list[float] = []

    def get(query: Mapping[str, str]) -> bytes:
        asked.append(dict(query))
        return b'{"event_exists": false}' + b" " * 70

    # The cached record's 2 bytes count toward the cap: 2 + 93 + 93 = 188 <= 200; the room
    # left (12) is then less than the largest record seen (93), so nothing more is asked.
    found = fetch_events(keys, tmp_path, get, cap=200, sleep=pauses.append)
    assert found.cached == 1
    assert found.requested == 2
    assert found.bytes_fetched == 2 * 93
    assert found.bytes_cached == 188  # within the cap of 200
    assert found.bytes_dropped == 0
    assert found.stopped_at_cap
    assert found.missing == (keys[3],)
    assert pauses == [1.0]
    assert asked[0] == {
        "wfo": "OKX",
        "year": "2023",
        "phenomena": "WW",
        "significance": "Y",
        "etn": "2",
    }
    assert read_cached(keys[1], tmp_path) == ()
    assert read_cached(keys[3], tmp_path) is None
    # A later fetch counts what the earlier ones kept: still at the cap, it fetches nothing.
    again = fetch_events(keys, tmp_path, get, cap=200, sleep=pauses.append)
    assert again.requested == 0
    assert again.stopped_at_cap
    assert again.missing == (keys[3],)


def test_a_record_that_would_pass_the_cap_is_dropped_not_cached(tmp_path: Path) -> None:
    keys = [EventKey("OKX", "WW", "Y", n, 2023) for n in (1, 2, 3)]
    bodies = iter([b"{}" + b" " * 48, b"{}" + b" " * 148, b"{}"])

    def get(_query: Mapping[str, str]) -> bytes:
        return next(bodies)

    # 50 bytes kept; the room left (150) holds a record as large as any seen, so the next is
    # asked for; it is 150 bytes, and 50 + 150 would pass the cap of 199: dropped, and the end.
    found = fetch_events(keys, tmp_path, get, cap=199, sleep=lambda _s: None)
    assert found.requested == 2
    assert found.bytes_fetched == 200
    assert found.bytes_dropped == 150
    assert found.bytes_cached == 50  # within the cap of 199
    assert found.stopped_at_cap
    assert found.missing == (keys[1], keys[2])
    assert read_cached(keys[1], tmp_path) is None
    assert not keys[1].path(tmp_path).with_suffix(".part").exists()
    # Exactly at the cap is within it.
    for key in keys:
        key.path(tmp_path).unlink(missing_ok=True)
    bodies = iter([b"{}" + b" " * 48, b"{}" + b" " * 148, b"{}"])
    exact = fetch_events(keys, tmp_path, get, cap=200, sleep=lambda _s: None)
    assert (exact.bytes_cached, exact.bytes_dropped, exact.missing) == (200, 0, (keys[2],))


def test_a_failed_request_is_missing_not_cached(tmp_path: Path) -> None:
    def get(_query: Mapping[str, str]) -> bytes:
        raise OSError("down")

    found = fetch_events([OKX], tmp_path, get, sleep=lambda _s: None)
    assert found.missing == (OKX,)
    assert found.errors
    assert not OKX.path(tmp_path).exists()


def test_the_snapshot_window_is_local() -> None:
    assert SNAPSHOT.astimezone(UTC) == datetime(2023, 2, 28, 2, 0, tzinfo=UTC)
    assert SNAPSHOT + timedelta(hours=12) == datetime(2023, 2, 28, 9, 0, tzinfo=NEW_YORK)


# --- classes as of the snapshot -------------------------------------------------------------------

WINDOW = Window(time(18, 0), time(9, 0), 21)
CHICAGO = "America/Chicago"
KEY = EventKey("ABC", "WW", "Y", 7, 2025)
DAY = date(2025, 1, 6)
"""Snapshot 21:00 CST on Jan 5 (03:00 UTC Jan 6); window 18:00 Jan 5 to 09:00 Jan 6 (15:00 UTC)."""


def product(valid: str, action: str, begin: str, end: str, words: str = "Snow.") -> dict[str, str]:
    return {
        "valid": valid,
        "product_id": valid,
        "text": f"KSZ001-061500-\n/O.{action}.KABC.WW.Y.0007.{begin}-{end}/\n"
        f"...WINTER WEATHER ADVISORY...\n* WHAT...{words}\n$$",
    }


def stream_row(start: str, end: str, issued: str = "2025-01-05T20:00") -> HistoryRow:
    def at(text: str) -> datetime:
        return datetime.fromisoformat(text).replace(tzinfo=UTC)

    return HistoryRow(2024, "ABC.WW.Y.0007.2025", "KSZ001", 1.0, "WW.Y", at(issued), at(start),
                      at(end), at(end))  # fmt: skip


def test_a_start_a_later_product_moved_past_9_am_is_counted_and_the_stream_keeps_the_day() -> None:
    record = {
        "report": product("2025-01-05T20:00:00Z", "NEW", "250106T0600Z", "250106T1800Z"),
        # After the snapshot: the start moved to 10 AM CST, past the window.
        "svs": [product("2025-01-06T09:00:00Z", "EXT", "250106T1600Z", "250106T2300Z")],
    }
    streams = {KEY: parse_record(record)}
    # The season file keeps the moved start: the history sees nothing in the window.
    row = stream_row("2025-01-06T16:00", "2025-01-06T23:00")
    (found,) = row_days(row, CHICAGO, WINDOW, streams, [DAY])
    assert found.history is WeatherClass.NONE
    assert found.stream is WeatherClass.ADVISORY
    assert found.start_move == "later"
    assert found.state is not None
    assert found.state.start == datetime(2025, 1, 6, 6, 0, tzinfo=UTC)
    # Without the stream the history's class stands on both sides.
    assert row_days(row, CHICAGO, WINDOW, {}, [DAY]) == []


def test_a_start_moved_earlier_after_the_snapshot_is_counted_too() -> None:
    record = {
        "report": product("2025-01-05T20:00:00Z", "NEW", "250106T1600Z", "250106T2300Z"),
        "svs": [product("2025-01-06T05:00:00Z", "EXT", "250106T0600Z", "250106T2300Z")],
    }
    row = stream_row("2025-01-06T06:00", "2025-01-06T23:00")
    (found,) = row_days(row, CHICAGO, WINDOW, {KEY: parse_record(record)}, [DAY])
    assert (found.history, found.stream, found.start_move) == (
        WeatherClass.ADVISORY, WeatherClass.NONE, "earlier",
    )  # fmt: skip


def test_a_cancel_before_the_snapshot_withdraws_the_zone() -> None:
    record = {
        "report": product("2025-01-05T15:00:00Z", "NEW", "250106T0600Z", "250106T1800Z"),
        "svs": [product("2025-01-05T22:00:00Z", "CAN", "000000T0000Z", "250106T1800Z")],
    }
    row = stream_row("2025-01-06T06:00", "2025-01-06T18:00", issued="2025-01-05T15:00")
    (found,) = row_days(row, CHICAGO, WINDOW, {KEY: parse_record(record)}, [DAY])
    assert found.stream is WeatherClass.NONE
    assert found.state is not None
    assert found.state.withdrawn


def test_district_days_and_the_label_report() -> None:
    record = {
        "report": product(
            "2025-01-05T20:00:00Z",
            "NEW",
            "250106T0600Z",
            "250106T1800Z",
            "Snow and sleet, mixed precipitation.",
        ),
        "svs": [product("2025-01-06T09:00:00Z", "EXT", "250106T1600Z", "250106T2300Z")],
    }
    row = stream_row("2025-01-06T16:00", "2025-01-06T23:00")
    reach = Reach(members={"p": np.array([0, 1, 2])}, extra={}, key_of={("KSZ001", 1.0): "p"})
    frame = school_row_days([row], reach, [CHICAGO, CHICAGO, CHICAGO], WINDOW,
                            {KEY: parse_record(record)}, [DAY])  # fmt: skip
    assert frame.height == 3
    assert set(frame["w_sleet"].to_list()) == {True}
    districts = district_row_days(
        frame, pl.DataFrame({"school": [0, 1, 2, 3], "district": ["d1", "d1", "d2", "d3"]}), 0.5
    )
    by = {r["district"]: r for r in districts.iter_rows(named=True)}
    assert by["d1"]["stream"] == int(WeatherClass.ADVISORY)
    assert by["d1"]["history"] == 0
    assert by["d1"]["moved_later"] == 2
    assert by["d1"]["w_mix"] is True
    assert by["d1"]["schools"] == 2
    labels = pl.DataFrame(
        {
            "district": ["d1", "d2", "d4"],
            "day": [DAY] * 3,
            "season": [2024] * 3,
            "outcome": ["no_school", "open", "unknown"],
            "weather": [0, 0, 0],
        }
    )
    weather = pl.DataFrame(schema={"district": pl.String, "day": pl.Date, "weather": pl.Int8})
    report = label_class_report(labels, weather, districts, frame, [DAY])
    summary = report["summary"]
    assert isinstance(summary, dict)
    assert summary["label_rows"] == 2
    assert summary["history_vs_label_class_mismatch"] == 0
    assert summary["labels_changed"] == 2
    assert summary["zone_days_start_moved_later"] == 1
    assert summary["labels_with_a_later_move"] == 2
    assert summary["labels_with_an_event_not_fetched"] == 0
    # The same row with no stream keeps the history's class on both sides, and says so.
    alone = school_row_days([stream_row("2025-01-06T06:00", "2025-01-06T18:00")], reach,
                            [CHICAGO] * 3, WINDOW, {}, [DAY])  # fmt: skip
    assert set(alone["streamed"].to_list()) == {False}
    assert set(alone["stream"].to_list()) == set(alone["history"].to_list()) == {1}
    assert report["pairs"] == {"none->advisory": 2}


def test_a_text_line_that_starts_like_a_ugc_line_is_not_one() -> None:
    text = (
        "...HEAVY SNOW...\nINZ076 AND NEARBY: LOCALLY HIGHER AMOUNTS POSSIBLE.\n"
        "INZ073>076-061500-\n/O.NEW.KIND.WW.Y.0003.250106T0600Z-250106T1800Z/\n* WHAT...Snow.\n$$"
    )
    (only,) = segments(text)
    assert only.ugcs == frozenset({"INZ073", "INZ074", "INZ075", "INZ076"})
    assert segments("no zones here\n$$") == ()


def test_parity_with_the_live_path_on_the_wawona_advisories() -> None:
    """Plan T2 parity (P7, Wawona 2026-10-22): at 21:00 PDT on Oct 21 the streams give the zones
    the start, end and elevation band the live path built from the same NWS alerts."""
    from snowlight.predict.alerts_live import live_events  # noqa: PLC0415
    from snowlight.sources.nws.alerts import parse_active  # noqa: PLC0415

    feed = parse_active((FIXTURES / "nws-2026-10-22-advisories.json").read_bytes())
    # The live fixture holds the first products and the morning updates, not HNX's 1:44 PM
    # update of Oct 21: at noon both paths have the same products.
    as_of = datetime(2026, 10, 21, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    snapshot = datetime(2026, 10, 21, 21, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    live = {
        (event.key, ugc): event
        for event in live_events(feed)
        if event.event.issued <= as_of
        for ugc in event.ugcs
    }
    cases = (
        (EventKey("HNX", "WW", "Y", 5, 2026), "iem-vtec-hnx-ww-y-0005-2026.json", "CAZ323"),
        (EventKey("REV", "WW", "Y", 9, 2026), "iem-vtec-rev-ww-y-0009-2026.json", "CAZ073"),
    )
    for key, name, ugc in cases:
        products = parse_record(json.loads((FIXTURES / name).read_text()))
        state = zone_state(key, products, ugc, as_of)
        assert state is not None
        built = live[(f"K{key.wfo}.{key.code}.{key.etn:04d}", ugc)]
        assert state.event() == built.event
        assert state.elevation == built.elevation
        assert state.elevation is not None
        assert state.elevation.bands == (Band(8000, None),)
        # At 21:00 the update (no begin: already in effect) keeps the end and the band, and
        # both paths give the zone the advisory class for Oct 22.
        later = zone_state(key, products, ugc, snapshot)
        assert later is not None
        assert later.end == built.event.end
        assert later.elevation == built.elevation
        day = date(2026, 10, 22)
        zone = "America/Los_Angeles"
        assert school_class([later.event()], day, zone, WINDOW, snapshot) is WeatherClass.ADVISORY  # type: ignore[list-item]
        assert school_class([built.event], day, zone, WINDOW, snapshot) is WeatherClass.ADVISORY
