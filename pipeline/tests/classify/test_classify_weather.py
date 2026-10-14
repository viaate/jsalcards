"""Weather terms, reason labels and other causes named in status text.

The texts are phrasing patterns written for these tests, not real listings.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import parse_status

TZ = "America/Chicago"
POSTED = datetime(2026, 1, 20, 5, 30, tzinfo=ZoneInfo(TZ))

REASONS = [
    # (text, reason, a term that must be found)
    ("Closed due to winter storm", "Winter storm", "winter storm"),
    ("Closed - Snow", "Winter storm", "snow"),
    ("Snow day", "Winter storm", "snow"),
    ("Closed - Snow and ice", "Winter storm", "ice"),
    ("Closed due to heavy snowfall", "Winter storm", "snow"),
    ("Delayed due to blizzard conditions", "Winter storm", "blizzard"),
    ("Closed due to lake-effect snow", "Winter storm", "lake-effect snow"),
    ("Closed - wintry mix", "Winter storm", "wintry mix"),
    ("Closed due to winter weather", "Winter storm", "winter weather"),
    ("2 hour delay due to snowy roads", "Winter storm", "snow"),
    ("Closed due to ice storm", "Ice", "ice storm"),
    ("Delayed due to freezing rain", "Ice", "freezing rain"),
    ("2 hour delay - icy roads", "Ice", "ice"),
    ("Delayed due to sleet", "Ice", "sleet"),
    ("Closed - black ice on roads", "Ice", "ice"),
    ("Delayed due to freezing drizzle", "Ice", "freezing drizzle"),
    ("Closed due to extreme cold", "Extreme cold", "extreme cold"),
    ("Delayed due to dangerous wind chills", "Extreme cold", "wind chill"),
    ("Closed - subzero temperatures", "Extreme cold", "subzero temperatures"),
    ("Closed due to bitter cold", "Extreme cold", "extreme cold"),
    ("2 hour delay due to cold temperatures", "Extreme cold", "cold"),
    ("Closed - polar vortex", "Extreme cold", "polar vortex"),
    ("Closed due to flooding", "Flooding", "flooding"),
    ("Closed - flash flooding", "Flooding", "flash flooding"),
    ("Closed due to high water", "Flooding", "high water"),
    ("Closed due to water over roadways", "Flooding", "water over roads"),
    ("Closed due to snowmelt flooding", "Flooding", "snowmelt"),
    ("Closed due to the hurricane", "Hurricane", "hurricane"),
    ("Closed - hurricane and flooding", "Hurricane", "flooding"),
    ("Closed - tropical storm", "Severe storms", "tropical storm"),
    ("Early dismissal due to severe storms", "Severe storms", "severe storms"),
    ("Early dismissal - tornado warning", "Severe storms", "tornado"),
    ("Early release due to thunderstorms", "Severe storms", "thunderstorms"),
    ("Closed due to severe weather", "Severe storms", "severe weather"),
    ("Early dismissal due to heat", "Heat", "heat"),
    ("Early dismissal due to extreme heat", "Heat", "extreme heat"),
    ("Early release - heat advisory", "Heat", "extreme heat"),
    ("Dismissing early due to high temperatures", "Heat", "high temperatures"),
    ("Early dismissal - hot weather", "Heat", "hot weather"),
    ("Closed due to power outage caused by ice storm", "Ice", "ice storm"),
]


@pytest.mark.parametrize(("text", "reason", "term"), REASONS)
def test_reason(text: str, reason: str, term: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.reason == reason
    assert result.reason in result.reasons
    assert term in result.weather_terms
    assert result.names_weather


@pytest.mark.parametrize(
    "text",
    [
        "Closed due to power outage",
        "Closed - no power",
        "Closed - power failure",
        "Closed; building without power",
    ],
)
def test_power_outage_is_a_reason_but_not_weather(text: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.kind == "closed"
    assert result.reason == "Power outage"
    assert result.names_weather is False


@pytest.mark.parametrize(
    ("text", "term"),
    [
        ("Closed - weather", "weather"),
        ("Closed due to inclement weather", "inclement weather"),
        ("Closed due to dense fog", "fog"),
        ("2 hour delay due to fog", "fog"),
        ("Closed due to storm", "storm"),
        ("Closed - storm damage", "storm"),
        ("Closed due to heavy rain", "rain"),
        ("Early dismissal due to high winds", "high winds"),
        ("Closed - tropical depression", "tropical depression"),
    ],
)
def test_weather_without_a_specific_label(text: str, term: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.names_weather
    assert term in result.weather_terms
    assert result.reason is None
    assert result.reasons == ()


@pytest.mark.parametrize(
    ("text", "cause"),
    [
        ("Closed due to water main break", "Water service"),
        ("Closed - burst pipe", "Water service"),
        ("Closed due to frozen pipes", "Water service"),
        ("Closed - no heat", "Heating"),
        ("Closed due to no heat", "Heating"),
        ("Closed - heating system failure", "Heating"),
        ("Closed - boiler problem", "Heating"),
        ("Closed due to gas leak", "Gas leak"),
        ("Closed due to fire", "Fire"),
        ("Closed due to illness", "Illness"),
        ("Closed - flu outbreak", "Illness"),
        ("Closed due to a threat", "Security"),
        ("Closed due to staff shortage", "Staffing"),
        ("Closed for teacher workday", "Planned day"),
        ("Closed - MLK Day", "Planned day"),
        ("No school - Winter break", "Planned day"),
        ("No school - professional development", "Planned day"),
        ("Early dismissal - no air conditioning", "Building"),
        ("Closed due to a funeral", "Funeral"),
        ("Closed due to wildfire smoke", "Air quality"),
        ("Closed - smoke from the fires", "Air quality"),
        ("Closed due to poor air quality", "Air quality"),
        ("Remote learning - AQI over 200", "Air quality"),
        ("Closed due to nearby wildfires", "Wildfire"),
        ("Closed - red flag warning", "Wildfire"),
        ("Closed due to earthquake", "Earthquake"),
        ("Closed due to a flood in the gym", "Building"),
        ("Closed - flooded basement", "Building"),
        ("Closed - teacher work day", "Planned day"),
    ],
)
def test_other_causes_are_not_weather(text: str, cause: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert cause in result.other_causes
    assert result.names_weather is False
    assert result.reason is None


@pytest.mark.parametrize(
    "text",
    [
        "Closed - no heat in the building",
        "Closed due to lack of heat",
        "Delayed - heat outage",
        "Delayed - heating issues",
        "Cold lunch will be served",
        "2 hour delay; cold lunch only",
        "Ice cream social cancelled",
        "Ice skating trip cancelled",
        "Game moved to rain date",
        "Blizzard bag day",
        "Closed - not weather related",
        "Closed - non-weather emergency",
        "Closed due to flooding from a burst pipe",
        "Closed due to flooded gym after water main break",
        "Closed",
        "Closed - common cold outbreak",
        # Water inside the building is no flood of the area.
        "Closed due to a flood in the gym",
        "Closed due to flooding in the basement",
        "Closed - flooded classrooms",
        # Weather the text says there is none of.
        "Closed. No snow expected.",
        "Closed, not due to weather",
        "Closed - not because of the snow",
    ],
)
def test_words_that_look_like_weather_but_are_not(text: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.names_weather is False
    assert result.weather_terms == ()
    assert result.reason is None


def test_terms_keep_their_order_and_do_not_repeat() -> None:
    result = parse_status(
        "Closed due to ice and snow; icy roads, more snow tonight", posted_at=POSTED, tz=TZ
    )
    assert result.weather_terms == ("ice", "snow")
    assert result.reasons == ("Winter storm", "Ice")
    assert result.reason == "Winter storm"


def test_hedged_status_still_names_weather() -> None:
    result = parse_status("Possible closure due to snow", posted_at=POSTED, tz=TZ)
    assert result.kind == "other"
    assert result.names_weather
    assert result.reason == "Winter storm"


# A weather word that begins a school's name names no weather. The names here are made up
# for these tests in the pattern of school names; none is a claim about a real school.
IN_NAMES = [
    ("Hurricane Middle School closed", "closed"),
    ("Hurricane High School: 2 hour delay", "delayed"),
    ("Closed: Hurricane Middle School", "closed"),
    ("Cold Spring Elementary closed", "closed"),
    ("Snow Hill Elementary: Closed", "closed"),
    ("Snow Canyon High School - 2 hour delay", "delayed"),
    ("Storm Lake Community Schools: closed", "closed"),
    ("Early dismissal at Storm Lake High School", "early_dismissal"),
    ("Flood Road Elementary closed", "closed"),
    ("Hail Ridge Academy: NTI day", "remote"),
    ("Snow Elementary closed", "closed"),
    ("Remote learning day for Frost Valley Elementary", "remote"),
    ("Snow Canyon High: Closed", "closed"),
    ("Snow Canyon High - 2 hour delay", "delayed"),
    ("Hurricane Schools: closed", "closed"),
    ("Storm Lake Schools - NTI day", "remote"),
]


@pytest.mark.parametrize(("text", "kind"), IN_NAMES)
def test_a_weather_word_in_a_school_name_names_no_weather(text: str, kind: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.kind == kind
    assert result.names_weather is False
    assert result.weather_terms == ()
    assert result.reason is None


@pytest.mark.parametrize(
    ("text", "reason", "term"),
    [
        ("Closed due to snow - Cold Spring Elementary", "Winter storm", "snow"),
        ("Hurricane closes Hurricane Middle School; closed", "Hurricane", "hurricane"),
        ("Snow day at Snow Hill Elementary", "Winter storm", "snow"),
        ("Heavy snow schools closed", "Winter storm", "snow"),
        ("Snow: schools closed", "Winter storm", "snow"),
        ("Snow high winds schools closed", "Winter storm", "snow"),
        ("Ice storm - schools closed", "Ice", "ice storm"),
        ("Flooding closes schools; closed", "Flooding", "flooding"),
        ("Snow closes Lincoln Elementary; closed", "Winter storm", "snow"),
        ("Icy roads: school closed", "Ice", "ice"),
    ],
)
def test_weather_beside_a_name_still_counts(text: str, reason: str, term: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.reason == reason
    assert term in result.weather_terms


@pytest.mark.parametrize(
    ("text", "reason", "term", "name"),
    [
        ("Hurricane Schools: 2 hour delay due to ice", "Ice", "ice", "hurricane"),
        ("Snow Canyon High: closed due to ice", "Ice", "ice", "snow"),
        ("Storm Lake Schools: closed - flooding", "Flooding", "flooding", "storm"),
    ],
)
def test_a_name_that_heads_the_text_names_no_weather_beside_weather_that_does(
    text: str, reason: str, term: str, name: str
) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.reason == reason
    assert result.reasons == (reason,)
    assert term in result.weather_terms
    assert name not in result.weather_terms


@pytest.mark.parametrize(
    ("text", "reason", "term"),
    [
        ("Snow totals high, schools closed", "Winter storm", "snow"),
        ("Snow chances high; closed", "Winter storm", "snow"),
        ("Snow chances high today; closed", "Winter storm", "snow"),
        ("Closed due to snow, flood in the gym", "Winter storm", "snow"),
        ("No school due to snow", "Winter storm", "snow"),
        ("Closed - no power due to ice storm", "Ice", "ice storm"),
    ],
)
def test_weather_the_text_does_name_still_counts(text: str, reason: str, term: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.reason == reason
    assert term in result.weather_terms


@pytest.mark.parametrize(
    "text",
    ["Closed, Workday Optional", "Closed - optional workday for staff", "Closed; workday optional"],
)
def test_an_optional_workday_is_no_planned_day(text: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.kind == "closed"
    assert "Planned day" not in result.other_causes


@pytest.mark.parametrize(
    "text", ["Closed - snow make-up day", "Closed - teacher workday. Snow make-up day."]
)
def test_a_day_that_makes_up_a_snow_day_has_no_weather_reason(text: str) -> None:
    result = parse_status(text, posted_at=datetime(2026, 1, 21, 6, 0, tzinfo=ZoneInfo(TZ)), tz=TZ)
    assert result.reason is None
