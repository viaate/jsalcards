"""What a post's fresh picture shows, worked out from the live files the deployed map reads.

The picture is taken in the social-post workflow from the real site (:mod:`snowlight.social.
render`): the map alone, every piece of the site's interface hidden, then laid into a branded
card (:mod:`snowlight.social.cards`). Before the browser opens, :func:`choose` reads the same
files the page reads and picks the view:

* **Closings on the map** (only while the facts file marks closings LIVE: while they are not,
  the file is not read at all and nothing is said about closings): when
  ``live/closings.json`` holds schools for the day the map
  shows (the day that is today in every contiguous US time zone, 08:00 to 04:00 UTC, as
  ``web/src/data/closings.ts`` has it) under the deployed directory's stamp, the map is
  zoomed (``?at=lat,lon,zoom``) to the window of the picture's size holding the most of them
  at :data:`ZOOM`, then closer (up to :data:`MAX_ZOOM`) while every lit school of the window
  still fits :data:`FIT_BOX` in the middle of the picture, so a few lit schools fill the
  card with their glow and the specks around them instead of a dot in a dark country.
* **Else a high chance** (only while the facts file marks chances LIVE: while they are
  TESTING the site is locked, and no picture gives a chance): when a district's chance of
  no school today is at least :data:`PANEL_MIN_CHANCE`, the district with the highest one,
  framed by its schools on the left of the picture (:data:`DISTRICT_X`), the right side left
  free for the card's number.
  The map draws no chance, so the chance is a number on the card, never on the map.
* **Else a region's city lights** (:func:`calm_regions`, taken by
  :mod:`snowlight.social.render`): one of :data:`REGIONS`, populous windows at a zoom where the
  site draws every school as a faint speck (zoom 5 to 10), rotated by the run's slot of the
  day (:func:`slot_of`) so each of a day's posts opens on a different place.
  The render checks the page drew specks in view and tries the next region when it did not.
* **Else the national map** (only when every region tried failed): the site's dark map,
  near-black land, state lines and city names (dark at any hour: the words never say
  "night"). The site draws no school specks at this zoom (it draws them only between zoom 5
  and 10), so alone it reads as an empty black map.

It also writes :attr:`Picture.shows`, the plain facts about the picture (the time, the place
by state, the counts and the chance), the only things a post may say about it, and the same
facts as fields (:class:`Seen`) for the card. No school, district or person is named. When
``closings.json`` was not read (a 404 while closings are not LIVE, or another directory's
file) nothing is said about closings at all, and neither when the file is older than
:data:`FRESH` (a stopped reader's empty file is no sign that nothing is closed): the picture
is then not current, so the post may not call it so. A chance is shown only from a
predictions file no older than :data:`PREDICTIONS_FRESH`, for the next school day not yet
under way: the first of the file's own days whose :data:`SCHOOL_STARTS` local hour, in each
district's own time zone (the page's rule), is still ahead in most districts. A day already
under way is never named (at 11:27 AM Central on a Monday the chance is Tuesday's). The
browser is then served exactly the files described, and the render checks the page lit as
many schools as the description counts.
"""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from snowlight.directory.points import Points

ZOOM: Final = 6.5
"""The widest zoom of a closings view: a few states across on a 1600 x 900 picture."""
MAX_ZOOM: Final = 9.5
"""The closest a closings view zooms in on a few lit schools: a metro area across, where the
site still draws every school around them as a speck."""
FIT_BOX: Final = (800.0, 400.0)
"""The box in the middle of the picture (width, height in pixels) a closings view zoomed past
:data:`ZOOM` keeps every lit school of its window in, clear of the card's corners."""
MIN_SPECKS: Final = 400
"""The schools a closings view zoomed past :data:`ZOOM` holds at least (when a closer view
holds fewer, it steps back by :data:`ZOOM_STEP`), so a few lit schools in the country sit among
the specks of the towns around them, not alone in the dark."""
ZOOM_STEP: Final = 0.25
MOSTLY: Final = 0.5
"""A description says "mostly" of states only when they hold more than this share."""
SECOND_STATE: Final = 0.15
"""The least share a second state needs to be named beside the first."""
WIDTH: Final = 1600
HEIGHT: Final = 900
TILE: Final = 512
"""MapLibre's tile size in CSS pixels: the world is ``TILE * 2**zoom`` pixels across."""
PANEL_MIN_CHANCE: Final = 0.10
"""The chance of no school that earns a district's view instead of the national map."""
DISTRICT_X: Final = 0.34
"""Where a district's schools are centered across the picture (the card's text goes right)."""
DISTRICT_BOX: Final = (520.0, 560.0)
"""The most a district's schools may span in the picture, in pixels (width, height)."""
DISTRICT_ZOOMS: Final = (7.0, 12.0)
FRESH: Final = timedelta(minutes=20)
"""How old a closings file may be and still be called live (web/src/state/freshness.ts)."""
LEAD: Final = timedelta(minutes=2)
"""How far ahead of the clock a closings file may be stamped and still be live (the same)."""
PREDICTIONS_FRESH: Final = timedelta(minutes=90)
"""How old a predictions file may be and still be shown (web/src/data/school-day.ts)."""
PREDICTIONS_AHEAD: Final = timedelta(minutes=15)
"""How far ahead of the clock a predictions file may be stamped (the same)."""
EASTERN: Final = ZoneInfo("America/New_York")
"""The zone of a district the predictions file gives none (the earliest contiguous zone, so a
day is never taken for one not yet under way where it already is)."""
SCHOOL_STARTS: Final = 5
"""From 05:00 local a school day is under way: its chance is spent, and the next one's shows."""
EAST_OFFSET: Final = timedelta(hours=-4)
WEST_OFFSET: Final = timedelta(hours=-8)
SHOWN_ZONE: Final = ZoneInfo("America/Chicago")
"""The zone the picture's browser, its description and its card tell time in."""
ZONE_SHORT: Final = "CT"
MAX_CANDIDATES: Final = 2000
STATUS_KEYS: Final = ("closed", "delayed", "remote", "early_dismissal")
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

type Kind = Literal["closings", "district", "national", "region"]
"""``region`` is a calm view at a chosen place and zoom: a post's view when nothing is lit
(:func:`calm_regions`), or one asked for by hand for the image library."""


@dataclass(frozen=True, slots=True)
class Region:
    """A populous window the map shows as city lights (every school a faint speck)."""

    place: str
    lat: float
    lon: float
    zoom: float

    @property
    def query(self) -> str:
        return f"?at={self.lat:.4f},{self.lon:.4f},{self.zoom:g}"


REGIONS: Final[tuple[Region, ...]] = (
    Region("the Northeast corridor", 40.6000, -74.4000, 6.6),
    Region("the Great Lakes", 42.3000, -85.2000, 6.3),
    Region("the Mid-Atlantic", 38.9000, -77.6000, 7.0),
    Region("the Texas triangle", 30.6000, -96.9000, 6.8),
    Region("the Front Range", 39.7000, -105.0000, 7.4),
    Region("the Pacific Northwest", 46.9000, -122.6000, 7.0),
    Region("Southern California", 33.9000, -117.8000, 7.4),
)
"""The calm views a post may take when nothing is lit, each at a zoom between 5 and 10 (where
the site draws school specks), rotated by the run's slot of the day: morning, noon and evening
(:func:`calm_regions`, :func:`slot_of`)."""
REGION_TRIES: Final = 2
"""How many regions one render attempt tries before it takes the national map."""

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


class Box(BaseModel):
    """A box in the 1600 x 900 picture, in pixels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x0: float
    y0: float
    x1: float
    y1: float


class Counts(BaseModel):
    """Lit schools by status (the four the map draws)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    closed: int = Field(ge=0)
    delayed: int = Field(ge=0)
    remote: int = Field(ge=0)
    early_dismissal: int = Field(ge=0)

    @property
    def total(self) -> int:
        return self.closed + self.delayed + self.remote + self.early_dismissal

    def as_list(self) -> list[int]:
        return [self.closed, self.delayed, self.remote, self.early_dismissal]


class Chance(BaseModel):
    """A chance of no school the card may show as a number (the map draws none)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(pattern=r"^(<1|>99|[1-9][0-9]?)%$")
    """As the page writes it (:func:`chance_text`)."""
    day: date
    scope: Literal["district", "highest"]
    """``district``: the pictured district's, the highest of any; ``highest``: the highest of
    any district, not pictured (the national view)."""
    districts: int = Field(ge=1)
    """How many districts have a chance that day."""
    at_most: bool
    """Whether the highest chance rounds to 1% or less ("at most 1% in every district")."""


class Seen(BaseModel):
    """The picture's facts as fields: everything a card may print, filled by code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    in_view: Counts | None = None
    """Closings view: the lit schools inside the picture, by status."""
    states: tuple[str, ...] = Field(default=(), max_length=2)
    """Closings view: the states most of the lit schools in view are in, most first, only as
    :func:`_states` names them by share."""
    states_hold_all: bool = False
    """Closings view: every lit school in view is in :attr:`states` (one lit school, or all in
    one state), so a card says "In Nevada", never "Mostly Nevada"."""
    lit: int = Field(default=0, ge=0)
    """How many schools the map lights across the country."""
    closings_at: datetime | None = None
    """When the closings file was written (closings view)."""
    closings_read: bool = False
    """Whether the page read a closings file of the deployed directory (not a 404)."""
    chance: Chance | None = None
    state: str | None = None
    """District view: the district's state."""
    focus: Box | None = None
    """District view: the box its schools span in the picture."""
    place: str | None = Field(default=None, max_length=60)
    """Region view: the place's plain name. Closings view whose lit schools name no state by
    share: the states most of the view's public schools are in ("New Mexico"), said as the
    view's place ("over New Mexico"), never as where the lit schools are."""
    spots: tuple[tuple[int, int], ...] = ()
    """Closings view: where each lit school in view sits in the picture (x, y pixels), so a
    card's words are measured against every one of them (:func:`snowlight.social.cards.cover`)."""


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
    seen: Seen


def today_everywhere(now: datetime) -> date | None:
    """The day that is today in every contiguous US zone, or ``None`` (04:00-08:00 UTC)."""
    east = (now + EAST_OFFSET).date()
    west = (now + WEST_OFFSET).date()
    return east if east == west else None


def clock(moment: datetime) -> str:
    """The time in the shown zone, with the zone: "6:42 AM CT"."""
    local = moment.astimezone(SHOWN_ZONE)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'} {ZONE_SHORT}"  # noqa: PLR2004


def _clock(moment: datetime) -> str:
    return clock(moment).removesuffix(ZONE_SHORT) + "Central time"


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


def closings_read(closings: Mapping[str, object] | None, directory: Directory) -> bool:
    """Whether the page reads this closings file at all (one of the deployed directory)."""
    return closings is not None and closings.get("directory") == directory.stamp()


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
    if not closings_read(closings, directory):
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


def project(
    lon: npt.NDArray[np.float64], lat: npt.NDArray[np.float64], zoom: float
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Web Mercator world pixels at ``zoom``, as MapLibre draws them (512-pixel tiles)."""
    world = TILE * 2.0**zoom
    x = (lon + 180.0) / 360.0 * world
    sin = np.sin(np.radians(np.clip(lat, -85.05, 85.05)))
    y = (0.5 - np.log((1 + sin) / (1 - sin)) / (4 * np.pi)) * world
    return x, y


def unproject(x: float, y: float, zoom: float) -> tuple[float, float]:
    """The (lon, lat) of world pixel ``(x, y)`` at ``zoom``."""
    world = TILE * 2.0**zoom
    lon = x / world * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / world))))
    return lon, lat


def _held(points: Points, center: tuple[float, float], zoom: float) -> int:
    """How many of the directory's schools a picture at ``center`` (lon, lat) and ``zoom``
    holds."""
    x, y = project(
        points.lon_e6.astype(np.float64) / 1e6, points.lat_e6.astype(np.float64) / 1e6, zoom
    )
    cx, cy = project(np.array([center[0]]), np.array([center[1]]), zoom)
    return int(((np.abs(x - cx[0]) <= WIDTH / 2) & (np.abs(y - cy[0]) <= HEIGHT / 2)).sum())


def _fit(
    lon: npt.NDArray[np.float64], lat: npt.NDArray[np.float64], points: Points
) -> tuple[tuple[float, float], float] | None:
    """The center (lon, lat) and zoom past :data:`ZOOM` (at most :data:`MAX_ZOOM`, two
    decimals, rounded down) at which every point fits :data:`FIT_BOX` in the middle of the
    picture, stepped back while the picture holds fewer than :data:`MIN_SPECKS` of the
    directory's schools; ``None`` when they span too much to zoom past :data:`ZOOM`."""
    x, y = project(lon, lat, 0.0)
    span_x = max(float(x.max() - x.min()), 1e-12)
    span_y = max(float(y.max() - y.min()), 1e-12)
    fit = math.log2(min(FIT_BOX[0] / span_x, FIT_BOX[1] / span_y))
    # Two decimals, as a link carries a zoom (web/src/state/url.ts), rounded down to fit.
    zoom = math.floor(min(fit, MAX_ZOOM) * 100) / 100
    if zoom <= ZOOM:
        return None
    # The middle of the points, in world pixels at zoom 0 (the same place at every zoom).
    center = unproject(float(x.min() + x.max()) / 2, float(y.min() + y.max()) / 2, 0.0)
    while zoom - ZOOM_STEP > ZOOM and _held(points, center, zoom) < MIN_SPECKS:
        zoom = round(zoom - ZOOM_STEP, 2)
    return center, zoom


def busiest_view(
    lon: npt.NDArray[np.float64], lat: npt.NDArray[np.float64]
) -> tuple[tuple[float, float], npt.NDArray[np.bool_]]:
    """The center (lon, lat) of the picture-sized window at :data:`ZOOM` holding the most
    points, and which points it holds. Candidates are the points themselves (every k-th one
    past :data:`MAX_CANDIDATES`); ties go to the earlier point, so the choice is repeatable."""
    x, y = project(lon, lat, ZOOM)

    def inside(cx: float, cy: float) -> npt.NDArray[np.bool_]:
        held: npt.NDArray[np.bool_] = (np.abs(x - cx) <= WIDTH / 2) & (np.abs(y - cy) <= HEIGHT / 2)
        return held

    step = max(1, len(x) // MAX_CANDIDATES)
    best = -1
    center = (float(x[0]), float(y[0]))
    for index in range(0, len(x), step):
        count = int(inside(float(x[index]), float(y[index])).sum())
        if count > best:
            best, center = count, (float(x[index]), float(y[index]))
    held = inside(*center)
    # Centered on the lit schools it holds, which keeps (nearly) all of them in view.
    moved = (float(x[held].mean()), float(y[held].mean()))
    moved_held = inside(*moved)
    if int(moved_held.sum()) >= int(held.sum()):
        center, held = moved, moved_held
    return unproject(center[0], center[1], ZOOM), held


def _states(ids: Sequence[str]) -> list[str]:
    """The states most of ``ids`` are in, by share of all of them (a private school's id names
    no state, so it counts against every state): the top two when together they hold more
    than :data:`MOSTLY` and the second at least :data:`SECOND_STATE`; else the top one when
    it alone holds more than :data:`MOSTLY`; else none, so "mostly" is never said of a mix."""
    if not ids:
        return []
    counts = Counter(STATES.get(school[:2]) for school in ids if len(school) == 12)  # noqa: PLR2004
    counts.pop(None, None)
    top = [(name, count / len(ids)) for name, count in counts.most_common(2) if name is not None]
    if len(top) == 2 and top[1][1] >= SECOND_STATE and top[0][1] + top[1][1] > MOSTLY:  # noqa: PLR2004
        return [top[0][0], top[1][0]]
    if top and top[0][1] > MOSTLY:
        return [top[0][0]]
    return []


def _and(names: Sequence[str]) -> str:
    return " and ".join(names)


def _counts(statuses: npt.NDArray[np.int64]) -> Counts:
    counts = np.bincount(statuses, minlength=4)
    return Counts(
        closed=int(counts[0]),
        delayed=int(counts[1]),
        remote=int(counts[2]),
        early_dismissal=int(counts[3]),
    )


def _schools(count: int) -> str:
    return f"{count} {'school' if count == 1 else 'schools'}"


def _status_counts(counts: Counts) -> str:
    values = counts.as_list()
    return ", ".join(f"{values[code]} {STATUS_WORDS[code]}" for code in range(4) if values[code])


def _closings_picture(lit: Lit, directory: Directory, now: datetime) -> Picture:
    points = directory.points
    lon = points.lon_e6[lit.schools].astype(np.float64) / 1e6
    lat = points.lat_e6[lit.schools].astype(np.float64) / 1e6
    (center_lon, center_lat), held = busiest_view(lon, lat)
    zoom: float = ZOOM
    if (closer := _fit(lon[held], lat[held], points)) is not None:
        (center_lon, center_lat), zoom = closer
    in_view = lit.schools[held]
    x, y = project(lon[held], lat[held], zoom)
    cx, cy = project(np.array([center_lon]), np.array([center_lat]), zoom)
    spots = tuple(
        (round(float(px - cx[0] + WIDTH / 2)), round(float(py - cy[0] + HEIGHT / 2)))
        for px, py in zip(x, y, strict=True)
    )
    query = f"?at={center_lat:.4f},{center_lon:.4f},{zoom:g}"
    ids = [directory.school_ids[int(index)] for index in in_view]
    states = _states(ids)
    hold_all = bool(states) and all(
        len(school) == 12 and STATES.get(school[:2]) in states  # noqa: PLR2004
        for school in ids
    )
    # No state by share for the lit schools (private ones name none): the view's own place.
    over = None if states else _and(view_states(directory, query)) or None
    counts = _counts(lit.statuses[held])
    total = len(lit.schools)
    current = -LEAD <= now - lit.generated_at <= FRESH
    updated = (
        f"The closings were updated at {_clock(lit.generated_at)}."
        if current
        else f"The closings were last updated at {_clock(lit.generated_at)}, "
        f"{int((now - lit.generated_at).total_seconds() // 60)} minutes before the picture, "
        "so the map does not call them live."
    )
    place = (
        f", {'in' if hold_all else 'mostly in'} {_and(states)}"
        if states
        else f", in a view over {over}"
        if over
        else ""
    )
    shows = (
        f"A picture of the Snowlight map taken at {_clock(now)} on {_day(now)}, zoomed to the "
        f"area with the most schools lit up: {_schools(len(in_view))} "
        f"{'glows' if len(in_view) == 1 else 'glow'} in this view ({_status_counts(counts)})"
        f"{place}. Across the country the map shows {_schools(total)} closed, delayed, remote or"
        f" dismissing early for {_day_of(lit.day)}. {updated}"
    )
    seen = Seen(
        in_view=counts,
        states=tuple(states),
        states_hold_all=hold_all,
        place=over,
        lit=total,
        closings_at=lit.generated_at,
        closings_read=True,
        spots=spots,
    )
    return Picture("closings", query, shows, now, current, total, seen)


def _day_of(day: date) -> str:
    return f"{day:%B} {day.day}"


def _chance_day(predictions: Mapping[str, object], today: date) -> int | None:
    days = predictions.get("days")
    if not isinstance(days, list):
        raise PictureError("predictions: days is missing")
    return next((i for i, value in enumerate(days) if value == today.isoformat()), None)


def chance_day(predictions: Mapping[str, object], now: datetime) -> date | None:
    """The next school day not yet under way: the first of the file's days whose
    :data:`SCHOOL_STARTS` local hour is still ahead of ``now`` in more than half of the file's
    districts, each in its own time zone (``time_zone``; :data:`EASTERN` when it gives none or
    one this machine does not know). ``None`` when every day the file holds is under way.

    Raises:
        PictureError: the file's days or districts are malformed.
    """
    days = predictions.get("days")
    districts = predictions.get("districts")
    if not isinstance(days, list) or not all(isinstance(day, str) for day in days):
        raise PictureError("predictions: days is missing")
    if not isinstance(districts, list):
        raise PictureError("predictions: districts is missing")
    zones: Counter[str] = Counter()
    for row in districts:
        zone = row.get("time_zone") if isinstance(row, dict) else None
        zones[zone if isinstance(zone, str) else ""] += 1
    known: dict[str, ZoneInfo] = {}
    for name in zones:
        try:
            known[name] = ZoneInfo(name) if name else EASTERN
        except (ValueError, KeyError):  # ZoneInfoNotFoundError is a KeyError
            known[name] = EASTERN
    total = sum(zones.values())
    for text in sorted(days):
        try:
            day = date.fromisoformat(text)
        except ValueError:
            raise PictureError("predictions: a day is malformed") from None
        ahead = sum(
            count
            for name, count in zones.items()
            if datetime.combine(day, time(SCHOOL_STARTS), tzinfo=known[name]) > now
        )
        if total and ahead * 2 > total:
            return day
    return None


def predictions_fresh(predictions: Mapping[str, object], now: datetime) -> bool:
    """Whether the page shows this predictions file's chances at ``now`` (not stale).

    Raises:
        PictureError: its stamp is missing or malformed.
    """
    age = now - _instant(predictions.get("generated_at"), "predictions")
    return -PREDICTIONS_AHEAD <= age <= PREDICTIONS_FRESH


def highest_chance(
    predictions: Mapping[str, object] | None,
    directory: Directory,
    now: datetime,
) -> tuple[float, int, int, date] | None:
    """The highest chance of no school of any district on the next school day not yet under
    way (:func:`chance_day`), the district's index, how many districts have a chance that day,
    and the day; ``None`` without one, when every day of the file is under way, or when the
    file is stale (:data:`PREDICTIONS_FRESH`).

    Raises:
        PictureError: the file is malformed.
    """
    if predictions is None or predictions.get("directory") != directory.stamp():
        return None
    if not predictions_fresh(predictions, now):
        return None
    today = chance_day(predictions, now)
    if today is None:
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
    return best[0], best[1], counted, today


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


def district_frame(directory: Directory, index: int) -> tuple[str, Box] | None:
    """The ``?at=`` query that frames district ``index``'s schools on the left of the
    picture (centered at :data:`DISTRICT_X`, spanning at most :data:`DISTRICT_BOX`), and the
    box they span; ``None`` when the directory places no school in it."""
    points = directory.points
    mine = points.district == index
    if not bool(mine.any()):
        return None
    lon = points.lon_e6[mine].astype(np.float64) / 1e6
    lat = points.lat_e6[mine].astype(np.float64) / 1e6
    x, y = project(lon, lat, 0.0)
    span_x = max(float(x.max() - x.min()), 1e-9)
    span_y = max(float(y.max() - y.min()), 1e-9)
    fit = math.log2(min(DISTRICT_BOX[0] / span_x, DISTRICT_BOX[1] / span_y))
    # Two decimals, as a link carries a zoom (web/src/state/url.ts), rounded down to fit.
    zoom = math.floor(min(max(fit, DISTRICT_ZOOMS[0]), DISTRICT_ZOOMS[1]) * 100) / 100
    scale = 2.0**zoom
    mid_x = float(x.min() + x.max()) / 2 * scale
    mid_y = float(y.min() + y.max()) / 2 * scale
    lon_c, lat_c = unproject(mid_x + (WIDTH / 2 - DISTRICT_X * WIDTH), mid_y, zoom)
    left = DISTRICT_X * WIDTH - mid_x
    top = HEIGHT / 2 - mid_y
    box = Box(
        x0=round(float(x.min()) * scale + left, 1),
        y0=round(float(y.min()) * scale + top, 1),
        x1=round(float(x.max()) * scale + left, 1),
        y1=round(float(y.max()) * scale + top, 1),
    )
    return f"?at={lat_c:.5f},{lon_c:.5f},{zoom:.2f}", box


def _weekday(day: date) -> str:
    return f"{day:%A}"


def choose(  # noqa: PLR0913 - the live files, the time and the facts file's switches
    *,
    closings: Mapping[str, object] | None,
    predictions: Mapping[str, object] | None,
    directory: Directory,
    now: datetime,
    chances: bool,
    closings_shown: bool,
) -> Picture:
    """The view to take at ``now`` and its description (see the module's docstring).

    ``chances`` is the facts file's switch (:func:`snowlight.social.rules.chances_shown`):
    without it the predictions are not read at all, so the picture is never a district's
    chance and its description and facts hold no chance. ``closings_shown``
    (:func:`snowlight.social.rules.closings_shown`) is the closings switch: without it the
    closings file is not read at all, so the picture is never a closings view and its
    description and facts say nothing about closings.

    Raises:
        PictureError: a live file is malformed (the run then falls back to the library).
    """
    now = now.astimezone(UTC)
    if not closings_shown:
        closings = None
    lit = lit_schools(closings, directory, now)
    if lit is not None:
        return _closings_picture(lit, directory, now)
    read = closings_read(closings, directory)
    high = highest_chance(predictions, directory, now) if chances else None
    closings_line, current = calm_closings(closings, read, now)
    if high is not None and high[0] >= PANEL_MIN_CHANCE:
        chance, index, counted, today = high
        frame = district_frame(directory, index)
        if frame is not None:
            query, box = frame
            district = directory.district_ids[index]
            state = STATES.get(district[:2])
            where = f" in {state}" if state else ""
            shows = (
                f"A picture of the Snowlight map taken at {_clock(now)} on {_day(now)}, zoomed "
                f"to the schools of a public school district{where}: its chance of no school on "
                f"{_weekday(today)}, {_day_of(today)} is {chance_text(chance)}, the highest of "
                f"any district that day. The map does not draw the chance; the card shows it."
                f"{closings_line}"
            )
            seen = Seen(
                closings_read=read,
                chance=Chance(
                    text=chance_text(chance),
                    day=today,
                    scope="district",
                    districts=counted,
                    at_most=False,
                ),
                state=state,
                focus=box,
            )
            return Picture("district", query, shows, now, current, 0, seen)
    chance_seen: Chance | None = None
    on = high[3] if high is not None else None
    if high is None or on is None:
        chance_line = ""
    elif high[0] == 0 or _percent(high[0]) <= 1:
        chance_line = (
            f" Not in the picture: Snowlight's chance of no school on {_weekday(on)}, "
            f"{_day_of(on)} is at most {max(1, _percent(high[0]))}% in every one of the "
            f"{high[2]} districts with a chance."
        )
        chance_seen = Chance(
            text=chance_text(high[0]), day=on, scope="highest", districts=high[2], at_most=True
        )
    else:
        chance_line = (
            f" Not in the picture: Snowlight's highest chance of no school on {_weekday(on)},"
            f" {_day_of(on)} in any district is {chance_text(high[0])}."
        )
        chance_seen = Chance(
            text=chance_text(high[0]),
            day=on,
            scope="highest",
            districts=high[2],
            at_most=False,
        )
    shows = (
        f"A picture of the dark Snowlight map of the contiguous US taken at {_clock(now)} "
        f"on {_day(now)}: near-black land, gray state lines and city names. At this zoom the "
        f"map draws no school specks.{closings_line}{chance_line}"
    )
    seen = Seen(closings_read=read, chance=chance_seen)
    return Picture("national", "", shows, now, current, 0, seen)


def calm_closings(
    closings: Mapping[str, object] | None, read: bool, now: datetime
) -> tuple[str, bool]:
    """What a picture with no lit school may say about closings, and whether it is current.

    Only a closings file the page reads, written within :data:`FRESH`, says that no school is
    lit up; an older one (a stopped reader) says nothing and the picture is not current, so
    a post never calls a stale calm map current. Without a file (a 404) nothing
    is said about closings at all.
    """
    if not read or closings is None:
        return "", True
    if -LEAD <= now - _instant(closings.get("generated_at"), "closings.json") <= FRESH:
        return " No school is lit up for weather on the map.", True
    return "", False


SLOT_HOURS: Final = (11, 17)
"""The local hours (shown zone) that part a day's three scheduled runs (about 7 to 8 AM, 11:30
AM to 12:30 PM and 6:40 to 7:40 PM Central): a run before the first is the day's first slot."""


def slot_of(moment: datetime) -> int:
    """The run's slot: the shown zone's day times three, plus 0, 1 or 2 for the morning, noon
    and evening runs (:data:`SLOT_HOURS`), so each of a day's posts turns to a new view and
    headline, and the next day carries on."""
    local = moment.astimezone(SHOWN_ZONE)
    part = sum(1 for hour in SLOT_HOURS if local.hour >= hour)
    return local.date().toordinal() * (len(SLOT_HOURS) + 1) + part


def calm_regions(now: datetime) -> tuple[Region, ...]:
    """:data:`REGIONS` in the order a post at ``now`` tries them: rotated by the run's slot
    (:func:`slot_of`), so each of a day's posts opens on a different place."""
    start = slot_of(now) % len(REGIONS)
    return REGIONS[start:] + REGIONS[:start]


def view_states(directory: Directory, query: str) -> list[str]:
    """The states most of the directory's public schools in an ``?at=lat,lon,zoom`` view are
    in, by share (:func:`_states`), most first, at most two (none for a query that is not
    one, or a view whose schools no one or two states hold most of)."""
    parts = query.removeprefix("?at=").split(",")
    if not query.startswith("?at=") or len(parts) != 3:  # noqa: PLR2004
        return []
    try:
        lat, lon, zoom = (float(part) for part in parts)
    except ValueError:
        return []
    points = directory.points
    x, y = project(
        points.lon_e6.astype(np.float64) / 1e6, points.lat_e6.astype(np.float64) / 1e6, zoom
    )
    cx, cy = project(np.array([lon]), np.array([lat]), zoom)
    held = (np.abs(x - cx[0]) <= WIDTH / 2) & (np.abs(y - cy[0]) <= HEIGHT / 2)
    public = [directory.school_ids[int(index)] for index in np.flatnonzero(held)]
    return _states([school for school in public if len(school) == 12])  # noqa: PLR2004


def region(  # noqa: PLR0913 - the view, the live files, the time and the switch
    *,
    query: str,
    place: str,
    closings: Mapping[str, object] | None,
    directory: Directory,
    now: datetime,
    closings_shown: bool,
) -> Picture:
    """A calm view of ``place`` at a zoom where the map draws every school as a faint speck:
    a post's view when nothing is lit (:func:`calm_regions`), or the image library's. Only
    when the map lights no school. Without ``closings_shown`` the closings file is not read.
    The description names the states most of the view's public schools are in, only by
    share (:func:`_states`): none when no one or two states hold most of them.

    Raises:
        PictureError: the map lights schools now (take :func:`choose`'s view then).
    """
    now = now.astimezone(UTC)
    if not closings_shown:
        closings = None
    if lit_schools(closings, directory, now) is not None:
        raise PictureError("schools are lit: a calm region picture would leave them out")
    read = closings_read(closings, directory)
    closings_line, current = calm_closings(closings, read, now)
    states = view_states(directory, query)
    mostly = f", mostly {_and(states)}" if states else ""
    shows = (
        f"A picture of the dark Snowlight map over {place}{mostly}, taken at {_clock(now)} on "
        f"{_day(now)}: schools drawn as faint white specks, like city lights, with gray "
        f"state lines and city names.{closings_line}"
    )
    seen = Seen(closings_read=read, place=place)
    return Picture("region", query, shows, now, current, 0, seen)


class Taken(BaseModel):
    """``picture.json``: what the fresh picture shows, for the cards and the post step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Kind
    query: str = Field(max_length=80)
    shows: str = Field(min_length=20, max_length=800)
    taken_at: datetime
    current: bool
    lit: int = Field(ge=0)
    seen: Seen
    file: str = Field(pattern=r"^picture\.png$")
