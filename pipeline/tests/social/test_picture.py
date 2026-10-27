"""The fresh picture's view and description, from SYNTHETIC live files
(snowlight.social.picture)."""

import math
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pytest

from snowlight.directory.points import Points
from snowlight.social.picture import (
    DISTRICT_X,
    FIT_BOX,
    HEIGHT,
    MAX_ZOOM,
    REGIONS,
    WIDTH,
    ZOOM,
    Counts,
    Directory,
    PictureError,
    _states,
    busiest_view,
    calm_regions,
    chance_day,
    chance_text,
    choose,
    clock,
    district_frame,
    lit_schools,
    project,
    region,
    slot_of,
    today_everywhere,
    unproject,
    view_states,
)
from snowlight.social.rules import mentions_closings

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
# the probe that found 'mostly' false for five of seven regions.
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
    # 9 PM Central on Sunday: Monday's 5 AM is still ahead everywhere.
    assert chance_day(week, at("2026-10-26T02:00")) == date(2026, 10, 26)
    # 5:30 AM Eastern on Monday: under way in the east (one district), not in Central (one):
    # not more than half, so Monday is no longer named.
    assert chance_day(week, at("2026-10-26T09:30")) == date(2026, 10, 27)
    # 4:30 AM Eastern: still ahead in both.
    assert chance_day(week, at("2026-10-26T08:30")) == date(2026, 10, 26)
    # Every day the file holds is under way: no chance is named at all.
    assert chance_day(week, at("2026-10-27T11:00")) is None
    # A file whose days skip the weekend: on Saturday the next school day is its Monday.
    weekend = predictions([0.01, 0.2], ("2026-10-26", "2026-10-27"))
    assert chance_day(weekend, at("2026-10-24T18:00")) == date(2026, 10, 26)
    # A district with no zone, or one this machine does not know, counts in Eastern time.
    odd = {**week, "districts": [{"district": 0, "days": []}, {"time_zone": "Mars/Base"}]}
    assert chance_day(odd, at("2026-10-26T09:30")) == date(2026, 10, 27)
    with pytest.raises(PictureError, match="a day is malformed"):
        chance_day({**week, "days": ["Monday"]}, at("2026-10-26T09:30"))
    with pytest.raises(PictureError, match="districts is missing"):
        chance_day({"days": ["2026-10-26"]}, at("2026-10-26T09:30"))


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


def test_few_lit_schools_fill_the_card_zoomed_in_with_every_one_in_the_box() -> None:
    """Two lit schools a few miles apart (SYNTHETIC): the view zooms in as far as
    :data:`MAX_ZOOM` allows, both in the middle box, so their glow and the specks around them
    fill the card instead of a dot in a dark country."""
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


def test_lit_private_schools_say_the_view_s_place_never_where_the_schools_are() -> None:
    """Two lit private schools (their ids name no state) near Buffalo (SYNTHETIC): no "mostly
    in", but the view's own place by its public schools' share, "in a view over New York"."""
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
