"""The heights an NWS alert names for where it applies."""

import json
from pathlib import Path

import numpy as np
import pytest

from snowlight.sources.nws.alerts import parse_active, parse_alert
from snowlight.sources.nws.elevation import Band, ElevationLimit, paragraphs, parse_alert_text

FIXTURE = Path(__file__).parents[1] / "predict" / "fixtures" / "nws-2026-10-22-advisories.json"
"""Four public NWS products of October 2026: the two Winter Weather Advisories (KHNX WW.Y
0005, KREV WW.Y 0009) as first issued and as the active feed held them on October 22."""


SAMPLE = Path(__file__).parent / "fixtures" / "wsw-elevation-sample.json"
"""45 reviewed segments of public NWS winter weather messages (IEM AFOS, 2023-2026)."""


def above(feet: int) -> ElevationLimit:
    return ElevationLimit((Band(feet, None),))


def below(feet: int) -> ElevationLimit:
    return ElevationLimit((Band(None, feet),))


def what(text: str) -> str:
    return f"* WHAT...{text}\n\n"


def where(text: str) -> str:
    return f"* WHERE...{text}\n\n"


@pytest.mark.parametrize(
    ("line", "limit"),
    [
        ("WINTER WEATHER ADVISORY IN EFFECT ABOVE 8,000 FEET FROM 11 AM", above(8000)),
        ("WINTER WEATHER ADVISORY IN EFFECT FROM 11 AM WEDNESDAY TO 5 PM PDT THURSDAY ABOVE 8000 "
         "FEET", above(8000)),
        ("WINTER STORM WARNING REMAINS IN EFFECT UNTIL 3 PM PST FOR ELEVATIONS ABOVE 4500",
         above(4500)),
        ("WINTER STORM WARNING ABOVE 7,000 FT IN EFFECT FROM 5 PM FRIDAY", above(7000)),
        ("WINTER WEATHER ADVISORY REMAINS IN EFFECT UNTIL 4 PM ABOVE 4500 FEET IN SISKIYOU COUNTY",
         above(4500)),
        ("WINTER WEATHER ADVISORY FOR MONO ABOVE 8000 FEET WILL EXPIRE AT 5 AM", above(8000)),
        ("WINTER WEATHER ADVISORY IN EFFECT UNTIL 9 PM 6000 FEET AND HIGHER", above(6000)),
        ("WINTER WEATHER ADVISORY IN EFFECT UNTIL 9 PM BELOW 5000 FEET", below(5000)),
        ("WINTER WEATHER ADVISORY IN EFFECT UNTIL 9 PM BETWEEN 3000 AND 5000 FEET",
         ElevationLimit((Band(3000, 5000),))),
        ("WINTER WEATHER ADVISORY IN EFFECT UNTIL 9 PM FROM 5000 TO 3000 FT",
         ElevationLimit((Band(3000, 5000),))),
    ],
)  # fmt: skip
def test_a_headline_naming_one_band_limits_the_alert(line: str, limit: ElevationLimit) -> None:
    assert parse_alert_text([line], None, None) == limit


@pytest.mark.parametrize(
    ("text", "limit"),
    [
        ("Above 8,000 feet in the Sierra Nevada.", above(8000)),
        ("Above 8,000 feet in the Sierra Nevada and the Kern County Mountains.", above(8000)),
        ("Above 5000 ft in the high south central Cascades in Klamath and Douglas Counties.",
         above(5000)),
        ("Elevations above 5000 feet.", above(5000)),
        ("Mono County above 7500 ft.", above(7500)),
        ("Northern Trinity County for elevations above 4000 feet.", above(4000)),
        ("Leadville Vicinity/Lake County Below 11000 Feet.", below(11000)),
        ("Cascade County below 5000ft.", below(5000)),
        ("Locations below 2000 feet.", below(2000)),
        ("Between 3,000 feet and 5,000 feet.", ElevationLimit((Band(3000, 5000),))),
    ],
)  # fmt: skip
def test_a_where_of_one_band_limits_the_alert(text: str, limit: ElevationLimit) -> None:
    assert parse_alert_text([], None, where(text)) == limit


@pytest.mark.parametrize(
    "first",
    [
        "Snow above 8000 feet.",
        "Heavy wet snow expected above 6500 feet.",
        "Accumulating snow expected for elevations above 5000 feet.",
        "Snow and blowing snow above 9,000 ft.",
        # The critic's probe: the weather's band beside the weather at another height.
        "Snow above 7000 feet. A rain and snow mix around 6000 feet.",
        "Snow above 7000 feet. Rain elsewhere.",
    ],
)
def test_the_weather_and_its_band_in_a_what_say_nothing_of_where_the_alert_applies(
    first: str,
) -> None:
    """A WHAT speaks of the weather: "snow above 7000 feet" beside "rain elsewhere" is no
    statement that the alert leaves the lower ground out. Only the headline or WHERE is."""
    rest = " Additional snow accumulations of 2 to 6 inches. Winds gusting as high as 40 mph."
    assert parse_alert_text([], None, what(first + rest) + where("Mono County.")) is None
    # Inside a band a headline or WHERE states, it keeps that band.
    if "around" not in first and "elsewhere" not in first:
        stated = where("Mono County above 5000 feet.")
        assert parse_alert_text([], None, what(first + rest) + stated) == above(5000)


@pytest.mark.parametrize(
    "line",
    [
        # Not the product's own line: a headline of the weather is no statement of where.
        "HEAVY SNOW EXPECTED ABOVE 7000 FEET",
        "SNOW ABOVE 7000 FEET TONIGHT",
        "WINTER STORM WARNING ABOVE 7000 FEET",
        # A second area after the band: the band may belong to the first alone.
        "WINTER STORM WARNING IN EFFECT ABOVE 5000 FEET IN JOSEPHINE COUNTY AND FOR SOUTH "
        "CENTRAL OREGON",
        "WINTER STORM WARNING IN EFFECT ABOVE 5000 FEET IN JOSEPHINE COUNTY, AND IN SOUTH "
        "CENTRAL OREGON",
        "WINTER STORM WARNING IN EFFECT ABOVE 5000 FEET IN JOSEPHINE COUNTY; FOR SOUTH CENTRAL "
        "OREGON",
        "WINTER STORM WARNING IN EFFECT ABOVE 5000 FEET IN JOSEPHINE COUNTY WITH SNOW TO THE "
        "VALLEY FLOOR",
        "WINTER STORM WARNING IN EFFECT ABOVE 5000 FEET IN JOSEPHINE COUNTY. SNOW IN MEDFORD",
    ],
)
def test_a_headline_states_a_band_only_as_the_product_line_and_for_one_area(line: str) -> None:
    assert parse_alert_text([line], None, None) is None


def test_a_headline_band_over_one_listed_area_keeps_it() -> None:
    """One area after the band, its counties listed: the band covers all of it (real KMFR)."""
    line = (
        "WINTER WEATHER ADVISORY REMAINS IN EFFECT UNTIL 5 AM PDT THURSDAY ABOVE 4000 FT IN THE "
        "HIGH SOUTH CENTRAL CASCADES IN KLAMATH, JACKSON AND DOUGLAS COUNTIES"
    )
    assert parse_alert_text([line], None, None) == above(4000)
    line = "WINTER STORM WARNING IN EFFECT ABOVE 5000 FEET FOR THE CASCADES AND THE KLAMATH BASIN"
    assert parse_alert_text([line], None, None) == above(5000)
    # The same second area after a WHERE band is refused too.
    text = "Above 5000 feet in Josephine County and for South Central Oregon."
    assert parse_alert_text([], None, where(text)) is None


@pytest.mark.parametrize(
    "extra",
    [
        # Real forms (KPDT WW.Y 0014, KEKA WW.Y 0003 of 2026) and the critic's probes.
        "Light snow accumulations are forecast as low as 3500 feet this evening.",
        "Lighter snow accumulations up to 1 inch will be possible as low as 2500 feet Thursday "
        "morning.",
        "Snow will lower to 3000 feet by Saturday morning.",
        "Snow lowering to the passes by morning.",
        "Up to an inch in the foothills.",
        "3 to 6 inches at lake level.",
        "Snow as low as the lake by morning.",
        "Snow, with accumulations reaching 3500 feet late tonight.",
        "A rain and snow mix around 4000 feet.",
        "4 to 8 inches above 4000'.",
        "4 to 8 inches above 5 kft.",
        "Chains required at the 4,200-foot summit.",
    ],
)
def test_any_word_or_height_of_lower_ground_anywhere_undoes_a_stated_band(extra: str) -> None:
    """The headline states "above 7000 feet" (or 4500, or 4000); any other part of the alert
    that names lower ground, in words or as a height, undoes the limit."""
    for line, feet in (
        ("WINTER WEATHER ADVISORY IN EFFECT ABOVE 7000 FEET", 7000),
        ("WINTER WEATHER ADVISORY REMAINS IN EFFECT UNTIL 11 PM PDT THIS EVENING ABOVE 4500 "
         "FEET", 4500),
    ):  # fmt: skip
        plain = what("Snow. 2 to 5 inches.") + where("Southern Cascades.")
        assert parse_alert_text([line], None, plain) == above(feet)
        details = plain + f"* ADDITIONAL DETAILS...{extra}\n\n"
        assert parse_alert_text([line], None, details) is None
        assert parse_alert_text([line], None, what(f"Snow. 2 to 5 inches. {extra}")) is None


def test_a_height_named_within_the_stated_band_and_a_wind_chill_keep_it() -> None:
    """A pass named at its height inside the band (real KMFR), and "wind chills as low as 10
    above zero" (real KPSR), say nothing of lower ground."""
    line = "WINTER WEATHER ADVISORY REMAINS IN EFFECT UNTIL 11 AM PDT THIS MORNING ABOVE 4000 FEET"
    impacts = "* IMPACTS...Slick roads at Etna Summit on Sawyers Bar Rd at 5950 ft.\n\n"
    assert parse_alert_text([line], None, where("Western Siskiyou.") + impacts) == above(4000)
    chills = "* IMPACTS...The dangerously cold wind chills as low as 10 above zero.\n\n"
    assert parse_alert_text([line], None, where("Western Siskiyou.") + chills) == above(4000)
    below_band = "* IMPACTS...Slick roads at Etna Summit at 3950 ft.\n\n"
    assert parse_alert_text([line], None, where("Western Siskiyou.") + below_band) is None


@pytest.mark.parametrize(
    "text",
    [
        # Amounts, winds and hedges around a band (the critic's real forms among them).
        "Heavy snow. Snow accumulations between 2 to 3 feet in the Tahoe Basin, highest on the "
        "west shore. Snow accumulations of 3 to 5 feet above 7000 feet.",
        "Heavy mixed precipitation expected. Total snow accumulations between 4 and 10 inches "
        "across much of eastern New Mexico with higher amounts of 10 to 16 inches above 9,000 "
        "feet.",
        "Total snow accumulations of 2 to 4 inches, with up to 8 inches above 8000 feet.",
        "Heavy snow. Total snow accumulations of 6 to 12 inches, except 1 to 2 feet above 7000 "
        "feet.",
        "Snow expected. Total snow accumulations 2 to 6 inches except up to 9 inches above 8500 "
        "feet.",
        "Snow accumulations of 1 to 3 inches, with 4 to 8 inches above 5000 feet.",
        "Heavy snow and strong winds. Snow accumulations of 1 to 2 feet. Winds gusting as high "
        "as 100 mph over Sierra ridges above 9000 feet.",
        "Snow, heaviest above 6000 feet.",
        "Heavy snow expected. Total snow accumulations between 10 and 24 inches, heaviest above "
        "8,000 feet.",
        "Mainly above 4000 feet.",
        "Snow, mainly above 7500 feet across the northern Utah mountains.",
        "Freezing rain. Ice accumulations of a light glaze, mainly above 1500 feet.",
        "from 3000 to 5000 feet with 4 to 8 inches above 5000 feet",
        "Heavy snow. Additional snow accumulations between 2 and 6 inches between 7500 and 9500 "
        "feet and 6 to 10 inches above 9500 feet.",
        "near and above 6000 feet",
        "at or above 6000 feet",
        "above 6000 feet MSL",
        "the higher terrain above 2500 feet, mainly the Catskills",
        "Passes above 7000 feet including Donner Summit.",
        "Roads over passes above 7000 feet, as well as towns in the Tahoe Basin.",
        # More than one area, or more than one sentence, around a band.
        "Grand and Summit Counties Below 9000 Feet, South Park, Byers, and Limon.",
        "Greater Lake Tahoe Area and Mono County above 7000 feet.",
        "Lake Tahoe, and elevations above 7000 feet in Mono County.",
        "Western Plumas County/Lassen Park. Elevations above 5000 feet. Also the Sacramento "
        "Valley.",
        "above 8000 feet in Tulare County and all of Mono County",
        "Above 9,000 feet. Below 9000 feet snow mixed with rain",
        # The lower ground, a height in words, a height out of range, no band.
        "Snow above 6000 feet, with 1 to 3 inches at lower elevations.",
        "Snow at all elevations, heaviest above 7000 feet.",
        "Snow levels falling to 4000 feet by morning. Above 7000 feet.",
        "Snow down to 3500 feet.",
        "Snow on the valley floor and above 5000 feet.",
        "Snow at elevations above 3000 feet, while rain falls in the valleys",
        "Lower elevations could see a dusting. Above 7000 feet",
        "Above eight thousand feet.",
        "above 8 thousand feet",
        "Snow above 25,000 feet.",
        "above 60000 feet",
        "above 7000' in Mono",
        "Wind chills as low as 30 below zero.",
        "Total snow accumulations of 1 to 2 feet.",
        "",
    ],
)
def test_amounts_hedges_lists_and_the_lower_ground_are_no_limit(text: str) -> None:
    """A band that qualifies an amount, a wind or part of the areas, or sits beside the lower
    ground, says nothing of where the alert applies: whatever paragraph holds it."""
    assert parse_alert_text([], None, what(text) + where("Greater Lake Tahoe Area.")) is None
    assert parse_alert_text([], None, where(text)) is None
    headline = "WINTER STORM WARNING REMAINS IN EFFECT UNTIL 10 PM PST WEDNESDAY " + text.upper()
    assert parse_alert_text([headline], None, None) is None


@pytest.mark.parametrize(
    ("description", "limit"),
    [
        # Bands inside the stated one keep it.
        (what("Snow above 8000 feet. Up to 10 inches above 9,000 feet.") + where("Mono County "
         "above 8000 feet."), above(8000)),
        (what("Heavy snow. 6 to 12 inches above 7000 feet.") + where("Sierra Nevada above 7,000 "
         "feet."), above(7000)),
        # A band reaching below the stated one undoes it, wherever it is.
        (what("Snow. 1 to 4 inches between 3000 and 5000 feet.") +
         where("Mono County above 5000 feet."), None),
        (what("Heavy snow. 2 to 6 inches above 4500 feet, 8 to 24 inches above 5000 feet.") +
         where("West Slope Northern Sierra Nevada above 5000 feet."), None),
        (where("Mono County above 8000 feet.") + "* IMPACTS...Slick roads below 6000 feet.\n\n",
         None),
        (where("Elevations above 9,000 feet.") + "* ADDITIONAL DETAILS...Snow levels near 7000 "
         "feet.\n\n", None),
    ],
)  # fmt: skip
def test_every_band_in_the_alert_must_lie_within_the_stated_ones(
    description: str, limit: ElevationLimit | None
) -> None:
    assert parse_alert_text([], None, description) == limit
    # The same with the band in the headline instead.
    headline = "WINTER STORM WARNING IN EFFECT UNTIL 4 PM ABOVE 8000 FEET"
    if limit == above(8000):
        assert parse_alert_text([headline], None, description) == limit


def test_two_headlines_of_one_segment_are_one_limit() -> None:
    """A warning above 4000 feet and an advisory above 2500 feet in one segment: a school in
    either band is reached (a union only ever widens the ground)."""
    lines = [
        "WINTER STORM WARNING WILL EXPIRE AT 11 AM MST THIS MORNING ABOVE 4000 FEET",
        "WINTER WEATHER ADVISORY WILL EXPIRE AT 11 AM MST THIS MORNING ABOVE 2500 FEET",
    ]
    assert parse_alert_text(lines, None, None) == ElevationLimit((Band(2500, None),
                                                                  Band(4000, None)))  # fmt: skip


def test_the_reviewed_sample_of_real_messages_gives_the_reviewed_limits() -> None:
    """Every segment of the reviewed sample, as the CAP feed holds it: the headlines, and the
    WHAT and WHERE paragraphs of the description."""
    cases = json.loads(SAMPLE.read_text())["cases"]
    assert len(cases) == 45
    wrong = []
    for case in cases:
        description = (
            (what(case["what"]) if case["what"] is not None else "")
            + (where(case["where"]) if case["where"] is not None else "")
            + (case["details"] + "\n\n" if "details" in case else "")
        )
        found = parse_alert_text(case["headlines"], None, description or None)
        expected = ElevationLimit.from_json(case["limit"])
        if found != expected:
            wrong.append((case["product"], case["issued"], case["case"], found, expected))
    assert wrong == []
    # The three the critic found read as whole-zone alerts, and both kinds of result occur.
    by_case = {case["case"]: case["limit"] for case in cases}
    assert by_case["amount qualifier: 3 to 5 feet above 7000 feet (Tahoe Basin)"] is None
    assert by_case["amount qualifier: higher amounts above 9,000 feet"] is None
    assert by_case["WHERE lists other areas beside the banded one"] is None
    # The lower ground the r2 critic found in the other paragraphs.
    assert by_case["headline band, lower ground in ADDITIONAL DETAILS: as low as 3500 feet"] is None
    assert by_case["WHERE band, lower ground in ADDITIONAL DETAILS: as low as 2500 feet"] is None
    limited = sum(1 for case in cases if case["limit"] is not None)
    assert 10 <= limited <= len(cases) - 10


def test_only_the_what_and_where_paragraphs_are_statements() -> None:
    description = (
        "* WHAT...Snow above 8,000 feet. Accumulations of 4 to 8\ninches.\n\n"
        "* WHERE...Mono County above 8000 feet.\n\n"
        "* IMPACTS...Roads slick.\n\n"
        "* ADDITIONAL DETAILS...Chains above 8500 feet."
    )
    assert paragraphs(description) == [
        "Snow above 8,000 feet. Accumulations of 4 to 8\ninches.",
        "Mono County above 8000 feet.",
    ]
    assert paragraphs(description, "WHERE") == ["Mono County above 8000 feet."]
    assert parse_alert_text([], None, description) == above(8000)
    # A headline that names no band adds none.
    assert parse_alert_text(["ADVISORY REMAINS IN EFFECT"], "Advisory issued", description) == (
        above(8000)
    )
    # A band only the other paragraphs name is no statement.
    assert parse_alert_text([], None, "* IMPACTS...Above 8000 feet.\n\n") is None
    assert parse_alert_text([], None, None) is None


def test_a_limit_reaches_within_its_bands_and_a_margin_and_unknown_heights() -> None:
    feet = np.array([4068.0, 6806.0, 7499.0, 7500.0, 7808.0, np.nan])
    assert above(8000).reaches(feet, 500).tolist() == [False, False, False, True, True, True]
    assert above(8000).reaches(feet, 0).tolist() == [False, False, False, False, False, True]
    below = ElevationLimit((Band(None, 4000),))
    assert below.reaches(feet, 500).tolist() == [True, False, False, False, False, True]
    both = ElevationLimit((Band(None, 4000), Band(7800, None)))
    assert both.reaches(feet, 0).tolist() == [False, False, False, False, True, True]
    band = ElevationLimit((Band(6000, 7000),))
    assert band.reaches(feet, 500).tolist() == [False, True, True, True, False, True]


def test_a_limit_round_trips_through_the_state_and_bad_ones_are_refused() -> None:
    limit = ElevationLimit((Band(None, 2000), Band(3000, 5000), Band(7000, None)))
    assert ElevationLimit.from_json(json.loads(json.dumps(limit.as_json()))) == limit
    assert ElevationLimit.from_json(None) is None
    assert ElevationLimit.from_json([]) is None
    for bad in ("8000", [[8000]], [["8000", None]], [[True, None]], [8000]):
        with pytest.raises(ValueError, match="elevation"):
            ElevationLimit.from_json(bad)


def test_the_october_22_advisories_say_above_8000_feet() -> None:
    """Both Sierra advisories of October 22, as first issued and as the feed held them (the
    KHNX update's headline names no height; its WHERE line does)."""
    feed = parse_active(FIXTURE.read_bytes())
    assert len(feed.alerts) == 4
    assert {alert.elevation for alert in feed.alerts} == {above(8000)}


def test_a_headline_in_another_shape_names_no_height_and_keeps_the_alert() -> None:
    feature = json.loads(FIXTURE.read_text())["features"][0]
    feature["properties"]["parameters"]["NWSheadline"] = "ABOVE 8000 FEET"
    feature["properties"]["description"] = None
    feature["properties"]["headline"] = 12
    alert = parse_alert(feature)
    assert alert.elevation is None
    assert alert.vtec
