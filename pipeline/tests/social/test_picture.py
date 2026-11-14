"""The fresh picture's view and description, from SYNTHETIC live files
(snowlight.social.picture)."""

import json
import math
import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from snowlight.directory.points import NO_DISTRICT, Points
from snowlight.social.cards import alt_text
from snowlight.social.picture import (
    CONTIGUOUS_ZONES,
    DISTRICT_X,
    FIT_BOX,
    HEIGHT,
    MAX_ZOOM,
    REGIONS,
    SCHOOL_STARTS,
    UNKNOWN_ZONE,
    UNREAD_ZONE,
    WIDTH,
    ZOOM,
    ZOOM_STEP,
    Counts,
    Directory,
    PictureError,
    Taken,
    _held,
    _states,
    busiest_view,
    calm_regions,
    chance_day,
    chance_text,
    choose,
    clock,
    district_frame,
    lit_schools,
    map_day,
    project,
    region,
    school_zones,
    slot_of,
    today_everywhere,
    unproject,
    view_states,
)
from snowlight.social.render import directory_of
from snowlight.social.rules import mentions_chance, mentions_closings

# Ten public schools: six around Buffalo, NY (36...), two in Pennsylvania (42...) near them,
# one in Minnesota (27...) and one in Texas (48...). Two districts: NY (3600001), MN (2700001).
SCHOOLS = (
    "360000100001", "360000100002", "360000100003", "360000100004", "360000100005",
    "360000100006", "420000100001", "420000100002", "270000100001", "480000100001",
)  # fmt: skip
LON = (-78.88, -78.80, -78.70, -78.95, -78.60, -78.75, -79.90, -80.05, -93.26, -97.74)
LAT = (42.89, 42.95, 42.80, 42.70, 42.90, 43.00, 42.12, 42.13, 44.98, 30.27)
DISTRICTS = ("3600001", "2700001")
STAMP = {"generated_on": "2026-10-14", "schools": 10, "districts": 2}


def directory() -> Directory:
    points = Points(
        lon_e6=np.asarray([round(v * 1e6) for v in LON], dtype=np.int32),
        lat_e6=np.asarray([round(v * 1e6) for v in LAT], dtype=np.int32),
        district=np.asarray([0, 0, 0, 0, 0, 0, 1, 1, 1, 1], dtype=np.uint32),
        kind=np.zeros(10, dtype=np.uint8),
        district_count=2,
    )
    return Directory("2026-10-14", SCHOOLS, DISTRICTS, points)


def closings(rows: list[tuple[int, int]], day: str, generated_at: str) -> dict[str, Any]:
    """A closings.json day from (school index, status) rows, ascending."""
    gaps, previous = [], -1
    for index, _status in rows:
        gaps.append(index - previous - 1)
        previous = index
    return {
        "generated_at": generated_at,
        "directory": dict(STAMP),
        "days": [{"day": day, "gaps": gaps, "statuses": [status for _, status in rows]}],
    }


def predictions(
    chances: list[float | None], days: tuple[str, str], generated_at: str | None = None
) -> dict[str, Any]:
    """A predictions file, stamped at ``generated_at`` (by default 16:30 UTC on its first day,
    fresh for a picture at 16:37), every district in Central time but the second, in Eastern."""
    rows = []
    for index, chance in enumerate(chances):
        today: dict[str, Any] = (
            {"state": "no_threat"}
            if chance is None
            else {"state": "forecast", "p_no_school": chance}
        )
        zone = "America/New_York" if index == 1 else "America/Chicago"
        rows.append({"district": index, "days": [{"state": "no_threat"}, today], "time_zone": zone})
    stamp = generated_at or f"{days[0]}T16:30:00Z"
    return {"generated_at": stamp, "directory": dict(STAMP), "days": list(days), "districts": rows}


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_the_shown_day_is_today_in_every_contiguous_zone_only() -> None:
    assert today_everywhere(at("2026-12-10T07:59")) is None
    assert today_everywhere(at("2026-12-10T08:00")) == date(2026, 12, 10)
    assert today_everywhere(at("2026-12-11T03:59")) == date(2026, 12, 10)
    assert today_everywhere(at("2026-12-11T04:00")) is None


def test_closings_zoom_to_the_busiest_window_and_say_what_glows() -> None:
    now = at("2026-12-10T12:10")
    rows = [(0, 0), (1, 0), (2, 1), (3, 0), (4, 2), (5, 0), (6, 0), (8, 0), (9, 3)]
    picture = choose(
        chances=True,
        closings_shown=True,
        closings=closings(rows, "2026-12-10", "2026-12-10T12:05:00Z"),
        predictions=None,
        directory=directory(),
        now=now,
    )
    assert picture.kind == "closings"
    assert picture.current
    assert picture.lit == 9
    lat, lon, zoom = (float(part) for part in picture.query.removeprefix("?at=").split(","))
    assert 42.0 < lat < 43.2
    assert -80.1 < lon < -78.5
    # Seven lit schools a few counties apart: closer than the widest view, all in the box.
    assert ZOOM < zoom <= MAX_ZOOM
    shows = picture.shows
    assert "6:10 AM Central time on December 10, 2026" in shows
    # The window holds Buffalo's six and the nearby Pennsylvania one, not MN or TX.
    assert "7 schools glow in this view (5 closed, 1 delayed, 1 remote)" in shows
    # Six of seven in New York; one in Pennsylvania is under the second state's share.
    assert "mostly in New York." in shows
    assert "for weather" not in shows, "a status with no reason named is not said to be weather"
    assert "Across the country the map shows 9 schools" in shows
    assert "updated at 6:05 AM Central time." in shows
    assert "Buffalo" not in shows, "no place below the state is named"
    seen = picture.seen
    assert seen.in_view == Counts(closed=5, delayed=1, remote=1, early_dismissal=0)
    assert seen.states == ("New York",)
    assert seen.lit == 9
    assert seen.closings_read
    assert seen.closings_at == at("2026-12-10T12:05")


def test_an_old_closings_file_is_not_called_current() -> None:
    picture = choose(
        chances=True,
        closings_shown=True,
        closings=closings([(0, 0)], "2026-12-10", "2026-12-10T11:00:00Z"),
        predictions=None,
        directory=directory(),
        now=at("2026-12-10T12:10"),
    )
    assert picture.kind == "closings"
    assert not picture.current
    assert "last updated at 5:00 AM Central time, 70 minutes before the picture" in picture.shows
    assert "does not call them live" in picture.shows


@pytest.mark.parametrize(
    ("file", "now", "read"),
    [
        # Another directory's file is not read by the page: nothing is said about closings.
        (
            {**closings([(0, 0)], "2026-12-10", "2026-12-10T12:05:00Z"), "directory": {}},
            "12:10",
            False,
        ),
        # The hours between days light nothing.
        (closings([(0, 0)], "2026-12-10", "2026-12-10T05:00:00Z"), "05:10", True),
        # Yesterday's rows light nothing today.
        (closings([(0, 0)], "2026-12-09", "2026-12-10T12:05:00Z"), "12:10", True),
        # Practice mode: a 404, nothing is said about closings.
        (None, "12:10", False),
    ],
)
def test_no_lit_school_gives_the_national_map(
    file: dict[str, Any] | None, now: str, read: bool
) -> None:
    picture = choose(
        chances=True,
        closings_shown=True,
        closings=file,
        predictions=None,
        directory=directory(),
        now=at(f"2026-12-10T{now}"),
    )
    assert picture.kind == "national"
    assert picture.query == ""
    assert picture.lit == 0
    assert picture.seen.closings_read is read
    assert ("No school is lit up for weather on the map." in picture.shows) is read
    if not read:
        assert "closing" not in picture.shows.lower()
        assert "lit" not in picture.shows
    assert "dark Snowlight map" in picture.shows
    assert "night" not in picture.shows
    # The site draws no school specks at the national zoom: the words never say it does.
    assert "draws no school specks" in picture.shows
    assert "dot" not in picture.shows


def test_a_high_chance_opens_that_districts_panel() -> None:
    picture = choose(
        chances=True,
        closings_shown=True,
        closings=None,
        predictions=predictions([0.04, 0.37], ("2026-12-09", "2026-12-10"), "2026-12-10T14:50:00Z"),
        directory=directory(),
        now=at("2026-12-10T15:00"),  # 9 AM Central: December 10 is under way, and the file ends
    )
    assert picture.kind == "national"
    assert picture.seen.chance is None, "no chance of a day already under way"
    assert "chance" not in picture.shows
    picture = choose(
        chances=True,
        closings_shown=True,
        closings=None,
        predictions=predictions([0.04, 0.37], ("2026-12-09", "2026-12-10"), "2026-12-09T18:00:00Z"),
        directory=directory(),
        now=at("2026-12-09T18:10"),  # 12:10 PM Central: the next school day is December 10
    )
    assert picture.kind == "district"
    assert picture.query.startswith("?at=")
    assert "district" not in picture.query, "no panel opens: the map alone is pictured"
    assert "schools of a public school district in Minnesota" in picture.shows
    assert "chance of no school on Thursday, December 10 is 37%, the highest of any" in (
        picture.shows
    )
    assert "The map does not draw the chance" in picture.shows
    assert "2700001" not in picture.shows, "no district is named"
    seen = picture.seen
    assert seen.state == "Minnesota"
    assert seen.chance is not None
    assert (seen.chance.text, seen.chance.scope, seen.chance.districts) == ("37%", "district", 2)
    assert seen.focus is not None
    assert seen.in_view is None


def test_a_calm_day_says_the_chance_is_not_in_the_picture() -> None:
    picture = choose(
        chances=True,
        closings_shown=True,
        closings=None,
        predictions=predictions([0.01, 0.01], ("2026-10-26", "2026-10-27")),
        directory=directory(),
        now=at("2026-10-26T16:37"),
    )
    assert picture.kind == "national"
    assert (
        "Not in the picture: Snowlight's chance of no school on Tuesday, October 27 is at most 1%"
        " in every one of the 2 districts with a chance."
    ) in picture.shows
    assert picture.seen.chance is not None
    assert picture.seen.chance.at_most
    assert picture.seen.chance.text == "1%"
    some = choose(
        chances=True,
        closings_shown=True,
        closings=None,
        predictions=predictions([0.06, None], ("2026-10-26", "2026-10-27")),
        directory=directory(),
        now=at("2026-10-26T16:37"),
    )
    assert "highest chance of no school on Tuesday, October 27 in any district is 6%" in some.shows
    assert some.seen.chance is not None
    assert (some.seen.chance.text, some.seen.chance.at_most) == ("6%", False)
    other = choose(
        chances=True,
        closings_shown=True,
        closings=None,
        predictions={**predictions([0.5], ("2026-10-26", "2026-10-27")), "directory": {}},
        directory=directory(),
        now=at("2026-10-26T16:37"),
    )
    assert other.kind == "national"
    assert "chance" not in other.shows, "another directory's chances are not read"


@pytest.mark.parametrize(
    "file",
    [
        {"generated_at": "2026-12-10T12:05:00Z", "directory": dict(STAMP)},
        {"directory": dict(STAMP), "days": []},
        {"generated_at": "noon", "directory": dict(STAMP), "days": []},
        {"generated_at": "2026-12-10T12:05:00", "directory": dict(STAMP), "days": []},
        {
            "generated_at": "2026-12-10T12:05:00Z",
            "directory": dict(STAMP),
            "days": [{"day": "2026-12-10", "gaps": [0, 0], "statuses": [0]}],
        },
        {
            "generated_at": "2026-12-10T12:05:00Z",
            "directory": dict(STAMP),
            "days": [{"day": "2026-12-10", "gaps": [10], "statuses": [0]}],
        },
        {
            "generated_at": "2026-12-10T12:05:00Z",
            "directory": dict(STAMP),
            "days": [{"day": "2026-12-10", "gaps": [0], "statuses": [7]}],
        },
    ],
)
def test_a_malformed_closings_file_is_an_error(file: dict[str, Any]) -> None:
    with pytest.raises(PictureError):
        lit_schools(file, directory(), at("2026-12-10T12:10"))


def test_malformed_predictions_are_an_error() -> None:
    with pytest.raises(PictureError, match="days"):
        choose(
            chances=True,
            closings_shown=True,
            closings=None,
            predictions={"directory": dict(STAMP), "generated_at": "2026-10-26T16:30:00Z"},
            directory=directory(),
            now=at("2026-10-26T16:37"),
        )
    with pytest.raises(PictureError, match="district"):
        choose(
            chances=True,
            closings_shown=True,
            closings=None,
            predictions={
                "directory": dict(STAMP),
                "generated_at": "2026-10-26T16:30:00Z",
                "days": ["2026-10-27"],
                "districts": [7],
            },
            directory=directory(),
            now=at("2026-10-26T16:37"),
        )
    with pytest.raises(PictureError, match="generated_at"):
        choose(
            chances=True,
            closings_shown=True,
            closings=None,
            predictions={"directory": dict(STAMP), "days": ["2026-10-26"], "districts": []},
            directory=directory(),
            now=at("2026-10-26T16:37"),
        )


def test_the_busiest_window_is_repeatable_and_holds_its_points() -> None:
    lon = np.asarray(LON, dtype=np.float64)
    lat = np.asarray(LAT, dtype=np.float64)
    first = busiest_view(lon, lat)
    again = busiest_view(lon[::-1].copy(), lat[::-1].copy())
    assert int(first[1].sum()) == int(again[1].sum()) == 8
    assert first[0] == pytest.approx(again[0])


def test_chances_are_written_as_the_page_writes_them() -> None:
    assert [chance_text(v) for v in (0.004, 0.005, 0.125, 0.37, 0.994, 0.995)] == [
        "<1%",
        "1%",
        "13%",
        "37%",
        "99%",
        ">99%",
    ]


def test_the_map_projection_round_trips_and_matches_maplibre() -> None:
    x, y = project(np.asarray([0.0, -95.0]), np.asarray([0.0, 40.0]), 0.0)
    assert (float(x[0]), float(y[0])) == pytest.approx((256.0, 256.0))
    lon, lat = unproject(float(x[1]) * 8, float(y[1]) * 8, 3.0)
    assert (lon, lat) == pytest.approx((-95.0, 40.0))


def test_a_district_is_framed_on_the_left_with_its_box() -> None:
    framed = district_frame(directory(), 0)
    assert framed is not None
    query, box = framed
    lat, lon, zoom = (float(part) for part in query.removeprefix("?at=").split(","))
    assert 7.0 <= zoom <= 12.0
    # The six Buffalo schools sit around DISTRICT_X across the picture, inside the frame.
    assert (box.x0 + box.x1) / 2 == pytest.approx(DISTRICT_X * WIDTH, abs=1)
    assert 0 <= box.x0 < box.x1 <= 800
    assert 0 <= box.y0 < box.y1 <= 900
    # The center is east of the schools, so they land left of the middle.
    assert lon > -78.775
    assert 42.7 < lat < 43.0
    empty = Directory(
        "2026-10-14",
        SCHOOLS,
        (*DISTRICTS, "3600009"),
        directory().points,
    )
    assert district_frame(empty, 2) is None


def test_a_region_picture_is_calm_only() -> None:
    picture = region(
        query="?at=40.9,-80.6,6.1",
        place="the Great Lakes and the Northeast",
        closings=None,
        directory=directory(),
        now=at("2026-10-26T04:44"),
        closings_shown=True,
    )
    assert picture.kind == "region"
    assert picture.seen.place == "the Great Lakes and the Northeast"
    assert "schools drawn as faint white specks" in picture.shows
    assert "closing" not in picture.shows.lower()
    with pytest.raises(PictureError, match="lit"):
        region(
            query="?at=40.9,-80.6,6.1",
            place="the Great Lakes and the Northeast",
            closings=closings([(0, 0)], "2026-12-10", "2026-12-10T12:05:00Z"),
            directory=directory(),
            now=at("2026-12-10T12:10"),
            closings_shown=True,
        )


RUNS = ("13:07", "17:37", "00:41")
"""The three scheduled runs, UTC (.github/workflows/social-post.yml); 00:41 is the evening of
the Central day before."""


def test_the_calm_regions_are_city_lights_rotated_by_the_run_slot() -> None:
    """Every region is at a zoom where the site draws school specks (5 to 10, never the bare
    national map), named plainly, and each of a day's three runs opens on a different one,
    in daylight time and in standard time, and the next day carries on."""
    assert len(REGIONS) >= 5
    for place in REGIONS:
        assert 5 < place.zoom < 10, place
        assert place.query.startswith("?at=")
        assert len(place.place) <= 60
    for day, evening in (("2026-10-27", "2026-10-28"), ("2026-11-10", "2026-11-11")):
        times = [at(f"{day}T{RUNS[0]}"), at(f"{day}T{RUNS[1]}"), at(f"{evening}T{RUNS[2]}")]
        slots = [slot_of(moment) for moment in times]
        assert slots == [slots[0], slots[0] + 1, slots[0] + 2], (day, slots)
        firsts = [calm_regions(moment)[0] for moment in times]
        assert len(set(firsts)) == 3, (day, firsts)
        # A run GitHub starts 40 minutes late keeps its slot.
        late = times[0].replace(minute=47)
        assert calm_regions(late)[0] == firsts[0]
    first = calm_regions(at("2026-10-27T13:07"))
    assert sorted(first, key=REGIONS.index) == list(REGIONS)
    assert calm_regions(at("2026-10-28T13:07"))[0] == calm_regions(at("2026-10-28T00:41"))[1]


def _ids(counts: dict[str, int], private: int = 0) -> list[str]:
    """SYNTHETIC public ids for each state code's count, and private ids (no state)."""
    ids = [f"{code}{index:010d}" for code, count in counts.items() for index in range(count)]
    return ids + [f"A{index:07d}" for index in range(private)]


# The public schools in each calm region's view in the deployed directory (Oct 27, 2026,
# points.021e180ccc.bin), by state: the top three, then the rest as one state each. Sums from
# the probe that found 'mostly' false for five of seven regions. They hold for these views
# only (REAL_REGION_QUERIES, pinned below): a change to a region's place or zoom fails
# test_the_region_share_snapshot_is_of_the_regions_views until the shares are probed again, and
# with the deployed directory at hand (SNOWLIGHT_SCHOOLS, or web/public/data/schools after a
# local build) test_the_real_directory_still_gives_the_snapshot_s_states recomputes them.
REAL_REGION_QUERIES = {
    "the Northeast corridor": "?at=40.6000,-74.4000,6.6",
    "the Great Lakes": "?at=42.3000,-85.2000,6.3",
    "the Mid-Atlantic": "?at=38.9000,-77.6000,7",
    "the Texas triangle": "?at=30.6000,-96.9000,6.8",
    "the Front Range": "?at=39.7000,-105.0000,7.4",
    "the Pacific Northwest": "?at=46.9000,-122.6000,7",
    "Southern California": "?at=33.9000,-117.8000,7.4",
}
REAL_REGION_SHARES = {
    "the Northeast corridor": ({"36": 4080, "42": 2772, "34": 2481}, 15330, []),
    "the Great Lakes": ({"17": 3508, "26": 3249, "39": 3072}, 15356, []),
    "the Mid-Atlantic": ({"42": 2276, "34": 1804, "36": 1638}, 9833, []),
    "the Texas triangle": ({"48": 6531, "22": 598}, 7129, ["Texas"]),
    "the Front Range": ({"08": 1605, "20": 12, "56": 10}, 1634, ["Colorado"]),
    "the Pacific Northwest": ({"53": 2076, "41": 556}, 2632, ["Washington", "Oregon"]),
    "Southern California": ({"06": 5318, "04": 100, "32": 2}, 5420, ["California"]),
}


@pytest.mark.parametrize("place", sorted(REAL_REGION_SHARES))
def test_mostly_is_said_only_of_states_that_hold_most_of_a_real_region(place: str) -> None:
    """The deployed directory's shares for every calm region: "mostly" only when the states
    named hold more than half of the view's public schools, and a second state only with a
    real share (no "Colorado and Kansas" for 12 Kansas schools of 1,634)."""
    assert place in {region.place for region in REGIONS}
    top, total, named = REAL_REGION_SHARES[place]
    rest = total - sum(top.values())
    # The rest spread one school a state code no larger than the third (never a top state).
    spread = {f"{60 + index % 30:02d}": 0 for index in range(30)}
    for index in range(rest):
        spread[f"{60 + index % 30:02d}"] += 1
    ids = _ids(top) + [f"{code}{index:010d}" for code, n in spread.items() for index in range(n)]
    assert _states(ids) == named


def test_the_region_share_snapshot_is_of_the_regions_views() -> None:
    assert {view.place: view.query for view in REGIONS} == REAL_REGION_QUERIES


def _deployed_schools() -> Path | None:
    for folder in (
        os.environ.get("SNOWLIGHT_SCHOOLS"),
        Path(__file__).resolve().parents[3] / "web" / "public" / "data" / "schools",
    ):
        if folder and any(Path(folder).glob("points.*.bin")):
            return Path(folder)
    return None


@pytest.mark.skipif(_deployed_schools() is None, reason="no deployed school directory here")
def test_the_real_directory_still_gives_the_snapshot_s_states() -> None:
    folder = _deployed_schools()
    assert folder is not None
    real = directory_of(
        next(folder.glob("meta.*.json")).read_bytes(),
        next(folder.glob("points.*.bin")).read_bytes(),
    )
    for view in REGIONS:
        assert view_states(real, view.query) == REAL_REGION_SHARES[view.place][2], view


def test_mostly_needs_more_than_half_and_a_second_state_a_real_share() -> None:
    assert _states(_ids({"36": 45, "42": 27, "34": 28})) == ["New York", "New Jersey"]
    assert _states(_ids({"36": 26, "42": 18, "34": 16, "09": 14, "25": 13, "44": 13})) == []
    assert _states(_ids({"36": 51, "42": 14, "34": 35})) == ["New York", "New Jersey"]
    assert _states(_ids({"36": 60, "42": 14, "34": 13, "09": 13})) == ["New York"]
    assert _states(_ids({"36": 50, "42": 10, "34": 40})) == ["New York", "New Jersey"]
    assert _states(_ids({"36": 50, "42": 50})) == ["New York", "Pennsylvania"]
    assert _states(_ids({"36": 50}, private=50)) == [], "a private school counts against it"
    assert _states(_ids({"36": 2}, private=1)) == ["New York"]
    assert _states(_ids({}, private=3)) == []
    assert _states([]) == []


def test_a_region_s_description_names_the_states_of_the_schools_in_view() -> None:
    assert view_states(directory(), "?at=42.9,-78.8,7") == ["New York", "Pennsylvania"]
    assert view_states(directory(), "?at=30.27,-97.74,7.5") == ["Texas"]
    assert view_states(directory(), "") == []
    picture = region(
        query="?at=42.9,-78.8,7",
        place="the Great Lakes",
        closings=None,
        directory=directory(),
        now=at("2026-10-27T14:00"),
        closings_shown=True,
    )
    assert "over the Great Lakes, mostly New York and Pennsylvania, taken at" in picture.shows
    assert "Buffalo" not in picture.shows
    assert "District" not in picture.shows


def test_the_clock_carries_its_zone() -> None:
    assert clock(at("2026-12-10T12:05")) == "6:05 AM CT"
    assert clock(at("2026-07-10T23:59")) == "6:59 PM CT"


@pytest.mark.parametrize(
    ("now", "generated_at"),
    [
        ("2026-12-10T12:10", "2026-12-10T08:00:00Z"),  # a reader stopped 4 hours ago
        ("2026-12-11T13:00", "2026-12-10T07:00:00Z"),  # yesterday's file only
    ],
)
def test_a_stale_file_with_nothing_lit_says_nothing_and_is_not_current(
    now: str, generated_at: str
) -> None:
    file = closings([(0, 0)], "2026-12-09", generated_at)
    picture = choose(
        chances=True,
        closings_shown=True,
        closings=file,
        predictions=None,
        directory=directory(),
        now=at(now),
    )
    assert picture.kind == "national"
    assert not picture.current, "a stale calm map is never presented as current"
    assert "lit up" not in picture.shows
    assert "closing" not in picture.shows.lower()
    calm = region(
        query="?at=43,-79,6",
        place="the Great Lakes",
        closings=file,
        directory=directory(),
        now=at(now),
        closings_shown=True,
    )
    assert not calm.current
    assert "lit up" not in calm.shows


def test_a_fresh_file_with_nothing_lit_says_so_and_is_current() -> None:
    file = closings([(0, 0)], "2026-12-09", "2026-12-10T12:05:00Z")
    picture = choose(
        chances=True,
        closings_shown=True,
        closings=file,
        predictions=None,
        directory=directory(),
        now=at("2026-12-10T12:10"),
    )
    assert picture.current
    assert "No school is lit up for weather on the map." in picture.shows


def test_a_stale_predictions_file_shows_no_chance() -> None:
    for stamp in ("2026-10-26T14:00:00Z", "2026-10-26T17:00:00Z"):  # 2.6 h old; 23 min ahead
        picture = choose(
            chances=True,
            closings_shown=True,
            closings=None,
            predictions=predictions([0.5, 0.01], ("2026-10-26", "2026-10-27"), stamp),
            directory=directory(),
            now=at("2026-10-26T16:37"),
        )
        assert picture.kind == "national"
        assert "chance" not in picture.shows
        assert picture.seen.chance is None


def test_the_chance_named_is_the_next_school_day_not_yet_under_way() -> None:
    week = predictions([0.01, 0.37], ("2026-10-26", "2026-10-27"))
    # 11:27 AM Central on Monday: Monday is under way everywhere, so the card names Tuesday.
    assert chance_day(week, at("2026-10-26T16:27")) == date(2026, 10, 27)
    # 9 PM Central on Sunday: Monday's 7:30 AM is still ahead everywhere.
    assert chance_day(week, at("2026-10-26T02:00")) == date(2026, 10, 26)
    # 5:30 AM Eastern on Monday, before most districts call it: still ahead in both.
    assert chance_day(week, at("2026-10-26T09:30")) == date(2026, 10, 26)
    # 7:29 AM Eastern: still ahead in both.
    assert chance_day(week, at("2026-10-26T11:29")) == date(2026, 10, 26)
    # 7:30 AM Eastern on Monday: under way in the east, not yet in Central. Monday is named
    # only while it is ahead in every district, so no district is left out by its clock.
    assert chance_day(week, at("2026-10-26T11:30")) == date(2026, 10, 27)
    # From 7:30 AM Eastern on Tuesday every day the file holds is under way: no chance at all.
    assert chance_day(week, at("2026-10-27T11:29")) == date(2026, 10, 27)
    assert chance_day(week, at("2026-10-27T11:30")) is None
    # A file whose days skip the weekend: on Saturday the next school day is its Monday.
    weekend = predictions([0.01, 0.2], ("2026-10-26", "2026-10-27"))
    assert chance_day(weekend, at("2026-10-24T18:00")) == date(2026, 10, 26)
    # A district with no zone, or one this machine does not know, has no clock: the page says
    # no day of it, so it holds no day back. With no clock at all no day is named.
    odd = {**week, "districts": [{"district": 0, "days": []}, {"time_zone": "Mars/Base"}]}
    assert chance_day(odd, at("2026-10-26T11:30")) is None
    central = {**odd, "districts": [*odd["districts"], {"time_zone": "America/Chicago"}]}
    assert chance_day(central, at("2026-10-26T12:29")) == date(2026, 10, 26)
    assert chance_day(central, at("2026-10-26T12:30")) == date(2026, 10, 27)
    with pytest.raises(PictureError, match="a district is malformed"):
        chance_day({**week, "districts": [7]}, at("2026-10-26T09:30"))
    with pytest.raises(PictureError, match="a day is malformed"):
        chance_day({**week, "days": ["Monday"]}, at("2026-10-26T09:30"))
    with pytest.raises(PictureError, match="districts is missing"):
        chance_day({"days": ["2026-10-26"]}, at("2026-10-26T09:30"))


@pytest.mark.parametrize(
    ("zone", "fall", "spring"),
    [
        # 07:30 on Sunday Nov 1 2026 (the clocks go back) and on Sunday Mar 14 2027 (forward).
        ("America/New_York", "2026-11-01T12:30", "2027-03-14T11:30"),
        ("America/Chicago", "2026-11-01T13:30", "2027-03-14T12:30"),
        ("America/Denver", "2026-11-01T14:30", "2027-03-14T13:30"),
        ("America/Phoenix", "2026-11-01T14:30", "2027-03-14T14:30"),
        ("America/Los_Angeles", "2026-11-01T15:30", "2027-03-14T14:30"),
        ("America/Anchorage", "2026-11-01T16:30", "2027-03-14T15:30"),
        ("Pacific/Honolulu", "2026-11-01T17:30", "2027-03-14T17:30"),
    ],
)
def test_a_day_is_under_way_from_07_30_in_every_zone_on_the_days_clocks_change(
    zone: str, fall: str, spring: str
) -> None:
    assert time(7, 30) == SCHOOL_STARTS
    for first, cutoff in (("2026-11-01", fall), ("2027-03-14", spring)):
        after = (date.fromisoformat(first) + timedelta(days=1)).isoformat()
        file = {"days": [first, after], "districts": [{"time_zone": zone}]}
        assert chance_day(file, at(cutoff) - timedelta(minutes=1)) == date.fromisoformat(first)
        assert chance_day(file, at(cutoff)) == date.fromisoformat(after)


# Three districts for the per-district rule: New York's six schools (0), Pennsylvania's two
# and Minnesota's one (1), Texas's one (2).
THREE = {"generated_on": "2026-10-14", "schools": 10, "districts": 3}


def three() -> Directory:
    points = Points(
        lon_e6=np.asarray([round(v * 1e6) for v in LON], dtype=np.int32),
        lat_e6=np.asarray([round(v * 1e6) for v in LAT], dtype=np.int32),
        district=np.asarray([0, 0, 0, 0, 0, 0, 1, 1, 1, 2], dtype=np.uint32),
        kind=np.zeros(10, dtype=np.uint8),
        district_count=3,
    )
    return Directory("2026-10-14", SCHOOLS, ("3600001", "2700001", "4800001"), points)


def outlooks(
    rows: list[tuple[str, list[float | None], str | None]],
    days: tuple[str, str],
    generated_at: str,
) -> dict[str, Any]:
    """A predictions file of :func:`three`'s districts, in order: each its zone, its chance on
    each day (``None``: no threat) and its first buses on the first day (UTC, or ``None``)."""
    districts = []
    for index, (zone, chances, buses) in enumerate(rows):
        entries: list[dict[str, Any]] = [
            {"state": "no_threat"}
            if chance is None
            else {"state": "forecast", "p_no_school": chance}
            for chance in chances
        ]
        if buses is not None:
            entries[0]["buses_at"] = buses
        districts.append({"district": index, "time_zone": zone, "days": entries})
    return {
        "generated_at": generated_at,
        "directory": dict(THREE),
        "days": list(days),
        "districts": districts,
    }


THURSDAY = ("2026-12-10", "2026-12-11")
NY, CT, PT = "America/New_York", "America/Chicago", "America/Los_Angeles"


def picture_at(file: dict[str, Any], now: str, closings_file: dict[str, Any] | None = None) -> Any:
    return choose(
        chances=True,
        closings_shown=closings_file is not None,
        closings=closings_file,
        predictions=file,
        directory=three(),
        now=at(now),
    )


def taken_of(picture: Any) -> Taken:
    return Taken(
        kind=picture.kind,
        query=picture.query,
        shows=picture.shows,
        taken_at=picture.taken_at,
        current=picture.current,
        lit=picture.lit,
        seen=picture.seen,
        file="picture.png",
    )


OVER_ALL = re.compile(r"\b(?:any|every) district\b|districts with a chance")
"""Words that compare a chance over every district holding one for its day."""


def words_of(picture: Any) -> list[str]:
    """What a post may say of the picture: its description and the dev-log card's alt text."""
    return [picture.shows, alt_text(taken_of(picture), "dev-log", fallback=False)]


def assert_compared_truly(picture: Any, file: dict[str, Any]) -> None:
    """No words call a chance the highest of any district, or say it of every district, while
    a district holding a forecast for that day in the file was left out or had a higher one."""
    chance = picture.seen.chance
    if chance is None:
        assert not any("chance" in text for text in words_of(picture)), picture.shows
        return
    column = file["days"].index(chance.day.isoformat())
    held = [
        row["days"][column]["p_no_school"]
        for row in file["districts"]
        if row["days"][column].get("state") == "forecast"
    ]
    named = 1 if chance.at_most else int(chance.text.strip("%<>"))
    for text in words_of(picture):
        if chance.left_out > 0:
            assert not OVER_ALL.search(text), text
            assert "still giv" in text, text
        elif OVER_ALL.search(text):
            assert len(held) == chance.districts, (text, held)
            assert all(round(value * 100) <= named for value in held), (text, held)


def test_the_morning_card_names_tomorrow_once_today_is_under_way_in_any_district() -> None:
    # 13:07 UTC, the morning run: 7:07 AM Central, 8:07 AM Eastern on Thursday Dec 10. New
    # York's Thursday is under way on its own clock, so Thursday is no longer named at all:
    # the card names Friday, as every Eastern panel does, with every district counted, and
    # never calls a Central Thursday chance the highest while New York's 93% was in the file.
    file = outlooks(
        [(NY, [0.93, 0.12], None), (CT, [0.2, 0.1], None), (CT, [0.15, 0.1], None)],
        THURSDAY,
        "2026-12-10T13:00:00Z",
    )
    for now in ("2026-12-10T12:45", "2026-12-10T13:07", "2026-12-10T13:29"):
        picture = picture_at(file, now)
        assert picture.kind == "district", now
        assert "in New York" in picture.shows
        assert "Friday, December 11 is 12%, the highest of any district that day" in (picture.shows)
        assert "Thursday" not in picture.shows
        assert picture.seen.chance is not None
        assert (picture.seen.chance.day, picture.seen.chance.districts) == (
            date(2026, 12, 11),
            3,
        )
        assert picture.seen.chance.left_out == 0
        assert_compared_truly(picture, file)
    # 7:29 AM Eastern: Thursday is still ahead everywhere, and New York's 93% the highest.
    early = picture_at({**file, "generated_at": "2026-12-10T12:20:00Z"}, "2026-12-10T12:29")
    assert "in New York" in early.shows
    assert "Thursday, December 10 is 93%, the highest of any district that day" in early.shows
    assert_compared_truly(early, file)
    # 7:30 AM Eastern: Friday, and Minnesota's Thursday, still ahead on its panel, is not
    # compared over: no Central Thursday chance is called the highest.
    turned = picture_at({**file, "generated_at": "2026-12-10T12:20:00Z"}, "2026-12-10T12:30")
    assert "Friday, December 11 is 12%" in turned.shows
    # The calm line: New York's 5% Thursday is not under the "at most 1%" said of Thursday,
    # since Thursday is not named once New York is under way.
    calm = outlooks(
        [(NY, [0.05, 0.01], None), (CT, [0.005, 0.01], None), (CT, [0.003, 0.01], None)],
        THURSDAY,
        "2026-12-10T13:00:00Z",
    )
    line = picture_at(calm, "2026-12-10T13:07")
    assert line.kind == "national"
    assert "chance of no school on Friday, December 11 is at most 1% in every one of the 3" in (
        line.shows
    )
    assert line.seen.chance is not None
    assert (line.seen.chance.text, line.seen.chance.districts) == ("1%", 3)
    assert_compared_truly(line, calm)
    assert "at most 1% in every district" in alt_text(taken_of(line), "dev-log", fallback=False)


def test_no_minute_of_a_winter_day_compares_a_chance_over_a_district_left_out() -> None:
    # Every 7 minutes for a day, with a higher Eastern chance each day, a Central and a
    # Pacific district, and a file stamped 5 minutes before: no description or alt text calls
    # a chance the highest of any district, or says it of every district, unless every
    # district holding one for that day counted and none held more.
    files: list[list[tuple[str, list[float | None], str | None]]] = [
        [(NY, [0.93, 0.12], None), (CT, [0.2, 0.1], None), (PT, [0.15, 0.4], None)],
        [(NY, [0.05, 0.009], None), (CT, [0.005, 0.003], None), (PT, [0.003, 0.002], None)],
        [(NY, [0.9, 0.95], "2026-12-10T11:45:00Z"), (CT, [0.3, 0.2], None), (PT, [0.2, 0.1], None)],
    ]
    named: set[date] = set()
    for rows in files:
        moment = at("2026-12-10T06:00")
        while moment < at("2026-12-11T06:00"):
            stamp = (moment - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
            file = outlooks(rows, THURSDAY, stamp)
            picture = picture_at(file, moment.strftime("%Y-%m-%dT%H:%M"))
            assert_compared_truly(picture, file)
            if picture.seen.chance is not None:
                named.add(picture.seen.chance.day)
                # The day named is not under way in any district.
                for zone, _, _ in rows:
                    starts = datetime.combine(picture.seen.chance.day, SCHOOL_STARTS)
                    assert moment < starts.replace(tzinfo=ZoneInfo(zone)), (moment, zone)
            moment += timedelta(minutes=7)
    assert named == {date(2026, 12, 10), date(2026, 12, 11)}


def test_a_day_is_not_named_from_the_minute_buses_run_before_07_30_anywhere() -> None:
    # New York's buses run at 6:45 AM Eastern (11:45 UTC): from that minute its Thursday is
    # under way, so Thursday is no longer named anywhere.
    file = outlooks(
        [
            (NY, [0.93, 0.12], "2026-12-10T11:45:00Z"),
            (CT, [0.5, 0.1], None),
            (CT, [0.2, 0.1], None),
        ],
        THURSDAY,
        "2026-12-10T11:40:00Z",
    )
    before = picture_at(file, "2026-12-10T11:44")
    assert "in New York" in before.shows
    assert "Thursday, December 10 is 93%" in before.shows
    at_buses = picture_at(file, "2026-12-10T11:45")
    assert at_buses.seen.chance is not None
    assert at_buses.seen.chance.day == date(2026, 12, 11)
    assert "93%" not in at_buses.shows
    assert_compared_truly(at_buses, file)


def test_a_district_is_framed_beside_the_next_day_from_the_minute_its_buses_run() -> None:
    # 13:00 UTC, Friday named (Thursday under way in the east). Minnesota's Friday 50% is the
    # highest; its buses run Thursday at 7 AM Central (13:00 UTC): before that its panel
    # still headlines Thursday, so no picture frames it beside Friday; from that minute on,
    # its panel headlines Friday and the picture frames it.
    file = outlooks(
        [
            (NY, [0.93, 0.12], None),
            (CT, [0.3, 0.5], "2026-12-10T13:00:00Z"),
            (CT, [0.2, 0.1], None),
        ],
        THURSDAY,
        "2026-12-10T12:50:00Z",
    )
    before = picture_at(file, "2026-12-10T12:59")
    assert before.kind == "national"
    assert "highest chance of no school on Friday, December 11 in any district is 50%." in (
        before.shows
    )
    at_buses = picture_at(file, "2026-12-10T13:00")
    assert at_buses.kind == "district"
    assert "in Minnesota" in at_buses.shows
    assert "Friday, December 11 is 50%, the highest of any district that day" in at_buses.shows
    for picture in (before, at_buses):
        assert_compared_truly(picture, file)


def test_a_district_with_no_clock_is_left_out_and_never_compared_over() -> None:
    # New York gives no zone and Minnesota one this machine does not know: the page says no
    # day of either, so neither counts, and the 20% of Texas, the only one counted, is never
    # called the highest of any district while they hold 90% and 60%.
    file = outlooks(
        [(NY, [0.9, 0.1], None), (CT, [0.6, 0.1], None), (CT, [0.2, 0.1], None)],
        THURSDAY,
        "2026-12-10T12:00:00Z",
    )
    file["districts"][0]["time_zone"] = None
    file["districts"][1]["time_zone"] = "Mars/Base"
    picture = picture_at(file, "2026-12-10T12:05")
    assert picture.seen.chance is not None
    assert (picture.seen.chance.districts, picture.seen.chance.left_out) == (1, 2)
    assert picture.kind == "district"
    assert "in Texas" in picture.shows
    assert (
        "Thursday, December 10 is 20%, and it is the only district that still gives a chance "
        "for that day." in picture.shows
    )
    assert_compared_truly(picture, file)
    # Two counted: the highest of the two, by count.
    file["districts"][1]["time_zone"] = CT
    two = picture_at(file, "2026-12-10T12:05")
    assert (
        "Thursday, December 10 is 60%, the highest of the 2 districts that still give a chance "
        "for that day." in two.shows
    )
    assert "the highest of the 2 districts that still give one" in (
        alt_text(taken_of(two), "dev-log", fallback=False)
    )
    assert_compared_truly(two, file)


def test_a_day_a_district_decided_is_never_named_by_its_chance() -> None:
    # 6:40 PM Central on Thursday: Friday's chances. New York's six schools all closed for
    # Friday already: its 90% is spent, so the card names Minnesota's 30%, the highest of the
    # two districts that still give one, never of any district.
    file = outlooks(
        [(NY, [None, 0.9], None), (CT, [None, 0.3], None), (CT, [None, 0.2], None)],
        THURSDAY,
        "2026-12-11T00:30:00Z",
    )
    closed = closings([(i, 0) for i in range(6)], "2026-12-11", "2026-12-11T00:35:00Z")
    closed["directory"] = dict(THREE)
    picture = picture_at(file, "2026-12-11T00:40", closed)
    assert picture.kind == "district"
    assert "in Minnesota" in picture.shows
    assert (
        "Friday, December 11 is 30%, the highest of the 2 districts that still give a chance "
        "for that day." in picture.shows
    )
    assert "any district" not in picture.shows
    assert "90%" not in picture.shows
    assert picture.seen.chance is not None
    assert (picture.seen.chance.districts, picture.seen.chance.left_out) == (2, 1)
    alt = alt_text(taken_of(picture), "dev-log", fallback=False)
    assert "whose chance of no school Friday is 30%, the highest of the 2 districts" in alt
    assert "any district" not in alt
    assert_compared_truly(picture, file)
    # The calm national line says it of the districts still giving one, by count.
    low = outlooks(
        [(NY, [None, 0.9], None), (CT, [None, 0.004], None), (CT, [None, 0.002], None)],
        THURSDAY,
        "2026-12-11T00:30:00Z",
    )
    calm = picture_at(low, "2026-12-11T00:40", closed)
    assert calm.kind == "national"
    assert (
        "Friday, December 11 is at most 1% in every one of the 2 districts that still give one."
        in calm.shows
    )
    assert "at most 1% in the 2 districts that still give one" in (
        alt_text(taken_of(calm), "dev-log", fallback=False)
    )
    assert_compared_truly(calm, low)
    mild = outlooks(
        [(NY, [None, 0.9], None), (CT, [None, 0.05], None), (CT, [None, 0.02], None)],
        THURSDAY,
        "2026-12-11T00:30:00Z",
    )
    some_high = picture_at(mild, "2026-12-11T00:40", closed)
    assert (
        "highest chance of no school on Friday, December 11 among the 2 districts that still "
        "give one is 5%." in some_high.shows
    )
    assert_compared_truly(some_high, mild)
    # One New York school closed: the others' panels still give 90%, so it is the highest,
    # but no picture frames the district beside a school that decided the day.
    one = closings([(0, 0)], "2026-12-11", "2026-12-11T00:35:00Z")
    one["directory"] = dict(THREE)
    some = picture_at(file, "2026-12-11T00:40", one)
    assert some.kind == "national"
    assert "highest chance of no school on Friday, December 11 in any district is 90%." in (
        some.shows
    )
    assert_compared_truly(some, file)
    # With closings not LIVE the file is not read: nothing spends the chance (the page it is
    # taken of is served no closings either).
    off = choose(
        chances=True,
        closings_shown=False,
        closings=closed,
        predictions=file,
        directory=three(),
        now=at("2026-12-11T00:40"),
    )
    assert "in New York" in off.shows
    # A decided today, in the hours the map lights no day (2 AM Eastern), spends it as well.
    today = outlooks(
        [(NY, [0.9, 0.1], None), (CT, [0.4, 0.1], None), (CT, [0.2, 0.1], None)],
        THURSDAY,
        "2026-12-10T06:50:00Z",
    )
    night = closings([(i, 0) for i in range(6)], "2026-12-10", "2026-12-10T06:55:00Z")
    night["directory"] = dict(THREE)
    late = picture_at(today, "2026-12-10T07:00", night)
    assert "in Minnesota" in late.shows
    assert "Thursday, December 10 is 40%, the highest of the 2 districts" in late.shows
    assert_compared_truly(late, today)


def test_a_district_still_on_an_earlier_day_is_not_pictured_beside_a_later_one() -> None:
    # 15:00 UTC: 7 AM Pacific, Thursday under way in the east and Central, so Friday is named.
    # Texas, here on Pacific time, still shows its Thursday chance on its own panel: its Friday
    # 60% is the highest Friday chance, so it is given, but no picture frames it beside Friday.
    file = outlooks(
        [(NY, [0.9, 0.1], None), (CT, [0.8, 0.15], None), (PT, [0.4, 0.6], None)],
        THURSDAY,
        "2026-12-10T14:50:00Z",
    )
    picture = picture_at(file, "2026-12-10T15:00")
    assert picture.kind == "national"
    assert "highest chance of no school on Friday, December 11 in any district is 60%." in (
        picture.shows
    )
    assert picture.seen.chance is not None
    assert picture.seen.chance.districts == 3
    # 7:30 AM Pacific: its Thursday is under way too, and its panel headlines Friday.
    framed = picture_at(file, "2026-12-10T15:30")
    assert framed.kind == "district"
    assert "in Texas" in framed.shows
    assert "Friday, December 11 is 60%" in framed.shows


def test_at_11_27_on_monday_the_card_and_description_name_tuesday() -> None:
    picture = choose(
        chances=True,
        closings_shown=True,
        closings=None,
        predictions=predictions([0.01, 0.01], ("2026-10-26", "2026-10-27"), "2026-10-26T16:07:00Z"),
        directory=directory(),
        now=at("2026-10-26T16:27"),
    )
    assert picture.seen.chance is not None
    assert picture.seen.chance.day == date(2026, 10, 27)
    assert "Tuesday, October 27" in picture.shows
    assert "Monday" not in picture.shows
    picture = choose(
        chances=True,
        closings_shown=True,
        closings=None,
        predictions=predictions([0.01, 0.37], ("2026-10-26", "2026-10-27"), "2026-10-26T01:50:00Z"),
        directory=directory(),
        now=at("2026-10-26T02:00"),  # 9 PM Central on Sunday
    )
    assert picture.kind == "national", "Monday's column holds no chance in this file"
    assert picture.seen.chance is None
    picture = choose(
        chances=True,
        closings_shown=True,
        closings=None,
        predictions=predictions([0.01, 0.37], ("2026-12-10", "2026-12-11"), "2026-12-10T20:50:00Z"),
        directory=directory(),
        now=at("2026-12-10T21:00"),
    )
    assert picture.kind == "district"
    assert "Friday, December 11 is 37%" in picture.shows


def test_while_chances_are_testing_the_picture_gives_none() -> None:
    """Rule F (SYNTHETIC predictions): a 74% district and a 1% nation, with chances TESTING,
    give the national map, and its description and facts hold no chance at all."""
    file = predictions([0.74, 0.01], ("2026-12-09", "2026-12-10"), "2026-12-09T18:00:00Z")
    now = at("2026-12-09T18:10")
    shown = choose(
        chances=True,
        closings_shown=True,
        closings=None,
        predictions=file,
        directory=directory(),
        now=now,
    )
    assert shown.kind == "district", "the same files with chances LIVE give the district"
    assert "74%" in shown.shows
    hidden = choose(
        chances=False,
        closings_shown=True,
        closings=None,
        predictions=file,
        directory=directory(),
        now=now,
    )
    assert hidden.kind == "national"
    assert hidden.query == ""
    assert hidden.seen.chance is None
    for word in ("%", "percent", "chance", "odds", "74", "highest"):
        assert word not in hidden.shows.lower(), word
    # The predictions are not read at all: a malformed file changes nothing.
    broken = choose(
        chances=False,
        closings_shown=True,
        closings=None,
        predictions={"days": 3},
        directory=directory(),
        now=now,
    )
    assert broken.shows == hidden.shows


def test_each_lit_school_in_view_has_its_spot_in_the_picture() -> None:
    rows = [(0, 0), (1, 0), (2, 1), (3, 0), (4, 2), (5, 0), (6, 0), (8, 0), (9, 3)]
    picture = choose(
        chances=False,
        closings_shown=True,
        closings=closings(rows, "2026-12-10", "2026-12-10T12:05:00Z"),
        predictions=None,
        directory=directory(),
        now=at("2026-12-10T12:10"),
    )
    spots = picture.seen.spots
    assert picture.seen.in_view is not None
    assert len(spots) == picture.seen.in_view.total == 7
    assert all(0 <= x < 1600 and 0 <= y < 900 for x, y in spots)


def test_while_closings_are_not_live_lit_schools_give_the_calm_national_map() -> None:
    """The closings switch (SYNTHETIC closings): a file lighting nine schools today, while
    the facts file marks closings COMING, gives the national map with nothing said about
    closings: no count, no state, no glow, not even "no school is lit up"."""
    rows = [(0, 0), (1, 0), (2, 1), (3, 0), (4, 2), (5, 0), (6, 0), (8, 0), (9, 3)]
    file = closings(rows, "2026-12-10", "2026-12-10T12:05:00Z")
    picture = choose(
        chances=False,
        closings_shown=False,
        closings=file,
        predictions=None,
        directory=directory(),
        now=at("2026-12-10T12:10"),
    )
    assert picture.kind == "national"
    assert picture.lit == 0
    assert picture.current
    seen = picture.seen
    assert (seen.in_view, seen.states, seen.lit, seen.spots) == (None, (), 0, ())
    assert not seen.closings_read
    assert seen.closings_at is None
    assert not mentions_closings(picture.shows), picture.shows
    for word in ("New York", "Pennsylvania", "9", "lit", "glow"):
        assert word not in picture.shows
    calm = region(
        query="?at=43,-79,6",
        place="the Great Lakes",
        closings=file,
        directory=directory(),
        now=at("2026-12-10T12:10"),
        closings_shown=False,
    )
    assert calm.kind == "region"
    assert not mentions_closings(calm.shows)
    assert not calm.seen.closings_read


def test_few_lit_schools_fill_the_card_zoomed_in_with_every_one_in_the_box(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two lit schools a few miles apart (SYNTHETIC), in a place dense with schools (no
    minimum of specks to meet): the view zooms in as far as :data:`MAX_ZOOM` allows, both in
    the middle box, so their glow and the specks around them fill the card instead of a dot
    in a dark country."""
    monkeypatch.setattr("snowlight.social.picture.MIN_SPECKS", 0)
    picture = choose(
        chances=False,
        closings_shown=True,
        closings=closings([(0, 0), (1, 0)], "2026-12-10", "2026-12-10T12:05:00Z"),
        predictions=None,
        directory=directory(),
        now=at("2026-12-10T12:10"),
    )
    zoom = float(picture.query.rsplit(",", 1)[1])
    assert zoom == MAX_ZOOM
    spots = picture.seen.spots
    assert len(spots) == 2
    for x, y in spots:
        assert abs(x - WIDTH / 2) <= FIT_BOX[0] / 2 + 1
        assert abs(y - HEIGHT / 2) <= FIT_BOX[1] / 2 + 1
    # The two are about 0.1 degree apart: at the widest view they would sit a few pixels
    # apart; zoomed in, far enough apart to read as a place.
    (x0, y0), (x1, y1) = spots
    assert math.hypot(x1 - x0, y1 - y0) > 60


def test_a_wide_spread_of_lit_schools_keeps_the_widest_closings_view() -> None:
    """Lit schools from Buffalo to Pennsylvania and Minnesota (SYNTHETIC): the busiest window
    at :data:`ZOOM`, never zoomed past what holds them all in the box."""
    rows = [(0, 0), (6, 0), (7, 0), (8, 0)]
    picture = choose(
        chances=False,
        closings_shown=True,
        closings=closings(rows, "2026-12-10", "2026-12-10T12:05:00Z"),
        predictions=None,
        directory=directory(),
        now=at("2026-12-10T12:10"),
    )
    zoom = float(picture.query.rsplit(",", 1)[1])
    assert ZOOM <= zoom <= MAX_ZOOM
    assert all(0 <= x < WIDTH and 0 <= y < HEIGHT for x, y in picture.seen.spots)
    assert picture.seen.in_view is not None
    assert len(picture.seen.spots) == picture.seen.in_view.total


def test_lit_private_schools_say_the_view_s_place_never_where_the_schools_are(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two lit private schools (their ids name no state) near Buffalo (SYNTHETIC): no "mostly
    in", but the view's own place by its public schools' share, "in a view over New York"."""
    monkeypatch.setattr("snowlight.social.picture.MIN_SPECKS", 0)
    ids = (*SCHOOLS, "A0000001", "A0000002")
    points = Points(
        lon_e6=np.asarray([round(v * 1e6) for v in (*LON, -78.86, -78.84)], dtype=np.int32),
        lat_e6=np.asarray([round(v * 1e6) for v in (*LAT, 42.91, 42.92)], dtype=np.int32),
        district=np.asarray([0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2], dtype=np.uint32),
        kind=np.asarray([0] * 10 + [1, 1], dtype=np.uint8),
        district_count=2,
    )
    here = Directory("2026-10-14", ids, DISTRICTS, points)
    file = closings([(10, 0), (11, 1)], "2026-12-10", "2026-12-10T12:05:00Z")
    file["directory"] = here.stamp()
    picture = choose(
        chances=False,
        closings_shown=True,
        closings=file,
        predictions=None,
        directory=here,
        now=at("2026-12-10T12:10"),
    )
    assert picture.kind == "closings"
    assert picture.seen.states == ()
    assert picture.seen.place == "New York"
    assert ", in a view over New York." in picture.shows
    assert "mostly" not in picture.shows


@pytest.mark.parametrize("specks", [7, 8])
def test_a_closer_view_steps_back_until_it_holds_enough_school_specks(
    monkeypatch: pytest.MonkeyPatch, specks: int
) -> None:
    """Two lit schools in Buffalo (SYNTHETIC) where the picture must hold ``specks`` of the
    directory's schools: the view steps back from :data:`MAX_ZOOM` by :data:`ZOOM_STEP` only
    until it does (the six Buffalo schools and one or both in Pennsylvania), never past
    :data:`ZOOM`, and both lit schools stay in the middle box."""
    monkeypatch.setattr("snowlight.social.picture.MIN_SPECKS", specks)
    picture = choose(
        chances=False,
        closings_shown=True,
        closings=closings([(0, 0), (1, 0)], "2026-12-10", "2026-12-10T12:05:00Z"),
        predictions=None,
        directory=directory(),
        now=at("2026-12-10T12:10"),
    )
    lat, lon, zoom = (float(part) for part in picture.query.removeprefix("?at=").split(","))
    assert ZOOM < zoom < MAX_ZOOM
    assert _held(directory().points, (lon, lat), zoom) >= specks
    assert _held(directory().points, (lon, lat), zoom + ZOOM_STEP) < specks
    for x, y in picture.seen.spots:
        assert abs(x - WIDTH / 2) <= FIT_BOX[0] / 2 + 1
        assert abs(y - HEIGHT / 2) <= FIT_BOX[1] / 2 + 1


@pytest.mark.parametrize(
    ("rows", "glows", "where"),
    [
        ([(2, 0)], "1 school glows in this view (1 closed)", ", in New York."),
        ([(0, 0), (1, 1), (2, 0)], "3 schools glow in this view", ", in New York."),
        (
            [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0)],
            "7 schools glow in this view",
            ", mostly in New York.",
        ),
    ],
)
def test_states_holding_every_lit_school_are_said_with_in_and_counts_agree_in_number(
    rows: list[tuple[int, int]], glows: str, where: str
) -> None:
    """One lit school, or lit schools all in New York (SYNTHETIC): "in New York", never
    "mostly"; six of seven (one in Pennsylvania) is a real majority short of all: "mostly".
    One school is "1 school", in view and across the country."""
    picture = choose(
        chances=False,
        closings_shown=True,
        closings=closings(rows, "2026-12-10", "2026-12-10T12:05:00Z"),
        predictions=None,
        directory=directory(),
        now=at("2026-12-10T12:10"),
    )
    assert glows in picture.shows
    assert where in picture.shows
    assert picture.seen.states_hold_all is (where == ", in New York.")
    assert "1 schools" not in picture.shows
    if len(rows) == 1:
        assert "the map shows 1 school closed, delayed" in picture.shows


# -- each school on its own map day (web/src/data/map-day.ts), as the page lights it ------------

MAP_DAY_TURNS = [
    # zone, then in November 2026: the minute before its 3:30 PM, its 3:30 PM, the minute
    # before its midnight, its midnight
    ("America/New_York", "09T20:29", "09T20:30", "10T04:59", "10T05:00"),
    ("America/Chicago", "09T21:29", "09T21:30", "10T05:59", "10T06:00"),
    ("America/Denver", "09T22:29", "09T22:30", "10T06:59", "10T07:00"),
    ("America/Phoenix", "09T22:29", "09T22:30", "10T06:59", "10T07:00"),
    ("America/Los_Angeles", "09T23:29", "09T23:30", "10T07:59", "10T08:00"),
    ("America/Anchorage", "10T00:29", "10T00:30", "10T08:59", "10T09:00"),
    ("Pacific/Honolulu", "10T01:29", "10T01:30", "10T09:59", "10T10:00"),
]
"""The site's own table (web/src/data/tests/map-day.test.ts ``ZONES``)."""


@pytest.mark.parametrize(("zone", "before", "turn", "late", "midnight"), MAP_DAY_TURNS)
def test_a_school_s_map_day_is_its_today_until_3_30_pm_on_its_clock_then_its_tomorrow(
    zone: str, before: str, turn: str, late: str, midnight: str
) -> None:
    monday, tuesday = date(2026, 11, 9), date(2026, 11, 10)
    assert map_day(at("2026-11-09T12:00"), zone) == monday
    assert map_day(at(f"2026-11-{before}"), zone) == monday
    assert map_day(at(f"2026-11-{turn}"), zone) == tuesday
    assert map_day(at(f"2026-11-{late}"), zone) == tuesday
    # After midnight that same Tuesday is its today: nothing changes at midnight.
    assert map_day(at(f"2026-11-{midnight}"), zone) == tuesday


def test_the_map_day_keeps_each_clock_across_its_changes() -> None:
    # Arizona keeps its own clock, an hour behind Denver's in summer.
    assert map_day(at("2026-07-14T21:45"), "America/Denver") == date(2026, 7, 15)
    assert map_day(at("2026-07-14T21:45"), "America/Phoenix") == date(2026, 7, 14)
    # The clocks go back on Nov 1, 2026: 3:30 PM EST is 20:30 UTC, EDT the day before 19:30.
    assert map_day(at("2026-11-01T20:29"), "America/New_York") == date(2026, 11, 1)
    assert map_day(at("2026-11-01T20:30"), "America/New_York") == date(2026, 11, 2)
    assert map_day(at("2026-10-31T19:29"), "America/New_York") == date(2026, 10, 31)
    assert map_day(at("2026-10-31T19:30"), "America/New_York") == date(2026, 11, 1)
    assert map_day(at("2026-11-01T23:29"), "America/Los_Angeles") == date(2026, 11, 1)
    assert map_day(at("2026-11-01T23:30"), "America/Los_Angeles") == date(2026, 11, 2)
    # They go forward on Mar 14, 2027: 3:30 PM CDT is 20:30 UTC; Arizona keeps 22:30.
    assert map_day(at("2027-03-14T20:29"), "America/Chicago") == date(2027, 3, 14)
    assert map_day(at("2027-03-14T20:30"), "America/Chicago") == date(2027, 3, 15)
    assert map_day(at("2027-03-14T22:29"), "America/Phoenix") == date(2027, 3, 14)
    assert map_day(at("2027-03-14T22:30"), "America/Phoenix") == date(2027, 3, 15)


def test_a_school_with_no_zone_keeps_the_day_that_is_today_everywhere() -> None:
    assert map_day(at("2026-11-09T20:45"), None) == date(2026, 11, 9)
    for hour in ("04:00", "05:30", "07:19", "07:59"):
        assert map_day(at(f"2026-11-10T{hour}"), None) is None
    assert map_day(at("2026-11-10T08:00"), None) == date(2026, 11, 10)


def test_a_school_whose_zone_is_unread_lights_only_while_every_clock_agrees() -> None:
    for moment in ("2026-11-09T20:45", "2026-11-09T23:30", "2026-11-10T03:59", "2026-11-10T07:59"):
        assert map_day(at(moment), UNREAD_ZONE) is None, moment
    assert map_day(at("2026-11-10T08:00"), UNREAD_ZONE) == date(2026, 11, 10)
    assert map_day(at("2026-11-10T20:29"), UNREAD_ZONE) == date(2026, 11, 10)
    assert map_day(at("2026-11-10T20:30"), UNREAD_ZONE) is None
    # Where it gives a day, every contiguous clock and a school with no zone give it too.
    for minute in range(0, 3 * 24 * 60, 7):
        now = at("2026-10-31T00:00") + timedelta(minutes=minute)
        day = map_day(now, UNREAD_ZONE)
        if day is not None:
            assert map_day(now, None) == day
            assert all(map_day(now, zone) == day for zone in CONTIGUOUS_ZONES)


def test_a_clock_that_cannot_be_told_gives_no_day() -> None:
    assert map_day(at("2026-11-10T12:00"), UNKNOWN_ZONE) is None
    assert map_day(at("2026-11-10T12:00"), "Not/A_Zone") is None


# Four schools (SYNTHETIC): an Eastern public school (district 0), a Pacific public school
# (district 1), a private school near Buffalo whose zone is its own entry, and a public
# school in Alaska (district 1 too, so the file gives it a zone; without the file it has none).
ZONE_IDS = ("360000100001", "060000100001", "A0000001", "020000100001")
ZONE_LON = (-78.88, -118.24, -78.86, -149.90)
ZONE_LAT = (42.89, 34.05, 42.91, 61.22)
ZONE_STAMP = {"generated_on": "2026-10-14", "schools": 4, "districts": 2}


def zone_directory() -> Directory:
    points = Points(
        lon_e6=np.asarray([round(v * 1e6) for v in ZONE_LON], dtype=np.int32),
        lat_e6=np.asarray([round(v * 1e6) for v in ZONE_LAT], dtype=np.int32),
        district=np.asarray([0, 1, NO_DISTRICT, 1], dtype=np.uint32),
        kind=np.asarray([0, 0, 1, 0], dtype=np.uint8),
        district_count=2,
    )
    return Directory("2026-10-14", ZONE_IDS, ("3600001", "0600001"), points)


def zone_file(east: str = "America/New_York", west: str = "America/Los_Angeles") -> dict[str, Any]:
    """The predictions file the page is served, for its zones: district 0 in ``east``,
    district 1 in ``west``, the private school in Eastern time (SYNTHETIC)."""
    return {
        "schema_version": 1,
        "generated_at": "2026-11-13T22:30:00Z",
        "directory": dict(ZONE_STAMP),
        "days": ["2026-11-13", "2026-11-14"],
        "districts": [
            {"district": 0, "time_zone": east, "days": [{"state": "no_threat"}] * 2},
            {"district": 1, "time_zone": west, "days": [{"state": "no_threat"}] * 2},
        ],
        "zones": ["America/New_York"],
        "outlooks": [{"state": "no_threat"}],
        "schools": [{"school": 2, "zone": 0, "days": [0, 0]}],
    }


def zone_closings(days: dict[str, list[tuple[int, int]]], generated_at: str) -> dict[str, Any]:
    file: dict[str, Any] = {
        "generated_at": generated_at,
        "directory": dict(ZONE_STAMP),
        "days": [],
    }
    for day, rows in days.items():
        file["days"].append(closings(rows, day, generated_at)["days"][0])
    return file


def lit_at(
    days: dict[str, list[tuple[int, int]]], moment: str, zones: dict[str, Any] | None
) -> tuple[list[int], set[date]] | None:
    file = zone_closings(days, f"{moment}:00Z")
    here = zone_directory()
    lit = lit_schools(file, here, at(moment), school_zones(zones, here))
    return None if lit is None else ([int(school) for school in lit.schools], set(lit.days))


def test_after_3_30_pm_on_its_clock_a_school_s_today_rows_no_longer_light() -> None:
    """Nov 13, 22:49 UTC (5:49 PM Eastern; the run that counted 83 while the map lit none):
    the Eastern school shows its Nov 14, which has no row, so it lights none; without the
    zones the page lights none either (the clocks no longer agree)."""
    rows = {"2026-11-13": [(0, 0)]}
    assert lit_at(rows, "2026-11-13T22:49", zone_file()) is None
    assert lit_at(rows, "2026-11-13T22:49", None) is None


def test_overnight_each_school_lights_its_own_today() -> None:
    """Nov 13, 07:19 UTC (the run that counted 0 while the map lit 16): no day is today
    everywhere, yet each school's own clock is on Nov 13 (Pacific is past midnight)."""
    rows = {"2026-11-13": [(0, 0), (1, 1)]}
    assert lit_at(rows, "2026-11-13T07:19", zone_file()) == ([0, 1], {date(2026, 11, 13)})
    # Without the zones the page lights none in those hours: nor does the count.
    assert lit_at(rows, "2026-11-13T07:19", None) is None


def test_in_the_evening_east_and_west_light_rows_of_different_days() -> None:
    """Nov 12, 22:50 UTC: 5:50 PM Eastern (its Nov 13) and 2:50 PM Pacific (its Nov 12). The
    Eastern school lights its Nov 13 row, the Pacific school its Nov 12 row, one row each."""
    rows = {"2026-11-12": [(0, 1), (1, 0)], "2026-11-13": [(0, 0), (1, 2)]}
    lit = lit_schools(
        zone_closings(rows, "2026-11-12T22:50:00Z"),
        zone_directory(),
        at("2026-11-12T22:50"),
        school_zones(zone_file(), zone_directory()),
    )
    assert lit is not None
    assert [int(school) for school in lit.schools] == [0, 1]
    assert [int(status) for status in lit.statuses] == [0, 0], "Eastern: Nov 13; Pacific: Nov 12"
    assert lit.days == frozenset({date(2026, 11, 12), date(2026, 11, 13)})


def test_a_private_school_keeps_its_own_zone_and_one_with_none_today_everywhere() -> None:
    rows = {"2026-11-13": [(2, 0)], "2026-11-14": [(2, 1)]}
    # 21:00 UTC: 4 PM Eastern, the private school's own clock: its Nov 14 row lights.
    assert lit_at(rows, "2026-11-13T21:00", zone_file()) == ([2], {date(2026, 11, 14)})
    # A file that gives it no zone: the day that is today everywhere, Nov 13.
    bare = {**zone_file(), "schools": [], "zones": []}
    assert lit_at(rows, "2026-11-13T21:00", bare) == ([2], {date(2026, 11, 13)})


def test_zones_the_page_cannot_use_leave_it_the_unread_rule() -> None:
    """A file for another directory, of another schema, or with a zone that cannot be read
    gives the page no zones (live.ts toldZones, map-day.ts parsePredictions): it lights each
    contiguous school by the day every clock agrees on, and an Alaska school not at all."""
    rows = {"2026-11-13": [(0, 0), (3, 0)]}
    other = {**zone_file(), "directory": {**ZONE_STAMP, "schools": 5}}
    unread = [other, {**zone_file(), "schema_version": 2}, zone_file(west="Not/A_Zone"), None]
    for file in unread:
        assert school_zones(file, zone_directory()) is None
        # 18:00 UTC: every contiguous clock is before 3:30 PM: the Eastern school lights.
        assert lit_at(rows, "2026-11-13T18:00", file) == ([0], {date(2026, 11, 13)})
        # 22:49 UTC: the clocks no longer agree: none.
        assert lit_at(rows, "2026-11-13T22:49", file) is None
    # With the file's zones the Alaska school lights by its district's clock (10 AM there).
    assert lit_at(rows, "2026-11-13T18:00", zone_file()) == ([0, 3], {date(2026, 11, 13)})


def _broken(change: str) -> dict[str, Any]:
    """The zone file with one thing the page's parsePredictions refuses (SYNTHETIC)."""
    file: dict[str, Any] = json.loads(json.dumps(zone_file()))
    district, school = file["districts"][1], file["schools"][0]
    edits: dict[str, Callable[[], None]] = {
        "no time": lambda: file.pop("generated_at"),
        "a time with its milliseconds": lambda: file.update(
            generated_at="2026-11-13T22:30:00.000Z"
        ),
        "a time that is no day": lambda: file.update(generated_at="2026-02-30T22:30:00Z"),
        "no days": lambda: file.update(days=[]),
        "days not consecutive": lambda: file.update(days=["2026-11-13", "2026-11-15"]),
        "a day that is no day": lambda: file.update(days=["2026-11-13", "2026-11-31"]),
        "a district with a day too few": lambda: district.update(days=[{"state": "no_threat"}]),
        "a district's forecast that does not read": lambda: district.update(
            days=[{"state": "no_threat"}, {"state": "forecast", "p_no_school": 1.0}]
        ),
        "a forecast with no reasons": lambda: district.update(
            days=[{"state": "no_threat"}, {"state": "forecast", "p_no_school": 0.2, "p_delay": 0.1}]
        ),
        "an outlook that does not read": lambda: file.update(outlooks=[{"state": "maybe"}]),
        "private schools out of order": lambda: file.update(
            schools=[school, {**school, "school": 1}]
        ),
        "the same private school twice": lambda: file.update(schools=[school, school]),
        "a private school with a day too few": lambda: school.update(days=[0]),
        "a private school's day past the outlooks": lambda: school.update(days=[0, 1]),
        "an index past the page's": lambda: district.update(district=4_294_967_295),
    }
    edits[change]()
    return file


@pytest.mark.parametrize(
    "change",
    [
        "no time",
        "a time with its milliseconds",
        "a time that is no day",
        "no days",
        "days not consecutive",
        "a day that is no day",
        "a district with a day too few",
        "a district's forecast that does not read",
        "a forecast with no reasons",
        "an outlook that does not read",
        "private schools out of order",
        "the same private school twice",
        "a private school with a day too few",
        "a private school's day past the outlooks",
        "an index past the page's",
    ],
)
def test_a_file_the_page_refuses_gives_no_zones(change: str) -> None:
    """Wherever the page's parsePredictions gives null (map-day.ts), the picture reads no zones
    either, so both light by the unread rule and the counts agree (an Alaska school: none)."""
    file = _broken(change)
    assert school_zones(file, zone_directory()) is None
    assert lit_at({"2026-11-13": [(0, 0), (3, 0)]}, "2026-11-13T18:00", file) == (
        [0],
        {date(2026, 11, 13)},
    )


def test_a_file_the_page_reads_in_full_gives_its_zones() -> None:
    """A forecast day with its reasons, outlooks the private schools name, and a file of one
    day: the page reads each, so the zones stand (SYNTHETIC)."""
    file = zone_file()
    file["districts"][1]["days"] = [
        {"state": "no_threat"},
        {"state": "forecast", "p_no_school": 0.2, "p_delay": 0.1, "reasons": [0, 7]},
    ]
    file["outlooks"].append({"state": "forecast", "p_no_school": 0.01, "p_delay": 0, "reasons": []})
    file["schools"][0]["days"] = [0, 1]
    assert school_zones(file, zone_directory()) is not None
    single = {
        **zone_file(),
        "days": ["2026-11-13"],
        "districts": [
            {"district": index, "time_zone": zone, "days": [{"state": "no_threat"}]}
            for index, zone in ((0, "America/New_York"), (1, "America/Los_Angeles"))
        ],
        "schools": [{"school": 2, "zone": 0, "days": [0]}],
    }
    assert school_zones(single, zone_directory()) is not None


def test_the_stamp_is_read_by_its_day_and_counts_alone() -> None:
    """The page compares a file's directory by its day and two counts only (map-day.ts
    ``zonesFor``) and refuses the file for a stamp it does not read (``parseStamp``): a key
    it does not read never parts the two, and a stamp it cannot read gives no zones (SYNTHETIC)."""
    extra = {**zone_file(), "directory": {**ZONE_STAMP, "built_by": "SYNTHETIC"}}
    assert school_zones(extra, zone_directory()) == school_zones(zone_file(), zone_directory())
    assert school_zones(extra, zone_directory()) is not None
    unread = [
        {**ZONE_STAMP, "generated_on": "Oct 14"},
        {**ZONE_STAMP, "schools": -1},
        {**ZONE_STAMP, "districts": True},
        {key: value for key, value in ZONE_STAMP.items() if key != "districts"},
        "2026-10-14",
        None,
    ]
    for stamp in unread:
        assert school_zones({**zone_file(), "directory": stamp}, zone_directory()) is None


def test_the_description_counts_what_the_page_lights_each_on_its_own_day() -> None:
    """The picture's words count the schools lit on each one's own day, and name the days."""
    rows = {"2026-11-12": [(0, 1), (1, 0)], "2026-11-13": [(0, 0), (1, 2)]}
    file = zone_closings(rows, "2026-11-12T22:45:00Z")
    picture = choose(
        chances=False,
        closings_shown=True,
        closings=file,
        predictions=None,
        directory=zone_directory(),
        now=at("2026-11-12T22:50"),
        zones=zone_file(),
    )
    assert picture.kind == "closings"
    assert picture.lit == 2
    assert "for November 12 or 13, each school's own day on its clock." in picture.shows
    assert "today" not in picture.shows.lower()
    one = choose(
        chances=False,
        closings_shown=True,
        closings=zone_closings({"2026-11-13": [(0, 0), (1, 2)]}, "2026-11-13T07:15:00Z"),
        predictions=None,
        directory=zone_directory(),
        now=at("2026-11-13T07:19"),
        zones=zone_file(),
    )
    assert one.lit == 2
    assert "dismissing early for November 13. The closings" in one.shows
    # The evening run with today's rows only: nothing lit, the calm view's words.
    calm = choose(
        chances=False,
        closings_shown=True,
        closings=zone_closings({"2026-11-13": [(0, 0)]}, "2026-11-13T22:45:00Z"),
        predictions=None,
        directory=zone_directory(),
        now=at("2026-11-13T22:49"),
        zones=zone_file(),
    )
    assert calm.kind == "national"
    assert calm.lit == 0
    assert "No school is lit up" in calm.shows


def test_a_calm_region_is_refused_only_where_the_page_lights_schools() -> None:
    file = zone_closings({"2026-11-13": [(0, 0)]}, "2026-11-13T07:15:00Z")
    with pytest.raises(PictureError, match="schools are lit"):
        region(
            query="?at=43,-79,6",
            place="the Great Lakes",
            closings=file,
            directory=zone_directory(),
            now=at("2026-11-13T07:19"),
            closings_shown=True,
            zones=zone_file(),
        )
    evening = region(
        query="?at=43,-79,6",
        place="the Great Lakes",
        closings=file,
        directory=zone_directory(),
        now=at("2026-11-13T22:49"),
        closings_shown=True,
        zones=zone_file(),
    )
    assert evening.kind == "region"


def test_while_chances_are_testing_the_zones_give_no_chance() -> None:
    """The zones come from the predictions file, but no chance does while chances are
    TESTING: a 90% forecast in it is never said."""
    file = zone_file()
    file["days"] = ["2026-11-13", "2026-11-14"]
    for row in file["districts"]:
        row["days"] = [{"state": "no_threat"}, {"state": "forecast", "p_no_school": 0.9}]
    file["generated_at"] = "2026-11-13T15:00:00Z"
    picture = choose(
        chances=False,
        closings_shown=True,
        closings=None,
        predictions=None,
        directory=zone_directory(),
        now=at("2026-11-13T15:10"),
        zones=file,
    )
    assert picture.seen.chance is None
    assert not mentions_chance(picture.shows)
    assert "90" not in picture.shows
