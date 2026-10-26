"""What a post's fresh picture shows, worked out from the live files the deployed map reads.

The picture is taken in the social-post workflow from the real site (:mod:`snowlight.social.
render`). Before the browser opens, :func:`choose` reads the same files the page reads and
picks the view:

* **Closings on the map**: when ``live/closings.json`` holds schools for the day the map
  shows (the day that is today in every contiguous US time zone, 08:00 to 04:00 UTC, as
  ``web/src/data/closings.ts`` has it) under the deployed directory's stamp, the map is
  zoomed (``?at=lat,lon,zoom``) to the window of the screen's size holding the most of them.
* **Else a high chance**: when a district's chance of no school today is at least
  :data:`PANEL_MIN_CHANCE`, the district with the highest one, its panel open
  (``?district=<id>``).
* **Else the national map at night**, every school a dot.

It also writes :attr:`Picture.shows`: the plain facts about the picture (the time, the place
by state, the counts and the chance), the only things a post may say about it. No school,
district or person is named. The browser is then served exactly the files described (the
render answers the page's requests for them), and the render checks the page lit as many
schools as the description counts.
"""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from snowlight.directory.points import Points

ZOOM: Final = 6.5
"""The zoom of a closings view: a few states across on a 1600 x 900 picture."""
WIDTH: Final = 1600
HEIGHT: Final = 900
PANEL_MIN_CHANCE: Final = 0.10
"""The chance of no school that earns a district's panel instead of the national map."""
FRESH: Final = timedelta(minutes=20)
"""How old a closings file may be and still be called live (web/src/state/freshness.ts)."""
LEAD: Final = timedelta(minutes=2)
"""How far ahead of the clock a closings file may be stamped and still be live (the same)."""
EAST_OFFSET: Final = timedelta(hours=-4)
WEST_OFFSET: Final = timedelta(hours=-8)
SHOWN_ZONE: Final = ZoneInfo("America/Chicago")
"""The zone the picture's browser and its description tell time in."""
MAX_CANDIDATES: Final = 2000
STATUS_WORDS: Final = ("closed", "delayed", "remote", "dismissing early")

STATES: Final[Mapping[str, str]] = {
    "01": "Alabama", "02": "Alaska", "04": "Arizona", "05": "Arkansas", "06": "California",
    "08": "Colorado", "09": "Connecticut", "10": "Delaware", "11": "the District of Columbia",
    "12": "Florida", "13": "Georgia", "15": "Hawaii", "16": "Idaho", "17": "Illinois",
    "18": "Indiana", "19": "Iowa", "20": "Kansas", "21": "Kentucky", "22": "Louisiana",
    "23": "Maine", "24": "Maryland", "25": "Massachusetts", "26": "Michigan", "27": "Minnesota",
    "28": "Mississippi", "29": "Missouri", "30": "Montana", "31": "Nebraska", "32": "Nevada",
    "33": "New Hampshire", "34": "New Jersey", "35": "New Mexico", "36": "New York",
    "37": "North Carolina", "38": "North Dakota", "39": "Ohio", "40": "Oklahoma", "41": "Oregon",
    "42": "Pennsylvania", "44": "Rhode Island", "45": "South Carolina", "46": "South Dakota",
    "47": "Tennessee", "48": "Texas", "49": "Utah", "50": "Vermont", "51": "Virginia",
    "53": "Washington", "54": "West Virginia", "55": "Wisconsin", "56": "Wyoming",
}  # fmt: skip
"""State names by the FIPS code a public school's or district's NCES id starts with."""

type Kind = Literal["closings", "district", "national"]

FILE: Final = "picture.png"
NOTE: Final = "picture.json"


class PictureError(ValueError):
    """A live file is not what the page reads (the picture would not match its words)."""


@dataclass(frozen=True, slots=True)
class Directory:
    """The deployed directory: ``schools/meta.json`` ids and ``points.bin``."""

    generated_on: str
    school_ids: tuple[str, ...]
    district_ids: tuple[str, ...]
    points: Points

    def stamp(self) -> dict[str, object]:
        return {
            "generated_on": self.generated_on,
            "schools": len(self.school_ids),
            "districts": len(self.district_ids),
        }


@dataclass(frozen=True, slots=True)
class Picture:
    """The view to take and what it shows."""

    kind: Kind
    query: str
    """The page address's query, from ``?``, or empty for the national map."""
    shows: str
    taken_at: datetime
    current: bool
    """Whether the post may call what it shows current (a closings file older than
    :data:`FRESH` is not)."""
    lit: int
    """How many schools the page lights, across the country (the render checks it)."""
    panel: str | None = None
    """The chance the open panel shows, as the page writes it (the render checks it)."""


def today_everywhere(now: datetime) -> date | None:
    """The day that is today in every contiguous US zone, or ``None`` (04:00-08:00 UTC)."""
    east = (now + EAST_OFFSET).date()
    west = (now + WEST_OFFSET).date()
    return east if east == west else None


def _clock(moment: datetime) -> str:
    local = moment.astimezone(SHOWN_ZONE)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'} Central time"  # noqa: PLR2004


def _day(moment: datetime) -> str:
    local = moment.astimezone(SHOWN_ZONE)
    return f"{local:%B} {local.day}, {local.year}"


def _instant(value: object, what: str) -> datetime:
    if not isinstance(value, str):
        raise PictureError(f"{what}: generated_at is missing")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PictureError(f"{what}: generated_at does not parse") from None
    if moment.tzinfo is None:
        raise PictureError(f"{what}: generated_at has no zone")
    return moment.astimezone(UTC)


def _rows(group: Mapping[str, object], count: int) -> tuple[list[int], list[int]]:
    gaps = group.get("gaps")
    statuses = group.get("statuses")
    if not isinstance(gaps, list) or not isinstance(statuses, list) or len(gaps) != len(statuses):
        raise PictureError("closings.json: a day's columns differ")
    schools: list[int] = []
    previous = -1
    for gap, status in zip(gaps, statuses, strict=True):
        if not isinstance(gap, int) or not isinstance(status, int) or not 0 <= status <= 3:  # noqa: PLR2004
            raise PictureError("closings.json: a row is malformed")
        previous += 1 + gap
        if previous >= count:
            raise PictureError("closings.json: a school index is past the directory")
        schools.append(previous)
    return schools, [int(status) for status in statuses]


@dataclass(frozen=True, slots=True)
class Lit:
    """The schools the map lights, and on which day."""

    day: date
    schools: npt.NDArray[np.int64]
    statuses: npt.NDArray[np.int64]
    generated_at: datetime


def lit_schools(
    closings: Mapping[str, object] | None, directory: Directory, now: datetime
) -> Lit | None:
    """The schools the page lights at ``now``: ``None`` when it lights none (no file, a file
    under another directory, or the hours between days).

    Raises:
        PictureError: the file is malformed.
    """
    if closings is None:
        return None
    generated_at = _instant(closings.get("generated_at"), "closings.json")
    if closings.get("directory") != directory.stamp():
        return None
    shown = today_everywhere(now)
    days = closings.get("days")
    if not isinstance(days, list):
        raise PictureError("closings.json: days is missing")
    for group in days:
        if not isinstance(group, dict):
            raise PictureError("closings.json: a day is malformed")
        if shown is None or group.get("day") != shown.isoformat():
            continue
        schools, statuses = _rows(group, len(directory.school_ids))
        if not schools:
            return None
        return Lit(
            day=shown,
            schools=np.asarray(schools, dtype=np.int64),
            statuses=np.asarray(statuses, dtype=np.int64),
            generated_at=generated_at,
        )
    return None


def _window(lat: float) -> tuple[float, float]:
    """The picture's span in degrees of longitude and latitude, centered at ``lat`` (one
    512-pixel MapLibre tile spans 360 / 2^zoom degrees, web/src/state/url.ts)."""
    scale = 360.0 / (512.0 * 2.0**ZOOM)
    return WIDTH * scale, HEIGHT * scale * float(np.cos(np.radians(lat)))


def _inside(
    lon: npt.NDArray[np.float64], lat: npt.NDArray[np.float64], center: tuple[float, float]
) -> npt.NDArray[np.bool_]:
    width, height = _window(center[1])
    return (np.abs(lon - center[0]) <= width / 2) & (np.abs(lat - center[1]) <= height / 2)


def busiest_view(
    lon: npt.NDArray[np.float64], lat: npt.NDArray[np.float64]
) -> tuple[tuple[float, float], npt.NDArray[np.bool_]]:
    """The center of the picture-sized window holding the most points, and which points it
    holds. Candidates are the points themselves (every k-th one past
    :data:`MAX_CANDIDATES`); ties go to the earlier point, so the choice is repeatable."""
    step = max(1, len(lon) // MAX_CANDIDATES)
    best = -1
    center = (float(lon[0]), float(lat[0]))
    for index in range(0, len(lon), step):
        candidate = (float(lon[index]), float(lat[index]))
        count = int(_inside(lon, lat, candidate).sum())
        if count > best:
            best, center = count, candidate
    held = _inside(lon, lat, center)
    # Centered on the lit schools it holds, which keeps (nearly) all of them in view.
    moved = (float(lon[held].mean()), float(lat[held].mean()))
    moved_held = _inside(lon, lat, moved)
    if int(moved_held.sum()) >= int(held.sum()):
        return moved, moved_held
    return center, held


def _states(ids: Sequence[str]) -> list[str]:
    """The states most of ``ids`` (public NCES ids) are in, most first, at most two."""
    counts = Counter(STATES.get(school[:2]) for school in ids if len(school) == 12)  # noqa: PLR2004
    counts.pop(None, None)
    return [name for name, _ in counts.most_common(2) if name is not None]


def _and(names: Sequence[str]) -> str:
    return " and ".join(names)


def _status_counts(statuses: npt.NDArray[np.int64]) -> str:
    counts = np.bincount(statuses, minlength=4)
    parts = [f"{int(counts[code])} {STATUS_WORDS[code]}" for code in range(4) if counts[code]]
    return ", ".join(parts)


def _closings_picture(lit: Lit, directory: Directory, now: datetime) -> Picture:
    points = directory.points
    lon = points.lon_e6[lit.schools].astype(np.float64) / 1e6
    lat = points.lat_e6[lit.schools].astype(np.float64) / 1e6
    (center_lon, center_lat), held = busiest_view(lon, lat)
    in_view = lit.schools[held]
    states = _states([directory.school_ids[int(index)] for index in in_view])
    total = len(lit.schools)
    current = -LEAD <= now - lit.generated_at <= FRESH
    updated = (
        f"The closings were updated at {_clock(lit.generated_at)}."
        if current
        else f"The closings were last updated at {_clock(lit.generated_at)}, "
        f"{int((now - lit.generated_at).total_seconds() // 60)} minutes before the picture, "
        "so the map does not call them live."
    )
    place = f", mostly in {_and(states)}" if states else ""
    shows = (
        f"A picture of the Snowlight map taken at {_clock(now)} on {_day(now)}, zoomed to the "
        f"area with the most schools lit up for weather: {len(in_view)} schools glow in this "
        f"view ({_status_counts(lit.statuses[held])}){place}. Across the country the map "
        f"shows {total} schools closed, delayed, remote or dismissing early for {_day_of(lit.day)}."
        f" {updated}"
    )
    query = f"?at={center_lat:.4f},{center_lon:.4f},{ZOOM:g}"
    return Picture("closings", query, shows, now, current, total)


def _day_of(day: date) -> str:
    return f"{day:%B} {day.day}"


def _chance_day(predictions: Mapping[str, object], today: date) -> int | None:
    days = predictions.get("days")
    if not isinstance(days, list):
        raise PictureError("predictions: days is missing")
    return next((i for i, value in enumerate(days) if value == today.isoformat()), None)


def highest_chance(
    predictions: Mapping[str, object] | None, directory: Directory, today: date
) -> tuple[float, int, int] | None:
    """The highest chance of no school ``today`` of any district, the district's index, and
    how many districts have a chance that day; ``None`` without one.

    Raises:
        PictureError: the file is malformed.
    """
    if predictions is None or predictions.get("directory") != directory.stamp():
        return None
    column = _chance_day(predictions, today)
    districts = predictions.get("districts")
    if column is None:
        return None
    if not isinstance(districts, list):
        raise PictureError("predictions: districts is missing")
    best: tuple[float, int] | None = None
    counted = 0
    for row in districts:
        if not isinstance(row, dict):
            raise PictureError("predictions: a district is malformed")
        days = row.get("days")
        index = row.get("district")
        if not isinstance(days, list) or not isinstance(index, int) or column >= len(days):
            raise PictureError("predictions: a district is malformed")
        day = days[column]
        chance = day.get("p_no_school") if isinstance(day, dict) else None
        if not isinstance(chance, int | float) or not 0 <= index < len(directory.district_ids):
            continue
        counted += 1
        # Ties go to the lower index, so the choice is repeatable.
        if best is None or chance > best[0]:
            best = (float(chance), index)
    if best is None:
        return None
    return best[0], best[1], counted


def _percent(chance: float) -> int:
    """A chance as a whole percent, halves up, as the page's ``Math.round`` has it."""
    return math.floor(chance * 100 + 0.5)


def chance_text(chance: float) -> str:
    """A chance as the page writes it (web/src/copy-format.ts): "34%", "<1%", ">99%"."""
    percent = _percent(chance)
    if percent < 1:
        return "<1%"
    if percent > 99:  # noqa: PLR2004
        return ">99%"
    return f"{percent}%"


def choose(
    *,
    closings: Mapping[str, object] | None,
    predictions: Mapping[str, object] | None,
    directory: Directory,
    now: datetime,
) -> Picture:
    """The view to take at ``now`` and its description (see the module's docstring).

    Raises:
        PictureError: a live file is malformed (the run then falls back to the library).
    """
    now = now.astimezone(UTC)
    lit = lit_schools(closings, directory, now)
    if lit is not None:
        return _closings_picture(lit, directory, now)
    today = today_everywhere(now) or (now + EAST_OFFSET).date()
    high = highest_chance(predictions, directory, today)
    closings_line = "No school is lit up for weather on the map."
    if high is not None and high[0] >= PANEL_MIN_CHANCE:
        chance, index, _ = high
        district = directory.district_ids[index]
        state = STATES.get(district[:2])
        where = f" in {state}" if state else ""
        shows = (
            f"A picture of the Snowlight map taken at {_clock(now)} on {_day(now)}, with the "
            f"panel of a public school district{where} open: its chance of no school on "
            f"{_day_of(today)} is {chance_text(chance)}, the highest of any district that day. "
            f"{closings_line}"
        )
        return Picture(
            "district", f"?district={district}", shows, now, True, 0, chance_text(chance)
        )
    if high is None:
        chance_line = ""
    elif high[0] == 0 or _percent(high[0]) <= 1:
        chance_line = (
            f" Not in the picture: Snowlight's chance of no school on {_day_of(today)} is at most"
            f" {max(1, _percent(high[0]))}% in every one of the {high[2]} districts with a chance."
        )
    else:
        chance_line = (
            f" Not in the picture: Snowlight's highest chance of no school on {_day_of(today)} in"
            f" any district is {chance_text(high[0])}."
        )
    shows = (
        f"A picture of the Snowlight map of the US at night taken at {_clock(now)} on "
        f"{_day(now)}: every school is a faint dot of light. {closings_line}{chance_line}"
    )
    return Picture("national", "", shows, now, True, 0)


class Taken(BaseModel):
    """``picture.json``: what the fresh picture shows, for the post step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Kind
    query: str = Field(max_length=80)
    shows: str = Field(min_length=20, max_length=600)
    taken_at: datetime
    current: bool
    lit: int = Field(ge=0)
    file: str = Field(pattern=r"^picture\.png$")
