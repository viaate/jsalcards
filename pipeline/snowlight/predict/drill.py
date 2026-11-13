"""``snowlight predict drill``: one scripted storm through the real pass, hour by hour, and the
storm-size night measured (predict-next STORM-DRILL). It serves nothing.

**The story.** Nine stories of one storm, each in its own made-up zone and state: real
districts of the committed model (picked by rule) on made-up points, NWS products scripted on
the story's own clock, the NDFD runs scripted through the real run assembly
(:func:`~snowlight.predict.ndfd.assemble_runs`), the real per-district forecast arithmetic
(:func:`~snowlight.predict.forecast_live.forecasts`) and the real settled reader
(:func:`~snowlight.predict.outlook_live.settled_reader`), the blend's night snow through the
real night reader, and the real loop (:func:`~snowlight.predict.cli.loop`) and pass on a faked
clock, from 3 AM Eastern on Monday to 6 PM Pacific on Tuesday. Publishing is on, to a host that
is a dictionary in this process's memory (:class:`DrillHost`): no host of the real world
exists here. The table reads, for each district at six moments on its own clock, what the
panel would show from the file the host held then.

**The storm-size night** (``--size``). Every district of the committed model and every private
school it holds on a 6-mile lattice of made-up points, a winter weather advisory over a share
of them upgraded to a winter storm warning at 8 PM Eastern, and nine passes through the night:
each pass's compute time, its file's sizes against the budget, and whether the file is whole;
then the frozen day's size.

The one copy of live code is :func:`drill_read` (the body of
:func:`~snowlight.predict.outlook_live.forecast_reader` with its two network parts scripted)
and :data:`ADJUST_COMPOSITION` (the reader :func:`~snowlight.predict.cli._adjust_reader`
builds); the drill's tests fail until a change to either is followed here.
"""

import argparse
import contextlib
import gzip
import hashlib
import io
import json
import math
import resource
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import shapely

from snowlight.directory.points import NO_DISTRICT, decode, encode
from snowlight.live import evidence
from snowlight.predict import anchor_labels, forecast_history, forecast_live, ndfd, serve
from snowlight.predict.alerts_live import UgcIndex
from snowlight.predict.artifact import ModelArtifact
from snowlight.predict.calendar import is_school_day
from snowlight.predict.config import PredictConfig
from snowlight.predict.exposure import Exposure
from snowlight.predict.forecast_values import Forecasts
from snowlight.predict.outlook_live import ADJUST_SECONDS, Budget, ReadForecast, settled_reader
from snowlight.predict.publish import Mode, State
from snowlight.predict.serve import PRIVATE, DeployedDirectory, ServeModel
from snowlight.predict.situations import Situation, WeatherClass
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import DayTimeline
from snowlight.schemas.predictions import Forecast, PredictionsFile
from snowlight.schemas.vocab import Reason, Status
from snowlight.sources.nws.alerts import NwsAlert, parse_active, parse_alert

if TYPE_CHECKING:
    from snowlight.predict.anchor import Anchor
    from snowlight.predict.cli import Pass

type Floats = npt.NDArray[np.float64]
type ReadRun = Callable[[ndfd.Run, date], forecast_history.RunValues]
type Script = Callable[[forecast_history.Schools, Mapping[str, int]], ReadRun]
type Feed = Callable[[], tuple[object, bool]]

DAY: Final = date(2027, 1, 12)
"""Tuesday D of the story; Monday D-1 and Wednesday D+1 (all school days, no clock change)."""
OFFICE: Final = "KDRL"
"""The made-up weather office of every product."""
START: Final = datetime(2027, 1, 11, 8, 0, tzinfo=UTC)
"""The story's first pass: 3 AM Eastern on Monday."""
UNTIL: Final = datetime(2027, 1, 13, 2, 0, tzinfo=UTC)
"""The story's end: 6 PM Pacific on Tuesday."""
FRESH: Final = timedelta(minutes=90)
"""The panel shows no number from a file older than this (``PREDICTIONS_FRESH_MS``,
``web/src/data/school-day.ts``; the drill's tests read it there)."""
AHEAD: Final = timedelta(minutes=15)
"""Nor from a file stamped more than this ahead of the reader's clock
(``PREDICTIONS_AHEAD_MS``, the same file)."""
UNDER_WAY_AT: Final = dtime(7, 30)
"""A school day is under way from this time on the school's clock, or once its buses have run
before it (``UNDER_WAY_AT`` and ``underWay``, ``web/src/app/chance.ts``)."""
MOVE_DAYS: Final = 6
"""The panel's move line names a run at most this many days back (``moved``,
``web/src/copy-chance.ts``)."""
LATEST: Final = "v1/predictions/latest.json"
TIMELINE: Final = f"v1/live/days/{DAY.isoformat()}.json"
CLOSING_MINUTE: Final = 465
"""7:45 AM: the ``daytwo`` schools post closed after 7:30 AM, when the day is under way."""
SCHEMA: Final = 1
ADJUST_COMPOSITION: Final = (
    "settled_reader(forecast_reader(fetcher, config.weather.covered_share, prune_days), budget)"
)
"""The reader ``cli._adjust_reader`` returns; the drill composes :func:`settled_reader` over
:func:`drill_read` the same way (its tests compare the two)."""
EDGE: Final = 0.03
"""A size under this share from its limit is said to be at the edge."""


@dataclass(frozen=True)
class Moment:
    """One moment the table reads: its name, its day against D, its time on the district's
    clock, and the day it reads the chance for (against D)."""

    name: str
    day: int
    at: dtime
    target: int


MOMENTS: Final = (
    Moment("d1_1600", -1, dtime(16, 0), 0),
    Moment("d1_2000", -1, dtime(20, 0), 0),
    Moment("d1_2130", -1, dtime(21, 30), 0),
    Moment("d0_0500", 0, dtime(5, 0), 0),
    Moment("d0_0630", 0, dtime(6, 30), 0),
    Moment("d0_1600", 0, dtime(16, 0), 1),
)


@dataclass(frozen=True)
class Story:
    """One story: its key, the risk rows it carries, its state, how many districts it picks and
    how many schools each has."""

    key: str
    rows: str
    state: str
    count: int
    schools: int = 1


STORIES: Final = (
    Story("watch", "B1 C3", "NY", 6),
    Story("cancel", "B3", "MA", 4),
    Story("late", "B4", "WA", 4),
    Story("daytwo", "B2", "MO", 4),
    Story("coldadv", "B5", "MN", 4),
    Story("half", "B6", "OH", 4, schools=5),
    Story("blizzard", "C1", "ND", 4),
    Story("extcold", "C2", "MT", 4),
    Story("overnight", "C4", "PA", 4),
)
SNOW: Final[Mapping[str, float]] = {
    "cancel": 8.0,
    "late": 6.0,
    "daytwo": 10.0,
    "coldadv": 0.0,
    "half": 8.0,
    "blizzard": 6.0,
    "extcold": 0.0,
    "overnight": 0.0,
}
"""Each story's inches at every school (``watch``: 3 in for picks 0, 2, 4 and 20 in for 1, 3,
5)."""
WATCH_SPLIT: Final = 10.0
"""The ``watch`` story's 3 in districts are under this, its 20 in districts over it."""
HALF_ZONE: Final = "OHZ955"
"""The ``half`` story's second zone (schools 2, 3 and 4 of each district), under no alert."""
FEELS: Final = 25.0
EXTREME_FEELS: Final = -35.0
OVERNIGHT_ICE: Final = 0.15
"""The ``overnight`` story's ice in runs from 1 AM on D (none in earlier runs)."""
MIXES: Final = ("worst", "typical")
"""The storm-size night's two forecast mixes: worst (snow, 0.05 in of ice and a 12 F morning
at every storm school, the upper bound) and typical (snow only, the lower bound)."""
SHARES: Final = (0.37, 0.70, 1.00)
GATE: Final = (0.37, "worst")
"""The world the CI gate judges (``--size``)."""
PASSES: Final = (
    dtime(0, 37),
    dtime(1, 7),
    dtime(2, 30),
    dtime(4, 7),
    dtime(5, 30),
    dtime(10, 7),
    dtime(11, 30),
    dtime(13, 7),
    dtime(14, 30),
)
"""The storm-size night's passes on D (UTC): the advisory, the upgrade, 9:30 PM Eastern,
9:07 PM Mountain, 9:30 PM Pacific and the morning, so every zone's four freezes are taken."""
EVENING: Final = 5
"""The first five passes are the evening's."""
UPGRADE: Final = datetime(2027, 1, 12, 1, 0, tzinfo=UTC)
PUBLIC_SCHOOLS: Final = 118_211 - 22_110
"""The deployed stamp's schools less its private ones."""
SPACING_MI: Final = 6.0
STORM_ZONE: Final = "KSZ999"
QUIET_ZONE: Final = "KSZ998"
STORM_HOURLY: Final = 0.6
"""The blend's snow an hour inside the storm."""


def local(zone: str, day: date, at: dtime) -> datetime:
    """``at`` on ``day`` on ``zone``'s clock, in UTC."""
    return datetime.combine(day, at, tzinfo=ZoneInfo(zone)).astimezone(UTC)


def _hm(hour: int, minute: int = 0) -> dtime:
    return dtime(hour, minute)


def inches_of(story: Story, k: int) -> float:
    """The snow at every school of pick ``k`` of ``story``."""
    if story.key == "watch":
        return 3.0 if k % 2 == 0 else 20.0
    return SNOW[story.key]


# --- The world --------------------------------------------------------------------------------


def pick(committed: ModelArtifact, exposure: Exposure, story: Story) -> tuple[str, ...]:
    """The story's districts: those of its state in the state's most common time zone, ordered
    by their winter storm warning days a winter (``None`` as 0), then LEAID, at the places
    ``round(i (n - 1) / (k - 1))``.

    Raises:
        ValueError: the state has fewer such districts than the story picks.
    """
    zones = Counter(v.time_zone for v in committed.districts.values() if v.state == story.state)
    if not zones:
        raise ValueError(f"{story.key}: no district in {story.state}")
    common = zones.most_common(1)[0][0]
    found = sorted(
        ((exposure.of(leaid, v.county)[0] or (0.0, 0.0))[1], leaid)
        for leaid, v in committed.districts.items()
        if v.state == story.state and v.time_zone == common
    )
    n = len(found)
    if n < story.count:
        raise ValueError(f"{story.key}: {n} districts in {story.state}, {story.count} asked")
    if story.count == 1:
        return (found[0][1],)
    return tuple(found[round(i * (n - 1) / (story.count - 1))][1] for i in range(story.count))


@dataclass(frozen=True)
class Product:
    """One scripted NWS product: when it was sent, its VTEC strings, its story and zone, its
    event, and its span."""

    sent: datetime
    vtec: tuple[str, ...]
    story: str
    zone: str
    event: str
    onset: datetime
    ends: datetime

    @property
    def ending(self) -> bool:
        """Whether every VTEC string ends an event (``CAN`` or ``UPG``)."""
        return all(".CAN." in v or ".UPG." in v for v in self.vtec)


def vtec(action: str, code: str, etn: int, start: datetime, end: datetime) -> str:
    """A VTEC string of the drill's office."""
    return f"/O.{action}.{OFFICE}.{code}.{etn:04d}.{start:%y%m%dT%H%MZ}-{end:%y%m%dT%H%MZ}/"


@dataclass(frozen=True)
class World:
    """The story's world: the districts, their stories, picks, inches and zones, the directory,
    the zone shapes, each story's time zone and the products."""

    leaids: tuple[str, ...]
    stories: tuple[Story, ...]
    picks: tuple[int, ...]
    inches: tuple[float, ...]
    district_of: tuple[int, ...]
    """Each school's district."""
    directory: DeployedDirectory
    areas: Mapping[str, shapely.Geometry]
    zone_of: Mapping[str, str]
    """Each story's zone code."""
    tz_of: Mapping[str, str]
    """Each story's time zone."""
    products: tuple[Product, ...]

    def of(self, key: str) -> list[int]:
        """The districts of a story."""
        return [i for i, story in enumerate(self.stories) if story.key == key]


def build_world(committed: ModelArtifact, exposure: Exposure) -> World:
    """The story's world (What 3): the picks on made-up points, one zone a story."""
    leaids: list[str] = []
    stories: list[Story] = []
    picks: list[int] = []
    lon: list[int] = []
    lat: list[int] = []
    district_of: list[int] = []
    areas: dict[str, shapely.Geometry] = {}
    zone_of: dict[str, str] = {}
    tz_of: dict[str, str] = {}
    for s, story in enumerate(STORIES):
        chosen = pick(committed, exposure, story)
        x0 = -120.0 + 5.0 * s
        code = f"{story.state}Z9{s:02d}"
        areas[code] = shapely.box(x0 - 1, 30.0, x0 + 1.5, 45.0)
        zone_of[story.key] = code
        zone = committed.districts[chosen[0]].time_zone
        if zone is None:
            raise ValueError(f"{story.key}: no time zone")
        tz_of[story.key] = zone
        if story.key == "half":
            areas[HALF_ZONE] = shapely.box(x0 + 2, 30.0, x0 + 4, 45.0)
        for k, leaid in enumerate(chosen):
            index = len(leaids)
            leaids.append(leaid)
            stories.append(story)
            picks.append(k)
            for j in range(story.schools):
                x = x0 + (3.0 if story.key == "half" and j >= 2 else 0.0) + 0.0001 * j  # noqa: PLR2004
                lon.append(round(x * 1e6))
                lat.append(round((31.0 + k) * 1e6))
                district_of.append(index)
    count = len(lon)
    stamp = DirectoryStamp(generated_on=date(2026, 10, 14), schools=count, districts=len(leaids))
    points = decode(encode(lon, lat, district_of, [0] * count, len(leaids)))
    directory = DeployedDirectory(
        stamp,
        tuple(leaids),
        points,
        school_ids=tuple(f"{i:012d}" for i in range(1, count + 1)),
    )
    return World(
        leaids=tuple(leaids),
        stories=tuple(stories),
        picks=tuple(picks),
        inches=tuple(inches_of(st, k) for st, k in zip(stories, picks, strict=True)),
        district_of=tuple(district_of),
        directory=directory,
        areas=areas,
        zone_of=zone_of,
        tz_of=tz_of,
        products=story_products(zone_of, tz_of),
    )


def story_products(zone_of: Mapping[str, str], tz_of: Mapping[str, str]) -> tuple[Product, ...]:
    """The storm's products (What 2), in the order they were sent."""
    before, after = DAY - timedelta(days=1), DAY + timedelta(days=1)
    found: list[Product] = []

    def add(
        key: str,
        sent: datetime,
        strings: tuple[str, ...],
        event: str,
        span: tuple[datetime, datetime],
    ) -> None:
        found.append(Product(sent, strings, key, zone_of[key], event, *span))

    def span(
        key: str, start: tuple[date, dtime], end: tuple[date, dtime]
    ) -> tuple[datetime, datetime]:
        return local(tz_of[key], *start), local(tz_of[key], *end)

    def sent(key: str, day: date, at: dtime) -> datetime:
        return local(tz_of[key], day, at)

    on, end = span("watch", (before, _hm(22)), (DAY, _hm(18)))
    add(
        "watch",
        sent("watch", before, _hm(4)),
        (vtec("NEW", "WS.A", 1, on, end),),
        "Winter Storm Watch",
        (on, end),
    )
    add(
        "watch",
        sent("watch", before, _hm(17)),
        (vtec("NEW", "WS.W", 10, on, end), vtec("UPG", "WS.A", 1, on, end)),
        "Winter Storm Warning",
        (on, end),
    )
    on, end = span("cancel", (before, _hm(23)), (DAY, _hm(15)))
    add(
        "cancel",
        sent("cancel", before, _hm(15)),
        (vtec("NEW", "WS.W", 2, on, end),),
        "Winter Storm Warning",
        (on, end),
    )
    add(
        "cancel",
        sent("cancel", DAY, _hm(4, 30)),
        (vtec("CAN", "WS.W", 2, on, end),),
        "Winter Storm Warning",
        (on, end),
    )
    on, end = span("late", (DAY, _hm(10)), (after, _hm(1)))
    add(
        "late",
        sent("late", before, _hm(15)),
        (vtec("NEW", "WS.W", 3, on, end),),
        "Winter Storm Warning",
        (on, end),
    )
    on, end = span("daytwo", (before, _hm(21)), (DAY, _hm(17)))
    add(
        "daytwo",
        sent("daytwo", before, _hm(14)),
        (vtec("NEW", "WS.W", 4, on, end),),
        "Winter Storm Warning",
        (on, end),
    )
    on, end = span("coldadv", (DAY, _hm(3)), (DAY, _hm(10)))
    add(
        "coldadv",
        sent("coldadv", before, _hm(15)),
        (vtec("NEW", "CW.Y", 5, on, end),),
        "Cold Weather Advisory",
        (on, end),
    )
    on, end = span("half", (before, _hm(22)), (DAY, _hm(14)))
    add(
        "half",
        sent("half", before, _hm(15)),
        (vtec("NEW", "WS.W", 6, on, end),),
        "Winter Storm Warning",
        (on, end),
    )
    on, end = span("blizzard", (before, _hm(22)), (DAY, _hm(18)))
    add(
        "blizzard",
        sent("blizzard", before, _hm(15)),
        (vtec("NEW", "BZ.W", 7, on, end),),
        "Blizzard Warning",
        (on, end),
    )
    on, end = span("extcold", (DAY, _hm(0)), (DAY, _hm(11)))
    add(
        "extcold",
        sent("extcold", before, _hm(15)),
        (vtec("NEW", "EC.W", 8, on, end),),
        "Extreme Cold Warning",
        (on, end),
    )
    on, end = span("overnight", (DAY, _hm(5)), (DAY, _hm(11)))
    add(
        "overnight",
        sent("overnight", DAY, _hm(3)),
        (vtec("NEW", "ZR.Y", 9, on, end),),
        "Freezing Rain Advisory",
        (on, end),
    )
    return tuple(sorted(found, key=lambda p: p.sent))


# --- The feeds --------------------------------------------------------------------------------


def feature(product: Product) -> dict[str, object]:
    """A product as one feature of the service's ``/alerts/active`` body. A product whose every
    VTEC string is ``CAN`` or ``UPG`` expires 60 minutes after it was sent."""
    expires = product.sent + timedelta(hours=1) if product.ending else product.ends
    if any(".CAN." in v for v in product.vtec):
        kind = "Cancel"
    elif any(".UPG." in v for v in product.vtec):
        kind = "Update"
    else:
        kind = "Alert"
    return {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "id": f"urn:drill:{product.story}:{product.sent:%Y%m%dT%H%M}",
            "event": product.event,
            "status": "Actual",
            "messageType": kind,
            "severity": "Moderate",
            "sent": product.sent.isoformat(),
            "effective": product.sent.isoformat(),
            "onset": product.onset.isoformat(),
            "expires": expires.isoformat(),
            "ends": product.ends.isoformat(),
            "affectedZones": [],
            "geocode": {"UGC": [product.zone]},
            "parameters": {"VTEC": list(product.vtec)},
        },
    }


def active_at(products: Sequence[Product], at: datetime) -> list[Product]:
    """The products in the feed at ``at``: the latest sent per event (office, code, ETN); a
    product leaves at its end, and an ending one 60 minutes after it was sent."""
    latest: dict[tuple[str, str, str], Product] = {}
    for product in products:
        if product.sent > at:
            continue
        for string in product.vtec:
            parts = string.strip("/").split(".")
            latest[(parts[2], f"{parts[3]}.{parts[4]}", parts[5])] = product
    found: dict[int, Product] = {}
    for product in latest.values():
        gone = at - product.sent >= timedelta(hours=1) if product.ending else at >= product.ends
        if not gone:
            found[id(product)] = product
    return sorted(found.values(), key=lambda p: p.sent)


def active_feed(products: Sequence[Product], at: datetime) -> bytes:
    """The ``/alerts/active`` body at ``at``."""
    body = {
        "type": "FeatureCollection",
        "updated": at.isoformat(),
        "features": [feature(p) for p in active_at(products, at)],
    }
    return json.dumps(body).encode()


def history_of(products: Sequence[Product], start: datetime, end: datetime) -> list[NwsAlert]:
    """Every product sent in ``[start, end]``, as the history reads it."""
    return [parse_alert(feature(p)) for p in products if start <= p.sent <= end]


def feeds(
    products: Sequence[Product], now: Callable[[], datetime]
) -> tuple[Feed, Callable[[datetime, datetime], Sequence[NwsAlert]]]:
    """``Pass.alerts`` and ``Pass.history`` over the scripted products."""

    def alerts() -> tuple[object, bool]:
        return parse_active(active_feed(products, now())), True

    def history(start: datetime, end: datetime) -> Sequence[NwsAlert]:
        return history_of(products, start, end)

    return alerts, history


def listed_for(day: date) -> list[ndfd.Listed]:
    """The scripted NDFD listing of a night: every element, one stamp an hour from 00:00Z the
    day before for 48 hours, each written 50 minutes after its stamp."""
    first = datetime.combine(day - timedelta(days=1), dtime(0), UTC)
    found: list[ndfd.Listed] = []
    for hour in range(48):
        stamp = first + timedelta(hours=hour)
        found.extend(
            ndfd.Listed(
                element,
                stamp,
                f"drill://ndfd/{element.value}/{stamp:%Y%m%d%H}",
                ndfd.Host.AWS,
                stamp + timedelta(minutes=50),
            )
            for element in ndfd.ELEMENTS
        )
    return found


def runs_for(day: date) -> list[ndfd.Run]:
    """The runs a night can use, by the real rule (:func:`ndfd.assemble_runs`)."""
    return list(ndfd.assemble_runs(listed_for(day)).runs)


def drill_read(share: float, script: Script) -> ReadForecast:
    """The drill's copy of :func:`~snowlight.predict.outlook_live.forecast_reader`'s body: the
    deciding schools and the LEAID index built once per directory stamp, then the real
    :func:`~snowlight.predict.forecast_live.forecasts`, with its two network parts scripted
    (:func:`runs_for`, and ``script``'s run reader). No listing, cache or prune is copied.
    The drill's tests fail until a change to the live reader is followed here."""
    built: dict[object, tuple[forecast_history.Schools, dict[str, int], ReadRun]] = {}

    def read(
        model: ServeModel,
        days: tuple[date, ...],
        now: datetime,
        moment: Callable[[date, str], datetime] | None,
        zones: Collection[str] | None,
    ) -> Forecasts:
        stamp = model.directory.stamp
        if stamp not in built:
            built.clear()
            schools = forecast_history.deciding_schools(model.directory, model.artifact)
            index = {leaid: i for i, leaid in enumerate(model.directory.district_ids)}
            built[stamp] = (schools, index, script(schools, index))
        schools, index, reader = built[stamp]
        return forecast_live.forecasts(
            schools,
            index,
            days,
            now,
            runs_for,
            reader,
            share,
            moment=moment if moment is not None else (lambda _day, _zone: now),
            zones=zones,
        )

    return read


def adjust_reader(
    config: PredictConfig, script: Script
) -> Callable[[ServeModel, tuple[date, ...], datetime], Forecasts]:
    """``Pass.forecast``: :data:`ADJUST_COMPOSITION` over :func:`drill_read`."""
    budget = Budget(seconds=ADJUST_SECONDS)
    return settled_reader(drill_read(config.weather.covered_share, script), budget)


def _halves(values: Floats, ends: Sequence[datetime]) -> dict[datetime, Floats]:
    """Half of ``values`` in each period ending 12:00Z and 18:00Z, none in the others."""
    zero = np.zeros_like(values)
    return {end: (values / 2 if end.hour in {12, 18} else zero) for end in ends}


def story_script(world: World) -> Script:
    """The story's run values (What 2): each school's inches, half in the periods ending 12:00Z
    and 18:00Z of D and D+1 (none on D-1); the ``overnight`` story's ice in runs from 1 AM on D;
    feels -35 F at 7 AM in the ``extcold`` story, else 25 F."""
    keys = [story.key for story in world.stories]
    ice_from = local(world.tz_of["overnight"], DAY, dtime(1))

    def script(schools: forecast_history.Schools, index: Mapping[str, int]) -> ReadRun:
        idx = [index[schools.districts[d]] for d in schools.district]
        snow = np.array([world.inches[i] for i in idx], dtype=np.float64)
        over = np.array([keys[i] == "overnight" for i in idx], dtype=bool)
        cold = np.array([keys[i] == "extcold" for i in idx], dtype=bool)
        zones = sorted(set(schools.zone_of_district))

        def reader(run: ndfd.Run, day: date) -> forecast_history.RunValues:
            ends = ndfd.window_ends(day)
            some = day >= DAY
            total = snow if some else np.zeros_like(snow)
            ice = np.where(over & (run.time >= ice_from) & some, OVERNIGHT_ICE, 0.0)
            feels = {
                ndfd.bus_time(day, zone): np.where(cold, EXTREME_FEELS, FEELS) for zone in zones
            }
            return forecast_history.RunValues(run, _halves(total, ends), _halves(ice, ends), feels)

        return reader

    return script


def story_blend(world: World) -> Callable[..., tuple[datetime, dict[datetime, Floats]]]:
    """The blend's night snow (What 4): the cycle ``now`` floored to the hour less one hour and,
    each hour, 0.5 in at every point of a column ``[x0 - 1, x0 + 4)`` whose story has snow."""
    snowy = [any(world.inches[i] > 0 for i in world.of(st.key)) for st in STORIES]

    def blend(
        lat: Floats, lon: Floats, hours: set[datetime], now: datetime, _max_age: timedelta
    ) -> tuple[datetime, dict[datetime, Floats]]:
        del lat
        cycle = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        column = np.floor((lon + 121.0) / 5.0).astype(np.int64)
        inside = np.array([0 <= c < len(STORIES) and snowy[c] for c in column], dtype=bool)
        return cycle, {hour: np.where(inside, 0.5, 0.0) for hour in hours}

    return blend


# --- The host and the clock -------------------------------------------------------------------


class DrillHost:
    """The pass's host: a dictionary in this process's memory, and a log of every write (the
    faked clock's time, the key, the bytes), so a cell reads what the host held at a moment. A
    read gives at once what the last write left, so every read-back of the pass (the publish,
    the switch, the stamp) confirms at its first read and no read-back ever waits: the pass's
    own wait before a second read (2, 4 and 8 s) is the real ``time.sleep``, which the drill
    does not inject (that would change served code), so a host that did not confirm at once
    would make the story sleep for real. The drill's tests fail on any sleep."""

    def __init__(self, now: Callable[[], datetime]) -> None:
        self.held: dict[str, bytes] = {}
        self.log: list[tuple[datetime, str, bytes]] = []
        self.reads: list[str] = []
        self._now = now

    def read(self, key: str) -> bytes | None:
        """The bytes held at ``key``."""
        self.reads.append(key)
        return self.held.get(key)

    def write(self, files: Mapping[str, bytes]) -> None:
        """Hold every file, and log it."""
        at = self._now()
        for key, data in files.items():
            self.held[key] = data
            self.log.append((at, key, data))

    def held_at(self, key: str, at: datetime) -> bytes | None:
        """The bytes the host held at ``key`` at ``at`` (the last write at or before it)."""
        found = None
        for when, written, data in self.log:
            if written == key and when <= at:
                found = data
        return found

    def uploads(self) -> list[tuple[datetime, bytes]]:
        """Every predictions file written, with when."""
        return [(when, data) for when, key, data in self.log if key == LATEST]


@dataclass
class FakeClock:
    """The faked clock: ``sleep`` moves it on and runs each event whose time has come."""

    at: datetime
    events: list[tuple[datetime, Callable[[], None]]] = field(default_factory=list)

    def now(self) -> datetime:
        """The faked time."""
        return self.at

    def sleep(self, seconds: float) -> None:
        """Move on ``seconds``, then run the events due."""
        self.at += timedelta(seconds=seconds)
        while self.events and self.events[0][0] <= self.at:
            _due, run = self.events.pop(0)
            run()


def _ugcs(areas: Mapping[str, shapely.Geometry]) -> Callable[[DeployedDirectory], UgcIndex]:
    """``Pass.ugcs``: each school's zone among ``areas``."""

    def ugcs(directory: DeployedDirectory) -> UgcIndex:
        lon = np.asarray(directory.points.lon_e6, dtype=np.float64) * 1e-6
        lat = np.asarray(directory.points.lat_e6, dtype=np.float64) * 1e-6
        return UgcIndex.build(lon, lat, areas)

    return ugcs


def closing_timeline(world: World, at: datetime) -> DayTimeline:
    """The ``daytwo`` schools' day timeline of D (What 5): one change each at 7:45 AM, closed for
    a winter storm, its gaps as the live ingest writes them (``live/history.py``)."""
    closers = [j for j, d in enumerate(world.district_of) if world.stories[d].key == "daytwo"]
    gaps = tuple(b - a - 1 for a, b in zip([-1, *closers], closers, strict=False))
    n = len(closers)
    return DayTimeline(
        schema_version=1,
        day=DAY,
        generated_at=at,
        directory=world.directory.stamp,
        content_sha256=None,
        final=False,
        gaps=gaps,
        counts=(1,) * n,
        minutes=(CLOSING_MINUTE,) * n,
        statuses=(Status.CLOSED,) * n,
        reasons=(Reason.WINTER_STORM,) * n,
        shifts=(),
        clocks=(),
    )


# --- The story --------------------------------------------------------------------------------


@dataclass
class StoryRun:
    """One run of the story: the world, the pass, the host, the clock's end, and what the run
    printed and measured."""

    world: World
    run: "Pass"
    host: DrillHost
    model: ServeModel
    anchor: "Anchor | None"
    passes: int
    dark: int
    seconds: float
    out: list[str]
    err: list[str]
    frozen_raw: int
    frozen_xz: int


def story_drill(
    config: PredictConfig,
    committed: ModelArtifact,
    exposure: Exposure,
    labels: Path,
    folder: Path,
) -> StoryRun:
    """Run the story (What 5 and 6): the real loop over the real pass on a faked clock from
    :data:`START` to :data:`UNTIL`, publishing on to a :class:`DrillHost`; the pass's lines are
    kept, never printed. ``folder``: the frozen record's folder (removed by the caller)."""
    from snowlight.predict import cli  # noqa: PLC0415 - cli imports this module at its top

    for day in (DAY - timedelta(days=1), DAY, DAY + timedelta(days=1)):
        if not is_school_day(day):
            raise ValueError(f"{day} is not a school day")
    world = build_world(committed, exposure)
    anchor = anchor_labels.serving_anchor(config, committed, folder=labels)
    clock = FakeClock(START)
    host = DrillHost(clock.now)
    closing = local(world.tz_of["daytwo"], DAY, dtime(7, 45))

    def post() -> None:
        host.write({TIMELINE: closing_timeline(world, clock.at).to_json_bytes()})

    clock.events.append((closing, post))
    alerts, history = feeds(world.products, clock.now)
    areas = world.areas
    run = cli.Pass(
        config=config,
        mode=Mode.ON,
        host=host,
        directory=lambda: world.directory,
        alerts=alerts,
        ugcs=_ugcs(areas),
        zone_fallback=lambda _lon, _lat: None,
        model=lambda: committed,
        state=State(),
        anchor=anchor,
        now=clock.now,
        history=history,
        forecast=adjust_reader(config, story_script(world)),
        frozen=folder,
        night=cli.night_reader(
            story_blend(world), timedelta(minutes=config.serve.chart_nbm_max_age_minutes)
        ),
    )
    out, err = io.StringIO(), io.StringIO()
    started = time.monotonic()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        dark = cli.loop(run, UNTIL, cli.Loop(clock.now, clock.sleep), lambda _state: None)
    seconds = time.monotonic() - started
    lines = out.getvalue().splitlines()
    raw = (folder / f"{DAY.isoformat()}.jsonl").read_bytes()
    return StoryRun(
        world=world,
        run=run,
        host=host,
        model=run.serve_model(world.directory),
        anchor=anchor,
        passes=sum(1 for line in lines if line.startswith("predict: pass ")),
        dark=dark,
        seconds=seconds,
        out=lines,
        err=err.getvalue().splitlines(),
        frozen_raw=len(raw),
        frozen_xz=len(evidence.compress(raw, evidence.PRESETS[evidence.FROZEN])),
    )


@dataclass(frozen=True)
class Cell:
    """What the panel would show for one district at one moment (What 7)."""

    p: int
    prev: int | None
    said: str | None
    """``up``, ``down`` or ``same`` (the panel's move line), or ``None``."""
    base: str
    points: int | None
    borrowed: bool
    alert: bool
    """The day names an alert's weather (``Forecast.reasons`` not empty)."""
    forecast: bool
    """A forecast line shows (a reason of :data:`serve.ADJUST_KINDS`)."""
    after: bool
    """The district is in ``serve.closed_districts`` of the day before's timeline as held."""
    night: bool = False
    """The day carries a night chart (not in the JSON)."""

    @property
    def calm(self) -> bool:
        """The calm-day number: 1% and no alert's weather."""
        return self.p == 1 and not self.alert

    def text(self) -> str:
        """``NN%``, the move line, the base's letter and the marks (``b``, ``f``, ``a``)."""
        found = f"{self.p}%"
        if self.said is not None:
            found += {"up": " ^", "down": " v", "same": " ="}[self.said] + str(self.prev)
        found += " " + BASE_LETTERS[self.base]
        found += ("b" if self.borrowed else "") + ("f" if self.forecast else "")
        return found + ("a" if self.after else "")

    def as_json(self) -> dict[str, object]:
        """The cell's JSON (no ``night``)."""
        return {
            "p": self.p,
            "prev": self.prev,
            "said": self.said,
            "base": self.base,
            "points": self.points,
            "borrowed": self.borrowed,
            "alert": self.alert,
            "forecast": self.forecast,
            "after": self.after,
        }


BASE_LETTERS: Final = {
    "class": "C",
    "pooled": "P",
    "alert": "A",
    "day_after": "D",
    "similar_days": "S",
}
NO_NUMBER: Final = "--"
NOT_IN_FILE: Final = "n/a"
OTHER_DAY: Final = "off"
"""The panel shows no chance for the moment's day: it heads another day, or none (the day is
under way or decided)."""
type CellValue = Cell | str


def _text(cell: CellValue) -> str:
    return cell if isinstance(cell, str) else cell.text()


def calm(cell: CellValue) -> bool:
    """Whether a cell shows the calm-day number (``--`` and ``n/a`` never do)."""
    return isinstance(cell, Cell) and cell.calm


def moment_at(world: World, i: int, moment: Moment) -> datetime:
    """When ``moment`` is on district ``i``'s clock."""
    return local(world.tz_of[world.stories[i].key], DAY + timedelta(days=moment.day), moment.at)


def percent(chance: float) -> int:
    """A chance in whole percent as the panel rounds it (``Math.round``: halves up, where
    Python's ``round`` takes halves to the even number)."""
    return math.floor(chance * 100 + 0.5)


def under_way(day: date, at: datetime, zone: ZoneInfo, buses: datetime | None) -> bool:
    """Whether school ``day`` is under way at ``at`` on the school's clock (the panel's
    ``underWay``): once its buses have run, where the file says when on that day, or from
    :data:`UNDER_WAY_AT`."""
    if buses is not None and buses.astimezone(zone).date() == day and at >= buses:
        return True
    return at >= datetime.combine(day, UNDER_WAY_AT, zone)


def headline_day(
    days: Sequence[tuple[date, object]], at: datetime, zone: ZoneInfo, decided: Collection[date]
) -> date | None:
    """The day the panel heads (its ``headlineDay``): the first of ``days`` (the district's
    today and the file's next day, each with its entry) that is not decided, has a forecast
    and is not under way at ``at``; ``None`` when none is."""
    for day, item in days:
        if day in decided or not isinstance(item, Forecast):
            continue
        if under_way(day, at, zone, item.buses_at):
            continue
        return day
    return None


def cells(story: StoryRun, config: PredictConfig) -> dict[tuple[int, str], CellValue]:
    """Every district's cell at every moment, as the panel would show it from the last upload
    at or before the moment on the district's clock: ``--`` when that file is over
    :data:`FRESH` old or :data:`AHEAD` ahead, ``n/a`` when the moment's day or the district is
    not in it, ``off`` when the panel heads another day (or none), else the moment's day's
    chance."""
    world = story.world
    uploads = [(when, PredictionsFile.from_json_bytes(data)) for when, data in story.host.uploads()]
    share = config.weather.covered_share
    after: dict[tuple[date, datetime], frozenset[int]] = {}

    def closed(day: date, at: datetime) -> frozenset[int]:
        if (day, at) not in after:
            data = story.host.held_at(f"v1/live/days/{day.isoformat()}.json", at)
            after[(day, at)] = (
                frozenset()
                if data is None
                else serve.closed_districts(
                    DayTimeline.model_validate_json(data), story.model, share
                )
            )
        return after[(day, at)]

    found: dict[tuple[int, str], CellValue] = {}
    for i in range(len(world.leaids)):
        zone = ZoneInfo(world.tz_of[world.stories[i].key])
        for moment in MOMENTS:
            at = moment_at(world, i, moment)
            made = next((f for when, f in reversed(uploads) if when <= at), None)
            day = DAY + timedelta(days=moment.target)
            if made is None or not -AHEAD <= at - made.generated_at <= FRESH:
                found[(i, moment.name)] = NO_NUMBER
                continue
            entry = next((e for e in made.districts if e.district == i), None)
            today = at.astimezone(zone).date()
            if entry is None or day not in made.days or today not in made.days:
                found[(i, moment.name)] = NOT_IN_FILE
                continue
            item = entry.days[made.days.index(day)]
            if not isinstance(item, Forecast):
                found[(i, moment.name)] = NOT_IN_FILE
                continue
            first = made.days.index(today)
            heads = [(d, entry.days[first + k]) for k, d in enumerate(made.days[first : first + 2])]
            decided = {d for d, _item in heads if i in closed(d, at)}
            if headline_day(heads, at, zone, decided) != day:
                found[(i, moment.name)] = OTHER_DAY
                continue
            found[(i, moment.name)] = _cell(
                item, at, zone, i in closed(day - timedelta(days=1), at)
            )
    return found


def _cell(item: Forecast, at: datetime, zone: ZoneInfo, after: bool) -> Cell:
    p = percent(item.p_no_school)
    prev = said = None
    if item.previous is not None:
        days = (at.astimezone(zone).date() - item.previous.at.astimezone(zone).date()).days
        if 0 <= days <= MOVE_DAYS and item.previous.at <= at:
            prev = percent(item.previous.p_no_school)
            said = "up" if prev < p else "down" if prev > p else "same"
    base = item.why.base
    return Cell(
        p=p,
        prev=prev,
        said=said,
        base=base.kind,
        points=getattr(base, "points", None),
        borrowed=bool(getattr(base, "borrowed", False)),
        alert=bool(item.reasons),
        forecast=any(r.kind in serve.ADJUST_KINDS for r in item.why.reasons),
        after=after,
        night=item.night is not None,
    )


# --- The verdicts -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """One risk row: whether it still shows, and its numbers."""

    row: str
    shows: bool
    line: str

    def text(self) -> str:
        """``B1: shows  6 of 6 at 1%``."""
        return f"{self.row}: {'shows' if self.shows else 'gone'}  {self.line}"


def level(model: ServeModel, i: int, weather: WeatherClass) -> int:
    """District ``i``'s class level of ``weather``, in whole percent."""
    position = serve.SITUATION_POSITION[Situation.of(weather, False).key]
    return percent(float(model.p[i, position]))


def _span(values: Sequence[int]) -> str:
    return f"{min(values)}-{max(values)}%" if values else "none"


def verdicts(
    story: StoryRun, found: Mapping[tuple[int, str], CellValue], config: PredictConfig
) -> list[Verdict]:
    """The ten verdicts (What 8), in order."""
    world, model = story.world, story.model

    def at(key: str, moment: str) -> list[CellValue]:
        return [found[(i, moment)] for i in world.of(key)]

    def sure(values: Sequence[CellValue]) -> list[Cell]:
        return [c for c in values if isinstance(c, Cell)]

    def all_calm(values: Sequence[CellValue]) -> tuple[bool, int]:
        count = sum(1 for c in values if calm(c))
        return count == len(values), count

    v: list[Verdict] = []
    shows, n = all_calm(at("watch", "d1_1600"))
    v.append(Verdict("B1", shows, f"{n} of {len(world.of('watch'))} at 1% at 4 PM Mon"))
    eight, late = at("watch", "d1_2000"), at("watch", "d1_2130")
    picks = world.of("watch")
    shows = all(isinstance(c, Cell) and not c.forecast and c.p == c.points for c in eight) and all(
        isinstance(c, Cell) and c.forecast for c in late
    )
    few = [
        c.p
        for i, c in zip(picks, eight, strict=True)
        if isinstance(c, Cell) and world.inches[i] < WATCH_SPLIT
    ]
    many = [
        c.p
        for i, c in zip(picks, eight, strict=True)
        if isinstance(c, Cell) and world.inches[i] >= WATCH_SPLIT
    ]
    moves = [
        b.p - a.p
        for a, b in zip(eight, late, strict=True)
        if isinstance(a, Cell) and isinstance(b, Cell)
    ]
    v.append(
        Verdict(
            "C3",
            shows,
            f"8 PM Mon: 3 in {_span(few)}, 20 in {_span(many)}; to 9:30 PM up to "
            f"{max(moves, default=0):+d} and down to {min(moves, default=0):+d} points",
        )
    )
    cancel = at("cancel", "d0_0500")
    shows, n = all_calm(cancel)
    downs = [f"{c.p}% down from {c.prev}%" for c in sure(cancel) if c.said == "down"]
    v.append(Verdict("B3", shows, f"{n} of {len(cancel)} at 1% at 5 AM Tue; " + ", ".join(downs)))
    shows, n = all_calm(at("late", "d0_0630"))
    v.append(Verdict("B4", shows, f"{n} of {len(world.of('late'))} at 1% at 6:30 AM Tue"))
    two = at("daytwo", "d0_1600")
    others = sum(
        1
        for (i, _m), c in found.items()
        if world.stories[i].key != "daytwo" and isinstance(c, Cell) and c.after
    )
    calm_n = sum(1 for c in two if calm(c))
    after_n = sum(1 for c in sure(two) if c.after)
    borrowed_n = sum(1 for c in sure(two) if c.borrowed)
    shows = calm_n == after_n == borrowed_n == len(two) and others == 0
    v.append(
        Verdict(
            "B2",
            shows,
            f"{calm_n} of {len(two)} at 1% for Wed at 4 PM Tue; after {after_n}, borrowed "
            f"{borrowed_n}; other districts after: {others}",
        )
    )
    cold = at("coldadv", "d1_2130") + at("coldadv", "d0_0500")
    shows, n = all_calm(cold)
    v.append(Verdict("B5", shows, f"{n} of {len(cold)} at 1% at 9:30 PM Mon and 5 AM Tue"))
    shows, n = all_calm(at("half", "d1_2130"))
    under = warned_schools(story, "half", MOMENTS[2])
    schools = next(s.schools for s in STORIES if s.key == "half")
    part = all(u >= 1 and u / schools < config.weather.covered_share for u in under)
    v.append(
        Verdict(
            "B6",
            shows and part,
            f"{n} of {len(world.of('half'))} at 1% at 9:30 PM Mon; schools under the warning "
            + ", ".join(str(u) for u in under)
            + f" of {schools} (a class covers {config.weather.covered_share:.0%})",
        )
    )
    v.append(_blizzard(world, model, found))
    v.append(_extreme_cold(world, model, found, config))
    over = at("overnight", "d0_0500")
    shows = all(
        isinstance(c, Cell) and c.forecast and c.points is not None and c.p < c.points for c in over
    )
    v.append(
        Verdict(
            "C4",
            shows,
            "at 5 AM Tue, level to chance: "
            + ", ".join(f"{c.points}% to {c.p}%" for c in sure(over)),
        )
    )
    return v


def warned_schools(story: StoryRun, key: str, moment: Moment) -> list[int]:
    """Each district of story ``key``: how many of its schools the zone index the pass is given
    (:func:`_ugcs` of the world's zones) puts in a zone that a product in the feed at ``moment``
    (on the district's clock) warns or advises for (an ending product warns for none)."""
    world = story.world
    index = _ugcs(world.areas)(world.directory)
    found = []
    for i in world.of(key):
        live = active_at(world.products, moment_at(world, i, moment))
        reached = set(index.reached({p.zone for p in live if not p.ending}).tolist())
        found.append(sum(1 for j, d in enumerate(world.district_of) if d == i and j in reached))
    return found


def _blizzard(
    world: World, model: ServeModel, found: Mapping[tuple[int, str], CellValue]
) -> Verdict:
    picks = world.of("blizzard")
    values = [found[(i, "d1_2130")] for i in picks]
    plain = [level(model, i, WeatherClass.SNOW_WARNING) for i in picks]
    shows = all(
        isinstance(c, Cell) and not c.forecast and c.p == w
        for c, w in zip(values, plain, strict=True)
    )
    seen = [c.p for c in values if isinstance(c, Cell)]
    inches = sorted({world.inches[i] for i in picks})
    return Verdict(
        "C1",
        shows,
        f"{_span(seen)} at 9:30 PM Mon, the plain warning levels {_span(plain)}, "
        f"{', '.join(f'{x:g}' for x in inches)} in",
    )


def cold_start(config: PredictConfig) -> float:
    """The cold class's registered starting level (``live_score.prior.cold.target``; NaN when
    the config names none)."""
    prior = config.live_score.get("prior")
    cold = prior.get("cold") if isinstance(prior, dict) else None
    target = cold.get("target") if isinstance(cold, dict) else None
    return float(target) if isinstance(target, int | float) else math.nan


def _extreme_cold(
    world: World,
    model: ServeModel,
    found: Mapping[tuple[int, str], CellValue],
    config: PredictConfig,
) -> Verdict:
    picks = world.of("extcold")
    values = [found[(i, "d1_2130")] for i in picks]
    levels = [level(model, i, WeatherClass.COLD) for i in picks]
    start = cold_start(config)
    shows = all(
        isinstance(c, Cell) and c.base == "class" and not c.forecast and c.p == w
        for c, w in zip(values, levels, strict=True)
    ) and math.isclose(start, 0.10)
    seen = [c.p for c in values if isinstance(c, Cell)]
    return Verdict(
        "C2",
        shows,
        f"{_span(seen)} at 9:30 PM Mon; cold levels {', '.join(f'{x}%' for x in levels)}; "
        f"the cold class starts at {start:.2f}",
    )


# --- The storm-size night ---------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Lattice:
    """The storm-size night's directory (What 9): the districts in SHA-256 order on a 6-mile
    lattice, their schools around each point, the private schools at the points of others."""

    directory: DeployedDirectory
    side: int
    origin: tuple[float, float]
    """Longitude and latitude of district 0."""
    step: tuple[float, float]
    """Degrees between columns and between rows."""
    private: int

    @property
    def districts(self) -> int:
        """How many districts."""
        return len(self.directory.district_ids)


def lattice(committed: ModelArtifact, scale: float) -> Lattice:
    """The lattice of ``ceil(scale n)`` districts, ``ceil(scale m)`` private schools and
    ``ceil(scale 96,101)`` public schools."""
    leaids = sorted(committed.districts, key=_sha)
    leaids = leaids[: math.ceil(scale * len(leaids))]
    n = len(leaids)
    side = math.ceil(math.sqrt(n))
    dlat = SPACING_MI / 69.0
    lat0, lon0 = 36.0, -100.0
    dlon = SPACING_MI / (69.0 * math.cos(math.radians(lat0 + side * dlat / 2)))
    public = math.ceil(scale * PUBLIC_SCHOOLS)
    lon: list[float] = []
    lat: list[float] = []
    district: list[int] = []
    kind: list[int] = []
    centers: list[tuple[float, float]] = []
    for i in range(n):
        row, column = divmod(i, side)
        x, y = lon0 + column * dlon, lat0 + row * dlat
        centers.append((x, y))
        for j in range(public // n + (1 if i < public % n else 0)):
            lon.append(x + 0.002 * (j % 5) - 0.004)
            lat.append(y + 0.002 * (j // 5) - 0.004)
            district.append(i)
            kind.append(0)
    private = sorted(committed.private, key=_sha)
    private = private[: math.ceil(scale * len(private))]
    for m in range(len(private)):
        x, y = centers[(7919 * m) % n]
        lon.append(x + 0.004)
        lat.append(y + 0.004)
        district.append(NO_DISTRICT)
        kind.append(PRIVATE)
    count = len(lon)
    points = encode([round(x * 1e6) for x in lon], [round(y * 1e6) for y in lat], district, kind, n)
    stamp = DirectoryStamp(generated_on=date(2026, 10, 14), schools=count, districts=n)
    ids = tuple(f"{i:012d}" for i in range(1, count - len(private) + 1)) + tuple(private)
    directory = DeployedDirectory(stamp, tuple(leaids), decode(points), school_ids=ids)
    return Lattice(directory, side, (lon0, lat0), (dlon, dlat), len(private))


def storm_zones(grid: Lattice, share: float) -> tuple[int, dict[str, shapely.Geometry]]:
    """How many districts the storm covers, and the zones: :data:`STORM_ZONE` over the first
    ``ceil(share n)`` districts (whole rows from the south, then the first of the next row),
    :data:`QUIET_ZONE` the lattice's box, 1 degree beyond its outer points, less it."""
    (lon0, lat0), (dlon, dlat), side = grid.origin, grid.step, grid.side
    covered = math.ceil(share * grid.districts)
    rows, extra = divmod(covered, side)
    box = shapely.box(lon0 - 1, lat0 - 1, lon0 + side * dlon + 1, lat0 + side * dlat + 1)
    parts = []
    if rows:
        parts.append(
            shapely.box(lon0 - 1, lat0 - 1, lon0 + side * dlon + 1, lat0 + (rows - 0.5) * dlat)
        )
    if extra:
        parts.append(
            shapely.box(
                lon0 - 1,
                lat0 + (rows - 0.5) * dlat,
                lon0 + (extra - 0.5) * dlon,
                lat0 + (rows + 0.5) * dlat,
            )
        )
    if not parts:
        return 0, {QUIET_ZONE: box}
    storm = shapely.union_all(parts)
    return covered, {STORM_ZONE: storm, QUIET_ZONE: shapely.difference(box, storm)}


def size_products() -> tuple[Product, ...]:
    """The night's feed: a WW.Y advisory over :data:`STORM_ZONE` sent D-1 12:00Z, upgraded at
    D 01:00Z by a WS.W NEW carrying its UPG."""
    on = datetime(2027, 1, 10, 12, tzinfo=UTC)
    off = datetime(2027, 1, 14, 18, tzinfo=UTC)
    return (
        Product(
            datetime(2027, 1, 11, 12, tzinfo=UTC),
            (vtec("NEW", "WW.Y", 1, on, off),),
            "size",
            STORM_ZONE,
            "Winter Weather Advisory",
            on,
            off,
        ),
        Product(
            UPGRADE,
            (vtec("NEW", "WS.W", 2, on, off), vtec("UPG", "WW.Y", 1, on, off)),
            "size",
            STORM_ZONE,
            "Winter Storm Warning",
            on,
            off,
        ),
    )


def size_script(storm: shapely.Geometry | None, mix: str) -> Script:
    """The night's run values: at deciding school ``k`` inside the storm ``2 + 1.1 (k mod 13)``
    inches, half in each of the periods ending 12:00Z and 18:00Z; worst: 0.05 in of ice the same
    way and feels 12 F; typical: no ice, 25 F. Outside: none, 25 F. Every day the same."""
    worst = mix == "worst"

    def script(schools: forecast_history.Schools, _index: Mapping[str, int]) -> ReadRun:
        if storm is None:
            inside = np.zeros(schools.lon.shape, dtype=bool)
        else:
            inside = np.asarray(shapely.contains_xy(storm, schools.lon, schools.lat), dtype=bool)
        k = np.arange(schools.lon.shape[0])
        total = np.where(inside, 2.0 + 1.1 * (k % 13), 0.0)
        ice = np.where(inside & worst, 0.05, 0.0)
        feels = np.where(inside & worst, 12.0, FEELS)
        zones = sorted(set(schools.zone_of_district))

        def reader(run: ndfd.Run, day: date) -> forecast_history.RunValues:
            ends = ndfd.window_ends(day)
            return forecast_history.RunValues(
                run,
                _halves(total, ends),
                _halves(ice, ends),
                {ndfd.bus_time(day, zone): feels for zone in zones},
            )

        return reader

    return script


def size_blend(
    storm: shapely.Geometry | None,
) -> Callable[..., tuple[datetime, dict[datetime, Floats]]]:
    """The night's blend: :data:`STORM_HOURLY` an hour inside the storm, 0 outside."""

    def blend(
        lat: Floats, lon: Floats, hours: set[datetime], now: datetime, _max_age: timedelta
    ) -> tuple[datetime, dict[datetime, Floats]]:
        cycle = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        if storm is None:
            inside = np.zeros(lat.shape, dtype=bool)
        else:
            inside = np.asarray(shapely.contains_xy(storm, lon, lat), dtype=bool)
        return cycle, {hour: np.where(inside, STORM_HOURLY, 0.0) for hour in hours}

    return blend


@dataclass(frozen=True)
class SizePass:
    """One pass of a storm-size world and what its file holds."""

    share: float
    mix: str | None
    at: str
    seconds: float
    cpu: float
    dark: bool
    raw: int
    gzip: int
    lines: int
    """District-days with a forecast line."""
    previous: int
    """District-days with a previous chance."""
    nights: int
    """Districts with a night."""
    storm: int
    """Storm districts with a night."""
    covered: int
    """Storm districts."""
    schools: int
    """Private schools."""
    outlooks: int
    private_previous: int
    records: int
    """District-days with record days."""
    own: int
    """District-days on an own base (``alert``, ``similar_days`` or ``day_after``)."""
    ladder: tuple[str, ...]
    """The ladder's warning lines, verbatim."""

    @property
    def evening(self) -> bool:
        """One of the five evening passes."""
        return self.at in {f"{t:%H:%M}Z" for t in PASSES[:EVENING]}

    @property
    def upgraded(self) -> bool:
        """At or after the upgrade (01:07Z on)."""
        return self.at >= f"{PASSES[1]:%H:%M}Z"

    def missing(self) -> list[str]:
        """What a whole file holds that this one lacks (empty: whole)."""
        found: list[str] = []
        if self.dark:
            return ["dark"]
        if self.lines == 0:
            found.append("no forecast line")
        if self.schools == 0:
            found.append("no private school")
        if self.upgraded and self.private_previous == 0:
            found.append("no private previous chance")
        if self.storm == 0:
            found.append("no night on a storm district")
        if self.evening and self.storm < self.covered:
            found.append(f"nights on {self.storm} of {self.covered} storm districts")
        if self.evening and self.upgraded and self.previous == 0:
            found.append("no district previous chance")
        if self.own and not self.records:
            found.append(f"records: {self.at} {self.own} own bases, no record day")
        return found

    @property
    def whole(self) -> bool | None:
        """Whether the file is the one ``cli.fitted`` would make with no budget (``None``: the
        calibration world, with no storm)."""
        return None if self.covered == 0 else not self.missing()

    def as_json(self) -> dict[str, object]:
        """The pass's JSON row."""
        return {
            "share": self.share,
            "mix": self.mix,
            "at": self.at,
            "seconds": round(self.seconds, 3),
            "cpu": round(self.cpu, 3),
            "dark": self.dark,
            "raw": self.raw,
            "gzip": self.gzip,
            "lines": self.lines,
            "previous": self.previous,
            "nights": self.nights,
            "storm": self.storm,
            "covered": self.covered,
            "schools": self.schools,
            "outlooks": self.outlooks,
            "private_previous": self.private_previous,
            "records": self.records,
            "own": self.own,
            "whole": self.whole,
            "ladder": list(self.ladder),
        }


@dataclass(frozen=True)
class FrozenSize:
    """A world's frozen day D and what storing it costs."""

    share: float
    mix: str | None
    raw: int
    lines: int
    xz: int
    xz_seconds: float
    stored: int
    d1_rows: int
    taken: int
    """Freezes taken (zone and freeze)."""
    missed: int
    zones: int
    late_s: int
    """The latest freeze, in seconds."""

    def as_json(self) -> dict[str, object]:
        """The world's JSON row."""
        return {
            "share": self.share,
            "mix": self.mix,
            "raw": self.raw,
            "lines": self.lines,
            "xz": self.xz,
            "xz_seconds": round(self.xz_seconds, 3),
            "stored": self.stored,
            "d1_rows": self.d1_rows,
            "taken": self.taken,
            "missed": self.missed,
            "zones": self.zones,
            "late_s": self.late_s,
        }


@dataclass
class SizeNight:
    """Every pass and every world's frozen day of a size night, and the peak RSS."""

    passes: list[SizePass] = field(default_factory=list)
    frozen: list[FrozenSize] = field(default_factory=list)
    rss_mb: float = 0.0
    worlds: list[str] = field(default_factory=list)
    """Each world's header line."""


def worlds_of(*, full: bool) -> list[tuple[float, str | None]]:
    """The worlds a night runs: the gate's, or with ``full`` the calibration world and every
    share in both mixes."""
    if not full:
        return [GATE]
    return [(0.0, None)] + [(share, mix) for share in SHARES for mix in MIXES]


def size_night(  # noqa: PLR0913 - the config, the model, the folders and the scale
    config: PredictConfig,
    committed: ModelArtifact,
    labels: Path,
    folder: Path,
    *,
    scale: float = 1.0,
    full: bool = False,
    worlds: Sequence[tuple[float, str | None]] | None = None,
    say: Callable[[str], None] | None = None,
) -> SizeNight:
    """Run the storm-size night (What 9): each world fresh (its own ``Pass``, state, host and
    frozen folder under ``folder``; the anchor fitted once on ``labels``), its passes in time
    order, each measured, then its frozen day. ``worlds``: the (share, mix) worlds to run, in
    place of :func:`worlds_of` (the tests run a few). ``say`` gets each line as it is made."""
    grid = lattice(committed, scale)
    night = SizeNight()
    # The anchor is fitted once on the labels and is immutable, so each world's pass starts from
    # the very levels a fresh fit would give it.
    anchor = anchor_labels.serving_anchor(config, committed, folder=labels)
    for share, mix in worlds_of(full=full) if worlds is None else worlds:
        covered, areas = storm_zones(grid, share)
        line = (
            f"size {share:.0%} {mix or 'quiet'}: {covered:,} of {grid.districts:,} districts in "
            f"the storm; {grid.directory.stamp.schools:,} schools ({grid.private:,} private), "
            f"lattice side {grid.side} at {SPACING_MI:g} mi"
        )
        night.worlds.append(line)
        if say is not None:
            say(line)
        frozen = folder / f"frozen-{share:.2f}-{mix or 'quiet'}"
        try:
            for result in _world(
                config, committed, anchor, frozen, grid, share, mix, covered, areas
            ):
                if isinstance(result, SizePass):
                    night.passes.append(result)
                    lines = pass_lines(result, config)
                else:
                    night.frozen.append(result)
                    lines = [frozen_line(result)]
                if say is not None:
                    for each in lines:
                        say(each)
        finally:
            _remove(frozen)
    night.rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return night


def _remove(folder: Path) -> None:
    if not folder.exists():
        return
    for item in sorted(folder.rglob("*"), reverse=True):
        if item.is_dir():
            item.rmdir()
        else:
            item.unlink()
    folder.rmdir()


def _world(  # noqa: PLR0913, PLR0917 - one world of the night
    config: PredictConfig,
    committed: ModelArtifact,
    anchor: "Anchor | None",
    frozen: Path,
    grid: Lattice,
    share: float,
    mix: str | None,
    covered: int,
    areas: Mapping[str, shapely.Geometry],
) -> Iterator[SizePass | FrozenSize]:
    from snowlight.predict import cli  # noqa: PLC0415 - cli imports this module at its top

    storm = areas.get(STORM_ZONE)
    clock = FakeClock(datetime.combine(DAY, PASSES[0], UTC))
    host = DrillHost(clock.now)
    products = size_products() if covered else ()
    alerts, history = feeds(products, clock.now)
    run = cli.Pass(
        config=config,
        mode=Mode.ON,
        host=host,
        directory=lambda: grid.directory,
        alerts=alerts,
        ugcs=_ugcs(areas),
        zone_fallback=lambda _lon, _lat: None,
        model=lambda: committed,
        state=State(),
        anchor=anchor,
        now=clock.now,
        history=history,
        forecast=adjust_reader(config, size_script(storm, mix or "typical")),
        frozen=frozen,
        night=cli.night_reader(
            size_blend(storm), timedelta(minutes=config.serve.chart_nbm_max_age_minutes)
        ),
    )
    for at in PASSES if covered else (PASSES[1],):
        clock.at = datetime.combine(DAY, at, UTC)
        out, err = io.StringIO(), io.StringIO()
        cpu, started = time.process_time(), time.monotonic()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.one_pass(run)
        seconds, cpu = time.monotonic() - started, time.process_time() - cpu
        ladder = tuple(
            line[line.find("predict: warning:") :]
            for line in err.getvalue().splitlines()
            if "published it with no" in line
        )
        yield measure(host, clock.at, share, mix, covered, seconds, cpu, code, ladder)
    yield frozen_size(frozen, share, mix)


def measure(  # noqa: PLR0913, PLR0917 - one pass's measures
    host: DrillHost,
    at: datetime,
    share: float,
    mix: str | None,
    covered: int,
    seconds: float,
    cpu: float,
    code: int,
    ladder: tuple[str, ...],
) -> SizePass:
    """What the file the host holds after a pass at ``at`` carries (read as plain JSON: a
    storm night's file is up to 16 MB, and the pass itself has checked it)."""
    data = host.held_at(LATEST, at)
    written = any(when == at and key == LATEST for when, key, _data in host.log)
    document = {} if data is None else _dict(json.loads(data))
    days = [
        (int(str(entry.get("district"))), day)
        for entry in map(_dict, _list(document.get("districts")))
        for day in map(_dict, _list(entry.get("days")))
        if day.get("state") == "forecast"
    ]
    nights = {i for i, day in days if day.get("night") is not None}
    outlooks = [_dict(o) for o in _list(document.get("outlooks"))]
    return SizePass(
        share=share,
        mix=mix,
        at=f"{at:%H:%M}Z",
        seconds=seconds,
        cpu=cpu,
        dark=code != 0 or not written,
        raw=0 if data is None else len(data),
        gzip=0 if data is None else len(gzip.compress(data, mtime=0)),
        lines=sum(1 for _i, d in days if _kinds(d) & serve.ADJUST_KINDS),
        previous=sum(1 for _i, d in days if d.get("previous") is not None),
        nights=len(nights),
        storm=sum(1 for i in nights if i < covered),
        covered=covered,
        schools=len(_list(document.get("schools"))),
        outlooks=len(outlooks),
        private_previous=sum(
            1 for o in outlooks if o.get("state") == "forecast" and o.get("previous") is not None
        ),
        records=sum(1 for _i, d in days if d.get("record") is not None),
        own=sum(1 for _i, d in days if _base(d) in {"alert", "similar_days", "day_after"}),
        ladder=ladder,
    )


def _kinds(day: Mapping[str, object]) -> set[str]:
    """The kinds of a forecast day's reasons (its ``why``)."""
    return {str(_dict(r).get("kind")) for r in _list(_dict(day.get("why")).get("reasons"))}


def _base(day: Mapping[str, object]) -> str:
    """The kind of a forecast day's base."""
    return str(_dict(_dict(day.get("why")).get("base")).get("kind"))


def frozen_size(folder: Path, share: float, mix: str | None) -> FrozenSize:
    """The world's frozen day D: raw bytes, lines, xz bytes at the store's preset and the
    seconds it took, the base64 bytes and the D1 rows a database; the freezes taken."""
    raw = (folder / f"{DAY.isoformat()}.jsonl").read_bytes()
    started = time.monotonic()
    packed = evidence.compress(raw, evidence.PRESETS[evidence.FROZEN])
    took = time.monotonic() - started
    _item, parts = evidence.item_of(
        evidence.Offer(evidence.FROZEN, DAY.isoformat(), raw), "2027-01-13T00:00:00Z"
    )
    taken: set[tuple[str, str]] = set()
    missed: set[tuple[str, str]] = set()
    zones: set[str] = set()
    late = 0
    for line in raw.splitlines():
        if not line.startswith(b'{"'):
            continue
        head = json.loads(line)
        if head.get("k") == "freeze":
            taken.add((str(head["zone"]), str(head["freeze"])))
            zones.add(str(head["zone"]))
            late = max(late, int(head.get("late_by_s", 0)))
        elif head.get("k") == "missed":
            missed.add((str(head["zone"]), str(head["freeze"])))
    return FrozenSize(
        share=share,
        mix=mix,
        raw=len(raw),
        lines=raw.count(b"\n"),
        xz=len(packed),
        xz_seconds=took,
        stored=sum(len(p) for p in parts),
        d1_rows=1 + len(parts),
        taken=len(taken),
        missed=len(missed),
        zones=len(zones),
        late_s=late,
    )


def _margin(size: int, limit: int, name: str) -> str:
    left = limit - size
    if left < 0:
        return f"{-left:,} over the {name}"
    edge = " (at the edge)" if left < EDGE * limit else ""
    return f"{left:,} under the {name}{edge}"


def pass_lines(item: SizePass, config: PredictConfig) -> list[str]:
    """One pass's lines: its measures, then the ladder's own lines verbatim."""
    settings = config.serve
    whole = {None: "no storm", True: "whole", False: "not whole"}[item.whole]
    missing = item.missing()
    head = (
        f"  {item.at} {'dark' if item.dark else 'published'} in {item.seconds:.1f} s (cpu "
        f"{item.cpu:.1f}): raw {item.raw:,} "
        f"({_margin(item.raw, settings.budget_raw_bytes, 'budget')}, "
        f"{_margin(item.raw, settings.night_max_raw_bytes, 'night limit')}), gzip {item.gzip:,} "
        f"({_margin(item.gzip, settings.budget_gzip_bytes, 'budget')})"
    )
    body = (
        f"    lines {item.lines:,}, previous {item.previous:,}, nights {item.nights:,} (storm "
        f"{item.storm:,} of {item.covered:,}), private schools {item.schools:,}, outlooks "
        f"{item.outlooks:,} (previous {item.private_previous:,}), records {item.records:,}, own "
        f"{item.own:,}: {whole}" + (f" ({'; '.join(missing)})" if missing and item.covered else "")
    )
    return [head, body, *(f"    ladder: {line}" for line in item.ladder)]


def frozen_line(item: FrozenSize) -> str:
    """A world's frozen day line."""
    return (
        f"  frozen day {DAY.isoformat()}: {item.raw:,} raw, {item.lines:,} lines, xz9 "
        f"{item.xz:,} in {item.xz_seconds:.1f} s, stored {item.stored:,} base64, {item.d1_rows} D1 "
        f"rows a database ({_margin(item.stored, 1_000_000, '1 MB a day')}); freezes "
        f"{item.taken} taken in {item.zones} zones, {item.missed} missed, up to {item.late_s} s "
        "late"
    )


def size_code(results: Sequence[SizePass], say: Callable[[str], None] | None = None) -> int:
    """3 when a pass of the gate's world (37%, worst) went dark or is not whole, each named in
    one line; else 0. The other worlds are reported, never failed."""
    out = say or _out
    code = 0
    gate = sum(1 for item in results if (item.share, item.mix) == GATE)
    if gate != len(PASSES):
        out(f"size gate: {gate} of {len(PASSES)} passes of the 37% worst world")
        code = 3
    for item in results:
        if (item.share, item.mix) != GATE:
            continue
        for missing in item.missing():
            code = 3
            if missing.startswith("records: "):
                out(missing)
            else:
                out(f"size gate: {item.at} {missing}")
    return code


# --- Output -----------------------------------------------------------------------------------


LEGEND: Final = (
    "legend: NN% the chance; ^MM up from, vMM down from, =MM same as (the panel's move line); "
    "C class, P pooled, A alert, D day after, S similar days (the base); b a borrowed base; "
    "f a forecast line; a the day after a weather closing; -- no number (no file or over 90 "
    "minutes old); n/a the day not in the file; off the panel heads another day"
)


@dataclass
class Result:
    """What the drill found: the story's table and verdicts, its run, and the size night."""

    story: StoryRun
    cells: dict[tuple[int, str], CellValue]
    verdicts: list[Verdict]
    size: SizeNight | None = None


def render(result: Result) -> list[str]:
    """The table, the legend, the verdicts, the run line, the anchor line and the frozen line."""
    world, story = result.story.world, result.story
    lines = [
        f"{'story':10} {'rows':6} {'leaid':8} {'in':>5} "
        + " ".join(f"{m.name:>12}" for m in MOMENTS)
    ]
    for i, leaid in enumerate(world.leaids):
        row = " ".join(f"{_text(result.cells[(i, m.name)]):>12}" for m in MOMENTS)
        lines.append(
            f"{world.stories[i].key:10} {world.stories[i].rows:6} {leaid:8} "
            f"{world.inches[i]:5.1f} {row}"
        )
    lines.append(LEGEND)
    lines.extend(v.text() for v in result.verdicts)
    largest = max((len(d) for _w, d in story.host.uploads()), default=0)
    lines.append(
        f"drill: {story.passes} passes ({story.dark} dark), {len(story.host.uploads())} uploads, "
        f"the largest file {largest:,} bytes, {story.seconds:.1f} s"
    )
    lines.append(
        "anchor: none" if story.anchor is None else anchor_labels.anchor_line(story.anchor)
    )
    lines.append(
        f"drill frozen day {DAY.isoformat()}: {story.frozen_raw:,} raw, {story.frozen_xz:,} xz "
        "at preset 9"
    )
    return lines


def as_json(result: Result) -> str:
    """The result as JSON (schema 1), key-sorted."""
    story, world = result.story, result.story.world
    document: dict[str, object] = {
        "schema": SCHEMA,
        "day": DAY.isoformat(),
        "moments": [m.name for m in MOMENTS],
        "districts": [
            {
                "leaid": leaid,
                "story": world.stories[i].key,
                "rows": world.stories[i].rows,
                "state": world.stories[i].state,
                "zone": world.zone_of[world.stories[i].key],
                "snow": world.inches[i],
            }
            for i, leaid in enumerate(world.leaids)
        ],
        "cells": {
            leaid: {
                m.name: (c if isinstance(c := result.cells[(i, m.name)], str) else c.as_json())
                for m in MOMENTS
            }
            for i, leaid in enumerate(world.leaids)
        },
        "verdicts": [{"row": v.row, "shows": v.shows, "line": v.line} for v in result.verdicts],
        "run": {
            "passes": story.passes,
            "dark": story.dark,
            "uploads": len(story.host.uploads()),
            "largest": max((len(d) for _w, d in story.host.uploads()), default=0),
            "seconds": round(story.seconds, 3),
        },
        "frozen": {"raw": story.frozen_raw, "xz": story.frozen_xz},
    }
    if result.size is not None:
        document["size"] = [item.as_json() for item in result.size.passes]
        document["frozen_size"] = [item.as_json() for item in result.size.frozen]
        document["rss_mb"] = round(result.size.rss_mb, 1)
    return json.dumps(document, sort_keys=True, indent=1) + "\n"


def _cell_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return "missing"
    found = f"{value.get('p')}%"
    said = value.get("said")
    if said in {"up", "down", "same"}:
        found += {"up": " ^", "down": " v", "same": " ="}[str(said)] + str(value.get("prev"))
    found += " " + BASE_LETTERS.get(str(value.get("base")), "?")
    found += "b" if value.get("borrowed") else ""
    found += "f" if value.get("forecast") else ""
    return found + ("a" if value.get("after") else "")


def differences(before: Mapping[str, object], after: Mapping[str, object]) -> list[str]:
    """Every cell and verdict that differs between two results (``LEAID story moment: before ->
    after``), then how many."""
    stories = {
        str(d["leaid"]): str(d["story"])
        for d in [*_list(before.get("districts")), *_list(after.get("districts"))]
        if isinstance(d, dict)
    }
    old, new = _dict(before.get("cells")), _dict(after.get("cells"))
    lines: list[str] = []
    for leaid in sorted(set(old) | set(new)):
        was, now = _dict(old.get(leaid)), _dict(new.get(leaid))
        for moment in [m.name for m in MOMENTS] + sorted(
            (set(was) | set(now)) - {m.name for m in MOMENTS}
        ):
            if was.get(moment) != now.get(moment):
                lines.append(
                    f"{leaid} {stories.get(leaid, '?')} {moment}: "
                    f"{_cell_text(was.get(moment))} -> {_cell_text(now.get(moment))}"
                )
    cells_n = len(lines)
    rows_old = {str(v.get("row")): v for v in map(_dict, _list(before.get("verdicts")))}
    rows_new = {str(v.get("row")): v for v in map(_dict, _list(after.get("verdicts")))}
    verdicts_n = 0
    for row in [*rows_old, *(r for r in rows_new if r not in rows_old)]:
        a, b = rows_old.get(row, {}), rows_new.get(row, {})
        if a != b:
            verdicts_n += 1
            lines.append(f"{row}: {_said(a)} -> {_said(b)}")
    lines.append(f"{cells_n} cells differ, {verdicts_n} verdicts differ")
    return lines


def _said(verdict: Mapping[str, object]) -> str:
    if not verdict:
        return "missing"
    return f"{'shows' if verdict.get('shows') else 'gone'} ({verdict.get('line')})"


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _dict(value: object) -> dict[str, object]:
    return {str(k): v for k, v in value.items()} if isinstance(value, dict) else {}


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


# --- The command ------------------------------------------------------------------------------


def _scale(text: str) -> float:
    value = float(text)
    if not 0 < value <= 1:
        raise argparse.ArgumentTypeError(f"--scale {text}: give 0 < F <= 1")
    return value


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``predict drill``."""
    parser = actions.add_parser(
        "drill",
        help="one scripted storm through the real pass, hour by hour (serves nothing)",
        description=(
            "The storm drill: one scripted storm through the real loop and pass on a faked "
            "clock, publishing to a host in memory; --size adds the storm-size night."
        ),
    )
    parser.add_argument("--size", action="store_true", help="add the 37%% worst-case world")
    parser.add_argument(
        "--full", action="store_true", help="with --size: the calibration and all six worlds"
    )
    parser.add_argument("--scale", type=_scale, default=1.0, help="0 < F <= 1 (tests)")
    parser.add_argument("--labels", type=Path, default=None, help="a record folder (read only)")
    parser.add_argument("--json", type=Path, default=None, help="write the result here")
    parser.add_argument("--against", type=Path, default=None, help="a result to compare with")
    parser.add_argument("--verbose", action="store_true", help="print the passes' own lines")
    parser.set_defaults(handler=run_drill)


def run_drill(args: argparse.Namespace) -> int:
    """Run ``predict drill``: 0 when the story ran, 3 when the gate's world failed (with
    ``--size``), 1 on an error."""
    if args.full and not args.size:
        _out("predict drill: --full needs --size")
        return 1
    try:
        return _run(args)
    except Exception as error:  # the command's own exit code for any failure
        _out(f"predict drill: error: {type(error).__name__}: {error}")
        return 1


def run_story(
    config: PredictConfig,
    committed: ModelArtifact,
    exposure: Exposure,
    labels: Path,
    temp: Path,
) -> Result:
    """The story's run, cells and verdicts; its frozen folder (under ``temp``) is removed once
    measured."""
    frozen = temp / "frozen"
    try:
        story = story_drill(config, committed, exposure, labels, frozen)
    finally:
        _remove(frozen)
    found = cells(story, config)
    return Result(story, found, verdicts(story, found, config))


def _run(args: argparse.Namespace) -> int:
    from snowlight.predict import artifact, exposure  # noqa: PLC0415 - read at run time only

    config = PredictConfig.load(args.config)
    committed = artifact.load()
    against = None if args.against is None else json.loads(args.against.read_text())
    with tempfile.TemporaryDirectory(prefix="snowlight-drill-") as name:
        temp = Path(name)
        labels = args.labels
        if labels is None:
            labels = temp / "labels"
            labels.mkdir()
        result = run_story(config, committed, exposure.load(), labels, temp)
        if args.verbose:
            for line in [*result.story.out, *result.story.err]:
                _out(line)
        for line in render(result):
            _out(line)
        code = 0
        if args.size:
            result.size = size_night(
                config, committed, labels, temp, scale=args.scale, full=args.full, say=_out
            )
            _out(f"drill size: peak RSS {result.size.rss_mb:,.0f} MB")
            code = size_code(result.size.passes)
    text = as_json(result)
    if args.json is not None:
        args.json.write_text(text)
    if against is not None:
        for line in differences(against, json.loads(text)):
            _out(line)
    return code
