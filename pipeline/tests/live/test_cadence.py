"""The live cadence (spec 7.3, T14) on SYNTHETIC stations and alerts."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from snowlight.live.cadence import (
    ALERT_KEEP,
    BLOCKED_FOR,
    AlertWatch,
    Cadence,
    alert_counties,
    county_zones,
    in_window,
    station_zones,
)
from snowlight.live.ledger import Outcome
from snowlight.sources.stations.registry import Station

CHICAGO = "America/Chicago"
NEW_YORK = "America/New_York"
LOS_ANGELES = "America/Los_Angeles"
ZONES = {"20091": CHICAGO, "20045": CHICAGO, "36061": NEW_YORK, "06037": LOS_ANGELES}


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def station(
    source_id: str = "synthetic-ks", fips: tuple[str, ...] = ("20091",), poll: int | None = None
) -> Station:
    body = {
        "id": source_id,
        "platform": "synthetic",
        "call_sign": "SYNT",
        "name": "SYNTHETIC station",
        "market": "SYNTHETIC market",
        "dma": None,
        "states": ["KS"],
        "counties": {"basis": "dma", "source": "SYNTHETIC", "fips": list(fips)},
        "page_url": "https://example.invalid/closings",
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": poll,
        "status": "active",
        "evidence": "SYNTHETIC",
    }
    return Station.model_validate_json(json.dumps(body))


def poll_minutes(source: Station) -> int:
    return source.poll_minutes or 10


def cadence(
    *stations: Station, alerts: AlertWatch | None = None, path: Path | None = None
) -> Cadence:
    found = stations or (station(),)
    return Cadence({s.id: s for s in found}, ZONES, poll_minutes, path=path, alerts=alerts)


def feed(*alerts: dict[str, object]) -> bytes:
    """A SYNTHETIC /alerts/active body."""
    features = []
    for alert in alerts:
        props = {
            "status": "Actual",
            "messageType": "Alert",
            "event": "Winter Storm Warning",
            "expires": "2026-11-17T18:00:00+00:00",
            "ends": None,
            "geocode": {"SAME": ["020091"], "UGC": ["KSZ001"]},
            **alert,
        }
        features.append({"type": "Feature", "properties": props})
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


@pytest.mark.parametrize(
    ("local", "inside"),
    [
        ("17:59", False),
        ("18:00", True),
        ("22:59", True),
        ("23:00", False),
        ("03:59", False),
        ("04:00", True),
        ("08:59", True),
        ("09:00", False),
        ("12:00", False),
    ],
)
def test_t14_window_edges(local: str, inside: bool) -> None:
    # 2026-11-16 is CST (UTC-6).
    hour, minute = (int(part) for part in local.split(":"))
    moment = datetime(2026, 11, 16, hour, minute, tzinfo=UTC) + timedelta(hours=6)
    assert in_window(CHICAGO, moment) is inside


def test_t14_windows_follow_the_end_of_daylight_time_in_chicago() -> None:
    # Sat 2026-10-31 is CDT (UTC-5): 09:30Z is 04:30, inside the morning window.
    assert in_window(CHICAGO, at("2026-10-31 09:30"))
    # Sun 2026-11-01 01:00 CDT falls back to 01:00 CST: 09:30Z is 03:30 CST, outside.
    assert not in_window(CHICAGO, at("2026-11-01 09:30"))
    assert in_window(CHICAGO, at("2026-11-01 10:00"))  # 04:00 CST
    assert in_window(CHICAGO, at("2026-11-01 14:59"))  # 08:59 CST
    assert not in_window(CHICAGO, at("2026-11-01 15:00"))
    clock = cadence()
    source = clock.stations["synthetic-ks"]
    assert clock.interval(source, at("2026-11-01 09:30")) == timedelta(minutes=30)
    assert clock.interval(source, at("2026-11-01 10:00")) == timedelta(minutes=5)


def test_t14_cadence_in_and_out_of_windows() -> None:
    clock = cadence(station(poll=45))
    source = clock.stations["synthetic-ks"]
    assert clock.interval(source, at("2026-11-16 12:00")) == timedelta(minutes=5)  # 06:00 CST
    assert clock.interval(source, at("2026-11-16 18:00")) == timedelta(minutes=45)  # noon
    quiet = cadence(station(poll=15))
    assert quiet.interval(quiet.stations["synthetic-ks"], at("2026-11-16 18:00")) == timedelta(
        minutes=30
    )


def test_t14_an_alert_boosts_a_station_outside_its_windows() -> None:
    watch = AlertWatch(lambda: feed({}))
    clock = cadence(station(), station("synthetic-ny", ("36061",)), alerts=watch)
    noon = at("2026-11-16 18:00")
    due = clock.due(noon, ["synthetic-ks", "synthetic-ny"])
    assert [s.id for s in due] == ["synthetic-ks", "synthetic-ny"]  # never read: due
    assert clock.alerted == frozenset({"20091"})
    assert clock.interval(clock.stations["synthetic-ks"], noon) == timedelta(minutes=5)
    assert clock.interval(clock.stations["synthetic-ny"], noon) == timedelta(minutes=30)


def test_t14_alert_feed_down_keeps_the_last_set_two_hours() -> None:
    answers: list[bytes | Exception] = [feed({}), OSError("down")]

    def read() -> bytes:
        answer = answers[0] if len(answers) == 1 else answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    watch = AlertWatch(read)
    start = at("2026-11-16 17:00")
    assert watch.counties(start) == frozenset({"20091"})
    assert watch.counties(start + timedelta(minutes=2)) == frozenset({"20091"})  # not re-read
    assert watch.counties(start + timedelta(minutes=5)) == frozenset({"20091"})  # failed: kept
    assert watch.counties(start + ALERT_KEEP) == frozenset({"20091"})
    assert watch.counties(start + ALERT_KEEP + timedelta(minutes=5)) == frozenset()
    assert watch.last_good == start


def test_only_actual_current_allowlisted_alerts_count() -> None:
    now = at("2026-11-16 12:00")
    body = feed(
        {"geocode": {"SAME": ["020045"]}},
        {"status": "Test", "geocode": {"SAME": ["006037"]}},
        {"messageType": "Cancel", "geocode": {"SAME": ["006037"]}},
        {"event": "Small Craft Advisory", "geocode": {"SAME": ["006037"]}},
        {"expires": "2026-11-16T11:00:00+00:00", "geocode": {"SAME": ["006037"]}},
        {"ends": "2026-11-16T11:59:00+00:00", "geocode": {"SAME": ["006037"]}},
        {"geocode": {"SAME": ["bad", "1234567"]}},
        {"expires": "not a time", "geocode": {"SAME": ["036061"]}},
    )
    assert alert_counties(body, now) == frozenset({"20045", "36061"})
    with pytest.raises(ValueError, match="alerts"):
        alert_counties(b"[]", now)


def test_due_after_reads_failures_deferrals_and_blocks() -> None:
    clock = cadence()
    source = clock.stations["synthetic-ks"]
    morning = at("2026-11-16 12:00")  # 06:00 CST: 5-minute cadence
    clock.record(morning, [("synthetic-ks", Outcome.OK, None)])
    assert not clock.is_due(source, morning + timedelta(minutes=3))
    assert clock.is_due(source, morning + timedelta(minutes=5))
    noon = at("2026-11-16 18:00")  # 30-minute cadence
    clock.record(noon, [("synthetic-ks", Outcome.NOT_MODIFIED, None)])
    assert not clock.is_due(source, noon + timedelta(minutes=25))
    assert clock.is_due(source, noon + timedelta(minutes=30))
    clock.record(noon, [("synthetic-ks", Outcome.LATE, None)])
    assert clock.is_due(source, noon + timedelta(minutes=5))
    clock.record(noon, [("synthetic-ks", Outcome.DEFERRED, 290.0)])
    assert not clock.is_due(source, noon + timedelta(seconds=289))
    assert clock.is_due(source, noon + timedelta(seconds=290))
    clock.record(noon, [("synthetic-ks", Outcome.BLOCKED, None)])
    assert not clock.is_due(source, noon + BLOCKED_FOR - timedelta(minutes=1))
    assert clock.recently_due(noon) == frozenset({"synthetic-ks"})
    assert clock.is_due(source, noon + BLOCKED_FOR)


def test_recently_due_covers_the_last_fifteen_minutes() -> None:
    clock = cadence(station(), station("synthetic-two", ("20045",)))
    first = at("2026-11-16 12:00")
    clock.due(first, ["synthetic-ks"])
    clock.due(first + timedelta(minutes=5), ["synthetic-two", "synthetic-gone"])
    assert clock.recently_due(first + timedelta(minutes=10)) == frozenset(
        {"synthetic-ks", "synthetic-two"}
    )
    assert clock.recently_due(first + timedelta(minutes=16)) == frozenset({"synthetic-two"})


def test_station_zone_is_the_majority_and_a_tie_keeps_both() -> None:
    assert station_zones(station(fips=("20045", "20091", "36061")), ZONES) == (CHICAGO,)
    tied = station(fips=("20091", "36061"))
    assert station_zones(tied, ZONES) == (CHICAGO, NEW_YORK)
    assert station_zones(station(fips=("99999",)), ZONES) == ()
    clock = cadence(tied)
    # 09:30Z: 04:30 in New York (window), 03:30 in Chicago: the earliest open window counts.
    assert clock.boosted(tied, at("2026-11-16 09:30"))
    unknown = station("synthetic-unknown", ("99999",))
    assert cadence(unknown).boosted(unknown, at("2026-11-16 18:00"))
    assert clock.boosted(unknown, at("2026-11-16 18:00"))  # a station it was not given


def test_county_zones_take_the_zone_most_schools_are_in() -> None:
    pairs = [
        ("20091", CHICAGO),
        ("20091", CHICAGO),
        ("20091", NEW_YORK),
        ("36061", NEW_YORK),
        (None, CHICAGO),
        ("20045", None),
        ("06037", LOS_ANGELES),
        ("06037", "America/Denver"),
    ]
    assert county_zones(pairs) == {
        "20091": CHICAGO,
        "36061": NEW_YORK,
        "06037": "America/Denver",
    }


def test_clocks_are_kept_across_runs(tmp_path: Path) -> None:
    path = tmp_path / "cadence.json"
    clock = cadence(path=path)
    noon = at("2026-11-16 18:00")
    clock.record(
        noon, [("synthetic-ks", Outcome.DEFERRED, 60.0), ("synthetic-x", Outcome.OK, None)]
    )
    clock.save()
    again = cadence(path=path)
    assert again.clocks == clock.clocks
    cadence().save()  # no path: nothing written
    path.write_text("{oops", encoding="utf-8")
    assert cadence(path=path).clocks == {}
    path.write_text(json.dumps({"version": 7}), encoding="utf-8")
    assert cadence(path=path).clocks == {}
    path.write_text(
        json.dumps({"version": 1, "sources": {"a": {"outcome": "ok"}, "b": 3}}), encoding="utf-8"
    )
    assert cadence(path=path).clocks == {}
    assert cadence(path=tmp_path / "missing.json").clocks == {}


@pytest.mark.parametrize("outcome", [Outcome.ERROR, Outcome.PARTIAL])
def test_t14_a_failed_read_keeps_its_cadence(outcome: Outcome) -> None:
    """A 429 or 5xx without Retry-After, or a list judged stale on a good answer, is read
    again at the next pass only in a window or an alert; outside, at its calm interval."""
    clock = cadence()
    source = clock.stations["synthetic-ks"]
    noon = at("2026-11-16 18:00")  # 12:00 CST: 30-minute cadence
    clock.record(noon, [("synthetic-ks", outcome, None)])
    assert not clock.is_due(source, noon + timedelta(minutes=5))
    assert not clock.is_due(source, noon + timedelta(minutes=25))
    assert clock.is_due(source, noon + timedelta(minutes=30))
    morning = at("2026-11-16 12:00")  # 06:00 CST, in a window: every pass
    clock.record(morning, [("synthetic-ks", outcome, None)])
    assert clock.is_due(source, morning + timedelta(minutes=5))


def test_t14_no_source_is_read_again_inside_its_slot_or_minutes_later() -> None:
    clock = cadence()
    source = clock.stations["synthetic-ks"]
    grid = at("2026-11-16 12:00")  # 06:00 CST, in a window: 5-minute cadence
    clock.record(grid + timedelta(seconds=30), [("synthetic-ks", Outcome.OK, None)])
    assert not clock.is_due(source, grid + timedelta(minutes=4, seconds=45))  # live once
    assert clock.is_due(source, grid + timedelta(minutes=5, seconds=5))  # the next pass
    late = grid + timedelta(minutes=50, seconds=50)  # a pass that started 50 s late
    clock.record(late, [("synthetic-ks", Outcome.OK, None)])
    assert clock.is_due(source, grid + timedelta(minutes=55, seconds=1))  # grid jitter
    clock.record(grid + timedelta(minutes=63), [("synthetic-ks", Outcome.OK, None)])
    assert not clock.is_due(source, grid + timedelta(minutes=65, seconds=10))  # off grid
    assert clock.is_due(source, grid + timedelta(minutes=70))


def test_alert_feed_asking_to_wait_is_not_read_until_the_wait_ends() -> None:
    reads: list[datetime] = []

    class WaitError(RuntimeError):
        retry_after = 1800.0

    def read() -> bytes:
        reads.append(datetime.now(UTC))
        if len(reads) == 1:
            raise WaitError("SYNTHETIC deferral")
        return feed({})

    watch = AlertWatch(read)
    start = at("2026-11-16 17:00")
    assert watch.counties(start) == frozenset()
    assert watch.counties(start + timedelta(minutes=29)) == frozenset()
    assert len(reads) == 1
    assert watch.counties(start + timedelta(minutes=30)) == frozenset({"20091"})
    assert len(reads) == 2
