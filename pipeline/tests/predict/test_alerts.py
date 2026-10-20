"""The weather history from IEM rows, the live feed, and their parity."""

import csv
import io
from datetime import UTC, date, datetime, time

import numpy as np
import polars as pl
import pytest

from predict import world
from snowlight.predict.alerts_history import (
    HistoryError,
    HistoryRow,
    Reach,
    days_touched,
    district_day_classes,
    read_season,
    row_classes,
    school_day_classes,
)
from snowlight.predict.alerts_live import (
    Memory,
    UgcIndex,
    alerts_digest,
    live_events,
)
from snowlight.predict.situations import WeatherClass, Window, district_class, school_class
from snowlight.sources.nws.alerts import parse_active

WINDOW = Window(time(18), time(9), 21)
CHICAGO = "America/Chicago"
COLUMNS = (
    "wfo", "utc_issue", "utc_expire", "utc_prodissue", "utc_init_expire", "phenomena", "gtype",
    "significance", "eventid", "status", "ugc", "area2d", "utc_updated", "product_id", "vtec_year",
)  # fmt: skip


def season_csv(rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "wfo": "EAX", "gtype": "C", "ugc": "MOZ028", "area2d": "1000.5", "utc_updated": "",
                "product_id": "x", "vtec_year": "2025", "status": "EXP", "eventid": "1",
                **row,
            }
        )  # fmt: skip
    return out.getvalue()


def row(**fields: str) -> dict[str, str]:
    base = {
        "phenomena": "WS",
        "significance": "W",
        "utc_issue": "2025-01-05 06:00",
        "utc_expire": "2025-01-06 18:00",
        "utc_prodissue": "2025-01-04 20:00",
        "utc_init_expire": "202501061800",
    }
    return base | fields


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_read_season_keeps_class_codes_of_zone_rows_only() -> None:
    text = season_csv(
        [
            row(),
            row(phenomena="FF"),  # flash flood: no class
            row(ugc="MOC095"),  # a county row
            row(ugc="AKZ101"),  # outside the contiguous states
            row(gtype="P", ugc=""),  # a storm polygon
        ]
    )
    rows = read_season(text, 2024)
    assert len(rows) == 1
    found = rows[0]
    assert found.code == "WS.W"
    assert found.event_key == "EAX.WS.W.0001.2025"
    assert found.end == at("2025-01-06T18:00:00")
    with pytest.raises(HistoryError, match="missing columns"):
        read_season("wfo,ugc\nEAX,MOZ028\n", 2024)
    with pytest.raises(HistoryError):
        read_season(season_csv([row(utc_issue="soon")]), 2024)


def test_a_product_issued_after_the_snapshot_is_ignored() -> None:
    # Issued 22:30 local the evening before (04:30 UTC): after the 21:00 snapshot.
    late = read_season(
        season_csv(
            [
                row(
                    utc_prodissue="2025-01-06 04:30",
                    utc_issue="2025-01-06 06:00",
                    utc_init_expire="202501061800",
                )
            ]
        ),
        2024,
    )[0]
    # It covers 00:00 to 12:00 on the 6th, but the 6th's snapshot came before it.
    assert row_classes(late, CHICAGO, WINDOW) == []
    early = read_season(
        season_csv([row(utc_prodissue="2025-01-06 02:30", utc_issue="2025-01-06 06:00")]), 2024
    )[0]
    assert row_classes(early, CHICAGO, WINDOW) == [(date(2025, 1, 6), WeatherClass.SNOW_WARNING)]


def test_the_first_products_window_counts_and_an_early_end_once_known() -> None:
    extended = read_season(
        season_csv(
            [
                row(
                    utc_issue="2025-01-06 06:00",
                    utc_init_expire="202501061200",
                    utc_expire="2025-01-08 18:00",  # extended later: not used
                )
            ]
        ),
        2024,
    )[0]
    assert [day for day, _ in row_classes(extended, CHICAGO, WINDOW)] == [date(2025, 1, 6)]
    cancelled = read_season(
        season_csv(
            [
                row(
                    utc_prodissue="2025-01-04 15:00",
                    utc_issue="2025-01-05 06:00",
                    utc_init_expire="202501080000",
                    utc_expire="2025-01-05 20:00",  # cancelled at 14:00 local on the 5th
                    status="CAN",
                )
            ]
        ),
        2024,
    )[0]
    days = [day for day, _ in row_classes(cancelled, CHICAGO, WINDOW)]
    # Cancelled at 14:00 on the 5th, known by every later snapshot: no day after it counts.
    assert days == []
    assert cancelled.event(at("2025-01-05T12:00:00")).end == at("2025-01-08T00:00:00")
    assert cancelled.event(at("2025-01-06T03:00:00")).end == at("2025-01-05T20:00:00")


def test_tropical_rows_run_until_their_event_ended() -> None:
    text = season_csv(
        [
            row(phenomena="TR", eventid="1009", utc_expire="2025-09-03 18:00", status="CAN"),
            row(
                phenomena="TR",
                eventid="1009",
                ugc="MOZ029",
                utc_expire="2025-09-20 18:00",
                status="CON",
            ),
        ]
    )
    rows = read_season(text, 2025)
    assert all(item.end is None for item in rows)
    assert rows[1].final_end == at("2025-09-03T18:00:00")


def test_days_touched_and_classes() -> None:
    item = HistoryRow(
        2024, "EAX.WW.Y.0002.2025", "MOZ028", 1.0, "WW.Y", at("2025-01-05T12:00:00"),
        at("2025-01-06T00:00:00"), at("2025-01-06T12:00:00"), at("2025-01-06T12:00:00"),
    )  # fmt: skip
    assert days_touched(item, CHICAGO) == [date(2025, 1, 6), date(2025, 1, 7)]
    assert row_classes(item, CHICAGO, WINDOW) == [(date(2025, 1, 6), WeatherClass.ADVISORY)]


def test_school_and_district_classes_by_the_half_rule() -> None:
    reach = Reach(
        members={"MOZ028/a": np.array([0, 1, 2], dtype=np.int64)},
        extra={("MOZ028/a", 2024): np.array([3], dtype=np.int64)},
        key_of={("MOZ028", 1000.5): "MOZ028/a"},
    )
    rows = read_season(season_csv([row(), row(ugc="MOZ999")]), 2024)
    zones = [CHICAGO] * 5
    found = school_day_classes(rows, reach, zones, WINDOW)
    assert found.rows == 2
    assert found.rows_unresolved == 1
    assert sorted(set(found.frame["school"].to_list())) == [0, 1, 2, 3]
    owners = pl.DataFrame({"school": [0, 1, 2, 3, 4], "district": ["a", "a", "b", "b", "b"]})
    districts = district_day_classes(found.frame, owners, 0.5)
    by = {(d, day): w for d, day, w in districts.iter_rows()}
    assert by[("a", date(2025, 1, 6))] == int(WeatherClass.SNOW_WARNING)
    assert by[("b", date(2025, 1, 6))] == int(WeatherClass.SNOW_WARNING)  # 2 of 3 schools
    empty = school_day_classes([], reach, zones, WINDOW)
    assert empty.frame.is_empty()
    assert district_day_classes(empty.frame, owners, 0.5).is_empty()
    assert Reach({}, {}, {}).schools(rows[0]) is None


def test_live_events_skip_ended_cancelled_and_other_codes() -> None:
    feed = parse_active(
        world.feed_bytes(
            [
                world.feature(
                    "/O.NEW.KEAX.WS.W.0004.250106T0600Z-250107T0000Z/",
                    ("MOZ028",),
                    sent="2025-01-05T20:00:00+00:00",
                    onset="2025-01-06T06:00:00+00:00",
                    ends="2025-01-07T00:00:00+00:00",
                ),
                world.feature(
                    "/O.CAN.KEAX.WW.Y.0003.250106T0600Z-250107T0000Z/",
                    ("MOZ028",),
                    sent="2025-01-05T20:00:00+00:00",
                    onset=None,
                    ends=None,
                ),
                world.feature(
                    "/O.NEW.KEAX.FF.W.0005.250106T0600Z-250107T0000Z/",
                    ("MOC095",),
                    sent="2025-01-05T20:00:00+00:00",
                    onset="2025-01-06T06:00:00+00:00",
                    ends=None,
                ),
                world.feature(
                    "/O.NEW.KEAX.WS.W.0006.250106T0600Z-250107T0000Z/",
                    ("MOZ028",),
                    sent="2025-01-05T20:00:00+00:00",
                    onset="2025-01-06T06:00:00+00:00",
                    ends=None,
                    status="Test",
                ),
            ],
            "2025-01-05T20:05:00+00:00",
        )
    )
    events = live_events(feed)
    assert [event.key for event in events] == ["KEAX.WS.W.0004"]
    assert events[0].event.issued == at("2025-01-05T20:00:00")
    digest = alerts_digest(events)
    assert digest == alerts_digest(list(reversed(events)))
    assert digest != alerts_digest([])


def test_parity_one_alert_as_a_row_and_as_a_feature_gives_one_district_class() -> None:
    """The same Winter Storm Warning, from the IEM season file and from the live feed."""
    history = read_season(
        season_csv(
            [
                row(
                    utc_prodissue="2025-01-05 20:00",
                    utc_issue="2025-01-06 06:00",
                    utc_init_expire="202501070000",
                    utc_expire="2025-01-07 00:00",
                )
            ]
        ),
        2024,
    )[0]
    feed = parse_active(
        world.feed_bytes(
            [
                world.feature(
                    "/O.NEW.KEAX.WS.W.0001.250106T0600Z-250107T0000Z/",
                    ("MOZ028",),
                    sent="2025-01-05T20:00:00+00:00",
                    onset="2025-01-06T06:00:00+00:00",
                    ends="2025-01-07T00:00:00+00:00",
                )
            ],
            "2025-01-05T20:05:00+00:00",
        )
    )
    live = live_events(feed)[0]
    for day in (date(2025, 1, 6), date(2025, 1, 7)):
        as_of = WINDOW.snapshot(day, CHICAGO)
        from_history = school_class([history.event(as_of)], day, CHICAGO, WINDOW, as_of)
        from_live = school_class([live.event], day, CHICAGO, WINDOW, as_of)
        assert from_history is from_live
        schools = [from_history, from_history, WeatherClass.NONE]
        assert district_class(schools, 0.5) is district_class(
            [from_live, from_live, WeatherClass.NONE], 0.5
        )
    assert school_class([live.event], date(2025, 1, 6), CHICAGO, WINDOW, at("2025-01-06T03:00:00"))


def test_memory_keeps_an_alert_that_left_the_feed_until_it_was_last_seen() -> None:
    feed = parse_active(
        world.feed_bytes(
            [
                world.feature(
                    "/O.NEW.KEAX.WS.W.0004.250106T0600Z-250107T1200Z/",
                    ("MOZ028",),
                    sent="2025-01-05T20:00:00+00:00",
                    onset="2025-01-06T06:00:00+00:00",
                    ends="2025-01-07T12:00:00+00:00",
                )
            ],
            "2025-01-05T20:05:00+00:00",
        )
    )
    memory = Memory(30)
    seen = memory.update(live_events(feed), at("2025-01-06T07:00:00"))
    assert len(seen) == 1
    kept = Memory.from_json(30, memory.as_json())
    later = kept.update([], at("2025-01-06T08:00:00"))
    assert len(later) == 1
    assert later[0].event.end == at("2025-01-06T07:00:00")
    assert kept.update([], at("2025-01-07T14:00:00")) == []


def test_ugc_index_places_schools_in_zones() -> None:
    lon, lat = world.lon_lat()
    index = UgcIndex.build(lon, lat, world.ugc_areas())
    assert index.reached(["MOZ028"]).tolist() == [0, 1, 2, 3, 4, 7]
    assert index.reached(["KSZ104", "UTZ105"]).tolist() == [5, 6]
    assert index.reached(["XXZ000"]).size == 0
