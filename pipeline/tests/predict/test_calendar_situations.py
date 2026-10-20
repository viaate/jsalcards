"""School days, the days a pass forecasts, and the one weather-class rule."""

from datetime import UTC, date, datetime, time

import pytest

from snowlight.predict.calendar import (
    forecast_days,
    is_school_day,
    previous_school_day,
    school_days,
    season_label,
    season_of,
    thanksgiving,
)
from snowlight.predict.situations import (
    SITUATIONS,
    Event,
    Situation,
    WeatherClass,
    Window,
    counts,
    district_class,
    district_class_from_counts,
    school_class,
)

WINDOW = Window(time(18), time(9), 21)
CHICAGO = "America/Chicago"


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 1, 6), True),  # a Tuesday
        (date(2026, 1, 10), False),  # a Saturday
        (date(2025, 11, 27), False),  # Thanksgiving
        (date(2025, 11, 28), False),  # the Friday after
        (date(2025, 11, 26), True),
        (date(2025, 12, 24), False),
        (date(2026, 1, 1), False),
        (date(2026, 1, 2), True),
        (date(2026, 7, 1), False),  # summer
        (date(2025, 8, 15), True),
        (date(2026, 6, 15), True),
        (date(2026, 6, 16), False),
    ],
)
def test_school_days(day: date, expected: bool) -> None:
    assert is_school_day(day) is expected


def test_thanksgiving_and_seasons() -> None:
    assert thanksgiving(2026) == date(2026, 11, 26)
    assert season_of(date(2025, 1, 6)) == 2024
    assert season_of(date(2025, 8, 20)) == 2025
    assert season_label(2024) == "2024-25"
    assert previous_school_day(date(2026, 1, 5)) == date(2026, 1, 2)
    assert previous_school_day(date(2025, 12, 1)) == date(2025, 11, 26)
    assert list(school_days(date(2026, 1, 9), date(2026, 1, 12))) == [
        date(2026, 1, 9),
        date(2026, 1, 12),
    ]


def test_forecast_days_follow_los_angeles_across_zones_and_dst() -> None:
    zone = "America/Los_Angeles"
    # 06:30 UTC is still the evening before in Los Angeles.
    assert forecast_days(at("2026-01-07T06:30:00"), zone) == (date(2026, 1, 6), date(2026, 1, 7))
    assert forecast_days(at("2026-01-07T08:30:00"), zone) == (date(2026, 1, 7), date(2026, 1, 8))
    # Daylight time: midnight in Los Angeles is 07:00 UTC.
    assert forecast_days(at("2026-07-07T06:59:00"), zone)[0] == date(2026, 7, 6)
    assert forecast_days(at("2026-07-07T07:00:00"), zone)[0] == date(2026, 7, 7)
    with pytest.raises(ValueError, match="aware"):
        forecast_days(datetime(2026, 1, 7), zone)


def test_class_order_is_strongest_first() -> None:
    order = sorted(WeatherClass, reverse=True)
    assert [weather.label for weather in order] == [
        "blizzard", "ice", "snow_warning", "lake_snow", "cold", "tropical", "advisory", "none",
    ]  # fmt: skip
    assert len(SITUATIONS) == 10
    assert Situation.of(WeatherClass.SNOW_WARNING, after=True).key == "snow_warning"
    assert Situation.of(WeatherClass.NONE, after=True).key == "none_after"
    assert Situation.from_key("advisory_after") == Situation(WeatherClass.ADVISORY, after=True)
    for bad in ("sunny", "snow_warning_after"):
        with pytest.raises(ValueError, match="not a situation"):
            Situation.from_key(bad)
    assert Situation.of(WeatherClass.ICE, after=False).group == "severe"


def test_a_product_issued_after_the_snapshot_does_not_count() -> None:
    day = date(2026, 1, 7)
    snapshot = WINDOW.snapshot(day, CHICAGO)
    assert snapshot == at("2026-01-07T03:00:00")
    event = Event("WS.W", at("2026-01-07T03:30:00"), at("2026-01-07T06:00:00"), None)
    assert not counts(event, day, CHICAGO, WINDOW, snapshot)
    assert counts(event, day, CHICAGO, WINDOW, at("2026-01-07T04:00:00"))
    assert school_class([event], day, CHICAGO, WINDOW, snapshot) is WeatherClass.NONE


def test_the_window_runs_from_six_pm_the_day_before_to_nine_am() -> None:
    day = date(2026, 1, 7)
    issued = at("2026-01-06T12:00:00")
    late = Event("WS.W", issued, at("2026-01-07T15:00:00"), at("2026-01-07T20:00:00"))
    early = Event("WS.W", issued, at("2026-01-06T10:00:00"), at("2026-01-07T00:00:00"))
    inside = Event("WW.Y", issued, at("2026-01-07T00:00:00"), at("2026-01-07T06:00:00"))
    as_of = at("2026-01-07T03:00:00")
    assert not counts(late, day, CHICAGO, WINDOW, as_of)  # starts 9 AM local
    assert not counts(early, day, CHICAGO, WINDOW, as_of)  # ends 6 PM local
    assert counts(inside, day, CHICAGO, WINDOW, as_of)
    open_ended = Event("TR.W", issued, at("2026-01-05T00:00:00"), None)
    assert counts(open_ended, day, CHICAGO, WINDOW, as_of)
    flood = Event("FF.W", issued, at("2026-01-07T00:00:00"), None)
    assert flood.weather is None
    assert not counts(flood, day, CHICAGO, WINDOW, as_of)
    both = [inside, Event("BZ.W", issued, at("2026-01-07T01:00:00"), None)]
    assert school_class(both, day, CHICAGO, WINDOW, as_of) is WeatherClass.BLIZZARD


def test_the_district_class_covers_half_its_schools_or_more() -> None:
    snow, ice, none = WeatherClass.SNOW_WARNING, WeatherClass.ICE, WeatherClass.NONE
    assert district_class([snow, snow, none, none], 0.5) is snow
    assert district_class([snow, none, none], 0.5) is none
    # One ice and one snow: half covered by snow or stronger, not by ice.
    assert district_class([ice, snow, none, none], 0.5) is snow
    assert district_class([], 0.5) is none
    covered = [0] * 8
    covered[int(ice)], covered[int(snow)] = 1, 1
    assert district_class_from_counts(covered, 4, 0.5) is snow
    assert district_class_from_counts(covered, 5, 0.5) is none
    assert district_class_from_counts(covered, 0, 0.5) is none
