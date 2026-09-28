"""``predictions/latest.json``: the chance of a weather closure or delay, per district and day.

Each district has one entry per day in ``days``, in the same order. An entry is one
of three states, told apart by ``state``:

* ``forecast``: weather that has closed or delayed schools is forecast; the entry
  gives ``p_no_school`` (closed or remote), ``p_delay`` (a delayed start) and the
  weather behind them. The two outcomes exclude each other, so their sum is at
  most 1.
* ``no_threat``: no such weather is forecast.
* ``not_enough_data``: the district's history is too short to give a chance.

Districts without an entry have no prediction at all and read as not enough data.

What the school panel's chance section shows, and what a forecast carries for it
(every part may be null where the engine cannot give it; the site then leaves that
part out, and never fills it in):

* ``previous``: the chance the run before gave the same district and day, and when
  that run was made ("Up from 41% at 5 PM").
* ``announces_at`` and ``buses_at``: when the district usually posts its decision
  for this day, and when its first buses usually run that day.
* ``hours``: one weather measure an hour up to the bus hour, for the chart: the
  running total of snow (with its low-to-high range at the bus hour), or how cold
  it will feel.
* ``why``: how the chance adds up. A base chance with its reason, then reasons of
  typed kinds, each with its whole-number points. The base plus every reason's
  points is exactly the chance of no school in whole percent. The file carries only
  kinds and numbers; the site writes every sentence (``web/src/copy.ts``).
* ``record``: the district's own record in days like this one (the date, the snow
  and what the district did), shown under the reason it proves.
* ``events``: weather that already happened, with its time ("Snow stopped, 8
  inches in all").

A district's ``neighbors`` are the districts next door, whose posted statuses in
``live/closings.json`` the site lists as the evening's early signals: every other
district with a school within :data:`NEIGHBOR_MILES` miles of one of this district's
schools, nearest first, at most :data:`MAX_NEIGHBORS`.
"""

from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from snowlight.schemas.base import PublishedModel
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.scalars import (
    DistrictIndex,
    LocalDate,
    Percent,
    Probability,
    SchemaVersion,
    UtcInstant,
)
from snowlight.schemas.vocab import Reason, Status

MAX_DAYS = 3
# Districts next door: a school within this many miles of one of the district's schools.
NEIGHBOR_MILES = 10
MAX_NEIGHBORS = 12
# The chart runs at most a day and a half, an hour a bar.
MAX_HOURS = 36
# The district's record under a reason: its most recent days like this one.
MAX_RECORD_DAYS = 8
_HOUR = timedelta(hours=1)
_WHOLE = 100


def _tenths(value: float) -> float:
    if round(value, 1) != value:
        raise ValueError(f"a measure is given in tenths, not {value!r}")
    return value


type Inches = Annotated[
    float,
    Field(ge=0.0, le=120.0, description="Inches of snow or ice, in tenths (6.5, not 6.53)."),
    AfterValidator(_tenths),
]

type Fahrenheit = Annotated[
    int, Field(ge=-80, le=130, description="How cold or warm it feels, in whole degrees F.")
]

type Points = Annotated[
    int,
    Field(
        ge=-100,
        le=100,
        description="Whole percentage points a reason adds to the chance, or below 0 takes away.",
    ),
]

type AlertKind = Annotated[
    Literal[
        "winter_storm_warning",
        "winter_weather_advisory",
        "ice_storm_warning",
        "blizzard_warning",
        "extreme_cold_warning",
    ],
    Field(description="The weather alert a district's base chance is counted over."),
]


class PreviousChance(PublishedModel):
    """The chance of no school the run before this one gave the same district and day."""

    p_no_school: Probability
    at: UtcInstant = Field(description="When that run was made.")


class HourSpan(PublishedModel):
    """Hours of an hourly series, by position: first to last, both included."""

    first: Annotated[int, Field(ge=0, lt=MAX_HOURS)]
    last: Annotated[int, Field(ge=0, lt=MAX_HOURS)]


class Hours(PublishedModel):
    """One weather measure, an hour at a time from ``start`` to the bus hour, for the chart.

    ``snow_total``: the snow on the ground, as the running total since ``start``, in
    inches; ``low`` and ``high`` bound the total at the bus hour; ``heavy`` marks the
    hours the snow falls fastest (value i is the total at the end of hour i, so the
    heaviest snow falls from ``start`` + (first - 1) hours to ``start`` + last hours).
    ``wind_chill``: how cold it will feel each hour, in degrees F; no range, no heavy hours.
    """

    kind: Literal["snow_total", "wind_chill"]
    start: UtcInstant = Field(description="The first value's hour, on the hour.")
    values: Annotated[
        tuple[Annotated[float, Field(ge=-80.0, le=130.0), AfterValidator(_tenths)], ...],
        Field(
            min_length=2,
            max_length=MAX_HOURS,
            description="One value an hour, in tenths: inches of snow, or degrees F.",
        ),
    ]
    low: Inches | None
    high: Inches | None
    heavy: HourSpan | None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.start.minute or self.start.second:
            raise ValueError("hourly start must be on the hour")
        if (self.low is None) != (self.high is None):
            raise ValueError("hourly low and high come together")
        last = self.values[-1]
        if self.kind == "wind_chill":
            if self.low is not None or self.heavy is not None:
                raise ValueError("a wind chill series has no range and no heavy hours")
            return self
        if any(value < 0 for value in self.values):
            raise ValueError("a snow total is never below 0")
        if any(later < earlier for earlier, later in pairwise(self.values)):
            raise ValueError("a snow total is a running total: it never goes down")
        if self.low is not None and self.high is not None and not self.low <= last <= self.high:
            raise ValueError("the total at the bus hour is outside its low-to-high range")
        if self.heavy is not None:
            span = self.heavy
            if not 1 <= span.first <= span.last < len(self.values):
                raise ValueError("heavy hours must lie within the series, after its first hour")
        return self

    def hour(self, position: int) -> datetime:
        """The moment value ``position`` is for."""
        return self.start + position * _HOUR


# The base: where the chance starts for this district, before any reason.


class AlertBase(PublishedModel):
    """The district closes for about ``points`` in 100 of these alerts."""

    kind: Literal["alert"]
    points: Percent
    alert: AlertKind


class DayAfterBase(PublishedModel):
    """After a day closed for weather, the district stays closed the next day this often."""

    kind: Literal["day_after"]
    points: Percent


class SimilarDaysBase(PublishedModel):
    """The district closes for about ``points`` in 100 days with weather like this."""

    kind: Literal["similar_days"]
    points: Percent


type Base = Annotated[
    AlertBase | DayAfterBase | SimilarDaysBase,
    Field(discriminator="kind", description="Where the chance starts, before any reason."),
]


# The reasons: each a kind with its numbers, and the whole points it adds or takes away.


class SnowTotalReason(PublishedModel):
    """How much snow is coming: ``low`` to ``high`` inches, overnight or not."""

    kind: Literal["snow_total"]
    points: Points
    low: Inches
    high: Inches
    overnight: bool

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.low > self.high:
            raise ValueError("snow_total low is above its high")
        return self


class RecordReason(PublishedModel):
    """The district's own record in storms like this one (the file's ``record``)."""

    kind: Literal["record"]
    points: Points


class NeighborsReason(PublishedModel):
    """Districts next door (the entry's ``neighbors``) that already posted ``status``."""

    kind: Literal["neighbors"]
    points: Points
    districts: Annotated[tuple[DistrictIndex, ...], Field(min_length=1, max_length=MAX_NEIGHBORS)]
    status: Status


class TimingReason(PublishedModel):
    """When the heaviest snow falls, against when the buses run."""

    kind: Literal["timing"]
    points: Points
    start: UtcInstant
    end: UtcInstant

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.end <= self.start:
            raise ValueError("timing ends before it starts")
        return self


class WindChillReason(PublishedModel):
    """The wind will make it feel like ``feels_like`` at the bus stop."""

    kind: Literal["wind_chill"]
    points: Points
    feels_like: Fahrenheit


class ColdReason(PublishedModel):
    """It will feel like ``feels_like`` at the bus stop that morning."""

    kind: Literal["cold"]
    points: Points
    feels_like: Fahrenheit


class SnowStopsReason(PublishedModel):
    """The snow stops (or stopped) at ``at``, before the plows' work."""

    kind: Literal["snow_stops"]
    points: Points
    at: UtcInstant


class SunReason(PublishedModel):
    """Sun the afternoon before helps melt the ice."""

    kind: Literal["sun"]
    points: Points


class IcyRoadsReason(PublishedModel):
    """Side streets could stay icy after ``inches`` of snow."""

    kind: Literal["icy_roads"]
    points: Points
    inches: Inches


class IceReason(PublishedModel):
    """Freezing rain could leave ``inches`` of ice on the roads."""

    kind: Literal["ice"]
    points: Points
    inches: Inches


type ReasonPoints = Annotated[
    SnowTotalReason
    | RecordReason
    | NeighborsReason
    | TimingReason
    | WindChillReason
    | ColdReason
    | SnowStopsReason
    | SunReason
    | IcyRoadsReason
    | IceReason,
    Field(discriminator="kind", description="One reason, of a kind, and the points it adds."),
]


class Why(PublishedModel):
    """How the chance adds up: the base, then each reason's points, biggest first."""

    base: Base
    reasons: Annotated[tuple[ReasonPoints, ...], Field(max_length=8)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        kinds = [reason.kind for reason in self.reasons]
        if len(set(kinds)) != len(kinds):
            raise ValueError("why: each kind of reason comes once")
        if any(reason.points == 0 for reason in self.reasons):
            raise ValueError("why: a reason adds or takes away at least one point")
        return self

    def total(self) -> int:
        """The base plus every reason's points."""
        return self.base.points + sum(reason.points for reason in self.reasons)


class PastDay(PublishedModel):
    """One day in the district's record: its snow and what the district did."""

    day: LocalDate
    inches: Inches | None
    status: Status | None = Field(description="What the district did; null when it opened.")


class PastRecord(PublishedModel):
    """The district's own record in days like this one, oldest first.

    ``proves`` names the line it sits under: ``base`` (the base chance) or a reason's
    kind. ``inches`` is the least snow of a storm counted as similar, or null when the
    days are not storms (the days after one, say).
    """

    proves: Literal["base", "snow_total", "record"]
    inches: Inches | None
    days: Annotated[tuple[PastDay, ...], Field(min_length=1, max_length=MAX_RECORD_DAYS)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        for earlier, later in pairwise(self.days):
            if later.day <= earlier.day:
                raise ValueError("record days must be sorted and unique")
        if self.proves != "base":
            if self.inches is None:
                raise ValueError(f"a record under {self.proves} needs its inches")
            for past in self.days:
                if past.inches is None or past.inches < self.inches:
                    raise ValueError(f"record {past.day}: less snow than {self.inches} inches")
        return self


class SnowStarted(PublishedModel):
    """Snow started falling at ``at``."""

    kind: Literal["snow_started"]
    at: UtcInstant


class SnowStopped(PublishedModel):
    """Snow stopped at ``at``, ``inches`` in all."""

    kind: Literal["snow_stopped"]
    at: UtcInstant
    inches: Inches


type WeatherEvent = Annotated[
    SnowStarted | SnowStopped,
    Field(discriminator="kind", description="Weather that already happened, with its time."),
]


class Forecast(PublishedModel):
    """Weather that has closed or delayed these schools before is forecast that day."""

    state: Literal["forecast"]
    p_no_school: Probability
    p_delay: Probability
    reasons: Annotated[
        tuple[Reason, ...],
        Field(min_length=1, description="The forecast weather, most important first."),
    ]
    previous: PreviousChance | None
    announces_at: UtcInstant | None = Field(
        description="When the district usually posts its decision for this day."
    )
    buses_at: UtcInstant | None = Field(
        description="When the district's first buses usually run that day."
    )
    hours: Hours | None
    why: Why | None
    record: PastRecord | None
    events: Annotated[tuple[WeatherEvent, ...], Field(max_length=4)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if round(self.p_no_school + self.p_delay, 2) > 1:
            raise ValueError("p_no_school and p_delay exclude each other; their sum is over 1")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("reasons must not repeat")
        self._check_hourly()
        self._check_why()
        for earlier, later in pairwise(self.events):
            if later.at < earlier.at:
                raise ValueError("events must be in time order")
        return self

    def _check_hourly(self) -> None:
        hours = self.hours
        if hours is None:
            return
        if self.buses_at is None:
            raise ValueError("an hourly series runs to the buses, so it needs buses_at")
        bus_hour = self.buses_at.replace(minute=0, second=0)
        if hours.hour(len(hours.values) - 1) != bus_hour:
            raise ValueError("an hourly series ends at the bus hour")

    def _check_why(self) -> None:
        why = self.why
        percent = round(self.p_no_school * _WHOLE)
        if why is not None and why.total() != percent:
            raise ValueError(f"why adds up to {why.total()}, not the chance of {percent}")
        kinds = {"base"} | ({reason.kind for reason in why.reasons} if why else set())
        if self.record is not None and self.record.proves not in kinds:
            raise ValueError(f"the record proves {self.record.proves}, which is not in why")
        counts_record = why is not None and any(reason.kind == "record" for reason in why.reasons)
        if counts_record and (self.record is None or self.record.proves != "record"):
            raise ValueError("a record reason needs the record it counts")
        reasons = why.reasons if why is not None else ()
        timing = next((r for r in reasons if isinstance(r, TimingReason)), None)
        hours = self.hours
        if timing is not None and hours is not None and hours.heavy is not None:
            span = (hours.hour(hours.heavy.first - 1), hours.hour(hours.heavy.last))
            if (timing.start, timing.end) != span:
                raise ValueError("timing and the chart's heavy hours disagree")


class NoThreat(PublishedModel):
    """No weather that has closed or delayed these schools before is forecast that day."""

    state: Literal["no_threat"]


class NotEnoughData(PublishedModel):
    """The district's history is too short to give a chance."""

    state: Literal["not_enough_data"]


type DayForecast = Annotated[
    Forecast | NoThreat | NotEnoughData,
    Field(discriminator="state", description="One district's outlook for one day."),
]


class DistrictForecast(PublishedModel):
    """One district's outlook for each day in the file's days."""

    district: DistrictIndex
    neighbors: Annotated[
        tuple[DistrictIndex, ...],
        Field(
            max_length=MAX_NEIGHBORS,
            description=(
                "The districts next door, nearest first: every other district with a school "
                "within 10 miles of one of this district's schools."
            ),
        ),
    ]
    days: tuple[DayForecast, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(set(self.neighbors)) != len(self.neighbors):
            raise ValueError("neighbors must not repeat")
        if self.district in self.neighbors:
            raise ValueError("a district is not its own neighbor")
        for day in self.days:
            if not isinstance(day, Forecast) or day.why is None:
                continue
            for reason in day.why.reasons:
                if isinstance(reason, NeighborsReason) and not set(reason.districts) <= set(
                    self.neighbors
                ):
                    raise ValueError("a neighbors reason names a district that is not next door")
        return self


class PredictionsFile(PublishedModel):
    """predictions/latest.json: per district, the chance of no school or a delay, by day."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    directory: DirectoryStamp
    days: Annotated[
        tuple[LocalDate, ...],
        Field(
            min_length=1,
            max_length=MAX_DAYS,
            description="The local days forecast, consecutive, today first.",
        ),
    ]
    districts: tuple[DistrictForecast, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        for earlier, later in pairwise(self.days):
            if later - earlier != timedelta(days=1):
                raise ValueError("days must be consecutive")
        previous = -1
        for position, entry in enumerate(self.districts):
            where = f"districts[{position}]"
            if entry.district <= previous:
                raise ValueError(f"{where}: districts must be sorted and unique")
            previous = entry.district
            if entry.district >= self.directory.districts:
                raise ValueError(f"{where}: district {entry.district} is not in the directory")
            if any(neighbor >= self.directory.districts for neighbor in entry.neighbors):
                raise ValueError(f"{where}: a neighbor is not in the directory")
            if len(entry.days) != len(self.days):
                raise ValueError(f"{where}: {len(entry.days)} entries for {len(self.days)} days")
            for day, forecast in zip(self.days, entry.days, strict=True):
                if isinstance(forecast, Forecast):
                    self._check_times(f"{where} {day}", day, forecast)
        return self

    def _check_times(self, where: str, day: date, forecast: Forecast) -> None:
        if forecast.previous is not None and forecast.previous.at >= self.generated_at:
            raise ValueError(f"{where}: the previous run is not before this one")
        for event in forecast.events:
            if event.at > self.generated_at:
                raise ValueError(f"{where}: an event after generated_at has not happened")
        for past in forecast.record.days if forecast.record else ():
            if past.day >= day:
                raise ValueError(f"{where}: a record day is not before the day forecast")
