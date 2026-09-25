"""Tests for local windows and time zones from the NWS boundary files."""

from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

import pytest

from snowlight.weather.timezones import (
    IANA_ZONES,
    LocalWindow,
    TimeZoneLookup,
    TodayWindow,
    local_window,
)

if TYPE_CHECKING:
    from weather.conftest import Kit


def test_local_window_is_the_local_day_in_utc() -> None:
    assert local_window(date(2026, 1, 26), "America/Chicago") == (
        datetime(2026, 1, 26, 6, tzinfo=UTC),
        datetime(2026, 1, 27, 6, tzinfo=UTC),
    )
    start, end = local_window(date(2026, 3, 8), "America/New_York")
    assert (end - start).total_seconds() == 23 * 3600
    assert local_window(date(2026, 1, 26), "America/Phoenix", time(7), time(16)) == (
        datetime(2026, 1, 26, 14, tzinfo=UTC),
        datetime(2026, 1, 26, 23, tzinfo=UTC),
    )
    evening = LocalWindow(date(2026, 1, 26), time(18), time(9))
    assert evening.utc("America/Los_Angeles") == (
        datetime(2026, 1, 27, 2, tzinfo=UTC),
        datetime(2026, 1, 27, 17, tzinfo=UTC),
    )


def _lookup(kit: "Kit") -> TimeZoneLookup:
    catalog = kit.catalog()
    counties = catalog.boundaries_for("county", date(2026, 9, 25))
    zones = catalog.boundaries_for("zone", date(2026, 9, 25))
    assert counties is not None
    assert zones is not None
    return TimeZoneLookup(counties, zones)


def _inside(kit: "Kit", ugc: str) -> tuple[float, float]:
    zones = kit.catalog().boundaries_for("zone", date(2026, 9, 25))
    assert zones is not None
    point = zones.areas[ugc].representative_point()
    return point.y, point.x


def test_county_codes_give_the_zone(kit: "Kit") -> None:
    lookup = _lookup(kit)
    assert lookup.zone_for("35009", None, None) == "America/Denver"
    assert lookup.zone_for("09003", None, None) == "America/New_York"
    assert lookup.zone_for("99999", None, None) is None
    assert lookup.zone_for(None, None, None) is None


def test_split_counties_fall_back_to_the_forecast_zone(kit: "Kit") -> None:
    lookup = _lookup(kit)
    # Apache County, Arizona is coded Mm; the Chinle Valley zone (Navajo Nation) is M.
    assert lookup.zone_for("04001", None, None) is None
    assert lookup.zone_for("04001", *_inside(kit, "AZZ010")) == "America/Denver"
    assert lookup.zone_for("04001", *_inside(kit, "AZZ014")) is None
    # Gulf County, Florida is split (CE), and so is its forecast zone.
    assert lookup.zone_for("12045", *_inside(kit, "FLZ014")) is None
    # A Connecticut planning-region code is not an NWS county; the point decides.
    assert lookup.zone_for("09110", *_inside(kit, "CTZ002")) == "America/New_York"
    assert lookup.zone_for(None, 0.0, 0.0) is None


def test_codes_map_to_iana_zones() -> None:
    assert IANA_ZONES["m"] == "America/Phoenix"
    assert set(IANA_ZONES) == {"E", "C", "M", "m", "P"}
    with pytest.raises(KeyError):
        IANA_ZONES["V"]


def test_unsettled_places_list_every_zone_they_can_be_in(kit: "Kit") -> None:
    lookup = _lookup(kit)
    assert lookup.zones_for("35009", None, None) == ("America/Denver",)
    assert lookup.zones_for("04001", *_inside(kit, "AZZ010")) == ("America/Denver",)
    # Navajo Nation keeps daylight time, the rest of Arizona does not.
    phoenix_or_denver = ("America/Denver", "America/Phoenix")
    assert lookup.zones_for("04001", None, None) == phoenix_or_denver
    assert lookup.zones_for("04001", *_inside(kit, "AZZ014")) == phoenix_or_denver
    assert lookup.zones_for("12045", *_inside(kit, "FLZ014")) == (
        "America/Chicago",
        "America/New_York",
    )
    # The forecast zone at the point is more local than the county: it wins.
    assert lookup.zones_for("12045", *_inside(kit, "AZZ014")) == phoenix_or_denver
    assert lookup.zones_for("99999", None, None) == ()
    assert lookup.zones_for(None, 0.0, 0.0) == ()
    assert lookup.zones_for(None, None, None) == ()


def test_today_is_the_local_date_in_each_zone() -> None:
    # 03:30 UTC on 25 September is still the evening of the 24th in the contiguous states.
    now = datetime(2026, 9, 25, 3, 30, tzinfo=UTC)
    today = TodayWindow(now)
    assert today.day_in("America/New_York") == date(2026, 9, 24)
    assert today.utc("America/New_York") == local_window(date(2026, 9, 24), "America/New_York")
    assert TodayWindow(now, time(7), time(9)).utc("America/Chicago") == (
        datetime(2026, 9, 24, 12, tzinfo=UTC),
        datetime(2026, 9, 24, 14, tzinfo=UTC),
    )
    assert TodayWindow(datetime(2026, 9, 25, 12, tzinfo=UTC)).day_in("America/Los_Angeles") == (
        date(2026, 9, 25)
    )
    with pytest.raises(ValueError, match="aware"):
        TodayWindow(datetime(2026, 9, 25, 12)).day_in("America/Chicago")
