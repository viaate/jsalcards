"""The fresh picture's view and description, from SYNTHETIC live files
(snowlight.social.picture)."""

from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pytest

from snowlight.directory.points import Points
from snowlight.social.picture import (
    Directory,
    PictureError,
    busiest_view,
    choose,
    lit_schools,
    today_everywhere,
)

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


def predictions(chances: list[float | None], days: tuple[str, str]) -> dict[str, Any]:
    rows = []
    for index, chance in enumerate(chances):
        today: dict[str, Any] = (
            {"state": "no_threat"}
            if chance is None
            else {"state": "forecast", "p_no_school": chance}
        )
        rows.append({"district": index, "days": [{"state": "no_threat"}, today]})
    return {"directory": dict(STAMP), "days": list(days), "districts": rows}


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
    assert zoom == 6.5
    shows = picture.shows
    assert "6:10 AM Central time on December 10, 2026" in shows
    # The window holds Buffalo's six and the nearby Pennsylvania one, not MN or TX.
    assert "7 schools glow in this view (5 closed, 1 delayed, 1 remote)" in shows
    assert "mostly in New York and Pennsylvania" in shows
    assert "Across the country the map shows 9 schools" in shows
    assert "updated at 6:05 AM Central time." in shows
    assert "Buffalo" not in shows, "no place below the state is named"


def test_an_old_closings_file_is_not_called_current() -> None:
    picture = choose(
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
    ("file", "now"),
    [
        # Another directory's file is not read by the page.
        ({**closings([(0, 0)], "2026-12-10", "2026-12-10T12:05:00Z"), "directory": {}}, "12:10"),
        # The hours between days light nothing.
        (closings([(0, 0)], "2026-12-10", "2026-12-10T05:00:00Z"), "05:10"),
        # Yesterday's rows light nothing today.
        (closings([(0, 0)], "2026-12-09", "2026-12-10T12:05:00Z"), "12:10"),
        (None, "12:10"),
    ],
)
def test_no_lit_school_gives_the_national_map(file: dict[str, Any] | None, now: str) -> None:
    picture = choose(
        closings=file, predictions=None, directory=directory(), now=at(f"2026-12-10T{now}")
    )
    assert picture.kind == "national"
    assert picture.query == ""
    assert picture.lit == 0
    assert "No school is lit up for weather on the map." in picture.shows
    assert "at night" in picture.shows


def test_a_high_chance_opens_that_districts_panel() -> None:
    picture = choose(
        closings=None,
        predictions=predictions([0.04, 0.37], ("2026-12-09", "2026-12-10")),
        directory=directory(),
        now=at("2026-12-10T02:30"),  # 8:30 PM Central on December 9: the day is December 9
    )
    # 02:30 UTC is between days, so the chance day is the eastern date, December 9: the
    # column is the first, where every district is no_threat.
    assert picture.kind == "national"
    picture = choose(
        closings=None,
        predictions=predictions([0.04, 0.37], ("2026-12-09", "2026-12-10")),
        directory=directory(),
        now=at("2026-12-10T15:00"),
    )
    assert picture.kind == "district"
    assert picture.query == "?district=2700001"
    assert "public school district in Minnesota open" in picture.shows
    assert "chance of no school on December 10 is 37%, the highest of any district" in (
        picture.shows
    )


def test_a_calm_day_says_the_chance_is_not_in_the_picture() -> None:
    picture = choose(
        closings=None,
        predictions=predictions([0.01, 0.01], ("2026-10-25", "2026-10-26")),
        directory=directory(),
        now=at("2026-10-26T16:37"),
    )
    assert picture.kind == "national"
    assert (
        "Not in the picture: Snowlight's chance of no school on October 26 is at most 1% in "
        "every one of the 2 districts with a chance."
    ) in picture.shows
    some = choose(
        closings=None,
        predictions=predictions([0.06, None], ("2026-10-25", "2026-10-26")),
        directory=directory(),
        now=at("2026-10-26T16:37"),
    )
    assert "highest chance of no school on October 26 in any district is 6%" in some.shows
    other = choose(
        closings=None,
        predictions={**predictions([0.5], ("2026-10-25", "2026-10-26")), "directory": {}},
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
            closings=None,
            predictions={"directory": dict(STAMP)},
            directory=directory(),
            now=at("2026-10-26T16:37"),
        )
    with pytest.raises(PictureError, match="district"):
        choose(
            closings=None,
            predictions={"directory": dict(STAMP), "days": ["2026-10-26"], "districts": [7]},
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
