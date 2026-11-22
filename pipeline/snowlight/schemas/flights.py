"""The Flights files (docs/flights.md), all under ``flights/`` on the live host.

* ``flights/airports.json``: every airport on the map (:class:`FlightsAirports`);
* ``flights/latest.json``: names the newest live file (:class:`FlightsLatest`);
* ``flights/live/<slot>.json``: the chances by airport, day and block, with the FAA programs,
  the NWS alerts and the weather now, each with the time it was read (:class:`FlightsLive`);
* ``flights/routes/<code>.json``: the usual flights from one airport (:class:`FlightsRoutes`);
* ``flights/records/<code>.json``: one airport's own record in bad weather (:class:`FlightsRecord`);
* ``flights/track-record.json``: how the chances did on the held-out year and since
  (:class:`FlightsTrackRecord`);
* ``flights/replays/index.json`` and ``flights/replays/<id>.json``: past storm days, what the
  model would have said the evening before next to what happened (:class:`FlightsReplayIndex`,
  :class:`FlightsReplay`).

Chances are tenths of a percent (per mille, 0 to 1000), so a small chance is never written as
0. Where a target's chance did not pass the held-out test at an airport
(D6), the value is the airport's usual rate and its bit is set in the matching ``usual`` mask: a
reader shows it as the usual rate, never as a forecast. ``None`` is a block with no value (past,
or beyond the forecast).
"""

from enum import IntEnum
from typing import Annotated, Final, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from snowlight.schemas.base import SCREENED, PublishedModel, screen_text
from snowlight.schemas.scalars import (
    Count,
    Latitude,
    LocalDate,
    Longitude,
    MinuteOfDay,
    SchemaVersion,
    UtcInstant,
)

DAYS: Final = 3
"""Today and the next two local days."""
BLOCKS: Final = 5
"""Early 5-9, morning 9-12, afternoon 12-17, evening 17-21, night 21-5 (local)."""
LEADS: Final = 3

type FlightsAirportCode = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z0-9]{3}$"),
    Field(description="An airport's three-letter code as people say it (MCI)."),
]
type FlightsCarrierCode = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z0-9]{2}$"),
    Field(description="An airline's two-character code (WN)."),
]
type FlightsStateCode = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z]{2}$"),
    Field(description="Two-letter state or territory code."),
]
type FlightsZoneName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_]+/[A-Za-z_/+-]+$"),
    Field(description="An IANA time zone (America/Chicago)."),
]
type FlightsPlaceName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=120),
    AfterValidator(screen_text),
    SCREENED,
    Field(description="An airport's or city's name."),
]
type FlightsLiveStamp = Annotated[
    str,
    StringConstraints(pattern=r"^\d{8}T\d{4}Z$"),
    Field(description="A live file's stamp: its UTC minute, YYYYMMDDTHHMMZ."),
]
type FlightsSlot = Annotated[
    str,
    StringConstraints(pattern=r"^slot-[0-2]$"),
    Field(description="One of the three live files the passes take in turn."),
]
type FlightsReplayId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z0-9]{3}-\d{4}-\d{2}-\d{2}$"),
    Field(description="A past storm day: the airport and the local date (MCI-2025-01-05)."),
]
type FlightsMonthLabel = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}$"),
    Field(description="A calendar month, YYYY-MM."),
]
type FlightsPerMille = Annotated[int, Field(ge=0, le=1000, description="Tenths of a percent.")]
type FlightsBlockMask = Annotated[
    int, Field(ge=0, le=31, description="One bit per block, early first (bit 0).")
]
type FlightsDayMask = Annotated[int, Field(ge=0, le=7, description="One bit per day, today first.")]
type FlightsLeadMask = Annotated[
    int, Field(ge=0, le=7, description="One bit per lead class, 1 (bit 0) to 3 (bit 2).")
]
type FlightsWeekdayMask = Annotated[
    int, Field(ge=1, le=127, description="One bit per weekday, Monday (bit 0) to Sunday.")
]
type FlightsScore = Annotated[float, Field(ge=0.0, le=1.0, description="A Brier score.")]
type FlightsSkill = Annotated[
    float, Field(ge=-100.0, le=1.0, description="1 minus the Brier score over the usual rate's.")
]

type FlightsChance = FlightsPerMille | None
type FlightsBlockRow = tuple[
    Annotated[FlightsChance, Field(title="early")],
    Annotated[FlightsChance, Field(title="morning")],
    Annotated[FlightsChance, Field(title="afternoon")],
    Annotated[FlightsChance, Field(title="evening")],
    Annotated[FlightsChance, Field(title="night")],
]
type FlightsDayMasks = tuple[
    Annotated[FlightsBlockMask, Field(title="today")],
    Annotated[FlightsBlockMask, Field(title="tomorrow")],
    Annotated[FlightsBlockMask, Field(title="after")],
]
type FlightsTargetMasks = tuple[
    Annotated[FlightsLeadMask, Field(title="dep_canc")],
    Annotated[FlightsLeadMask, Field(title="dep_late")],
    Annotated[FlightsLeadMask, Field(title="arr_canc")],
    Annotated[FlightsLeadMask, Field(title="arr_late")],
    Annotated[FlightsLeadMask, Field(title="rough")],
]
type FlightsCounts = tuple[
    Annotated[Count, Field(title="early")],
    Annotated[Count, Field(title="morning")],
    Annotated[Count, Field(title="afternoon")],
    Annotated[Count, Field(title="evening")],
    Annotated[Count, Field(title="night")],
]
type FlightsDayRows = tuple[
    Annotated[FlightsBlockRow, Field(title="today")],
    Annotated[FlightsBlockRow, Field(title="tomorrow")],
    Annotated[FlightsBlockRow, Field(title="after")],
]
type FlightsDayChances = tuple[
    Annotated[FlightsChance, Field(title="today")],
    Annotated[FlightsChance, Field(title="tomorrow")],
    Annotated[FlightsChance, Field(title="after")],
]
type FlightsUsualMasks = tuple[
    Annotated[FlightsDayMasks, Field(title="dep_canc")],
    Annotated[FlightsDayMasks, Field(title="dep_late")],
    Annotated[FlightsDayMasks, Field(title="arr_canc")],
    Annotated[FlightsDayMasks, Field(title="arr_late")],
]
type FlightsWhys = tuple[FlightsWhy, ...]
type FlightsDayWhys = tuple[
    Annotated[FlightsWhys, Field(title="today")],
    Annotated[FlightsWhys, Field(title="tomorrow")],
    Annotated[FlightsWhys, Field(title="after")],
]
type FlightsDayRuns = tuple[
    Annotated[UtcInstant | None, Field(title="today")],
    Annotated[UtcInstant | None, Field(title="tomorrow")],
    Annotated[UtcInstant | None, Field(title="after")],
]
type FlightsMonthSpan = tuple[
    Annotated[FlightsMonthLabel, Field(title="first")],
    Annotated[FlightsMonthLabel, Field(title="last")],
]


class FlightsTarget(IntEnum):
    """What a chance is of."""

    DEP_CANC = 0
    """A departure is cancelled."""
    DEP_LATE = 1
    """A departure leaves 45+ minutes late."""
    ARR_CANC = 2
    """An arrival is cancelled."""
    ARR_LATE = 3
    """An arrival comes 45+ minutes late."""
    ROUGH = 4
    """The airport cancels 10% or more of the day's departures."""


class FlightsWhy(IntEnum):
    """A plain reason in the forecast for a day."""

    SNOW = 0
    ICE = 1
    THUNDER = 2
    WIND = 3
    FOG = 4
    COLD = 5
    HUBS = 6
    """Bad weather at the big hubs."""
    BEFORE = 7
    """Snow or ice in the hours before."""


class FlightsProgram(IntEnum):
    """An FAA traffic program or status at an airport."""

    GROUND_STOP = 0
    GROUND_DELAY = 1
    DEPARTURE_DELAY = 2
    ARRIVAL_DELAY = 3
    CLOSED = 4
    DEICING = 5


class FlightsProgramWhy(IntEnum):
    """The kind of reason the FAA gives for a program (its own words stay in the archive)."""

    OTHER = 0
    WEATHER = 1
    VOLUME = 2
    """More flights than the airport can take then."""
    EQUIPMENT = 3
    RUNWAY = 4
    """A runway closed or under work."""


class FlightsAlert(IntEnum):
    """An NWS alert in effect at the airport."""

    WINTER_STORM = 0
    BLIZZARD = 1
    ICE_STORM = 2
    WINTER_WEATHER = 3
    SEVERE_THUNDERSTORM = 4
    TORNADO = 5
    HIGH_WIND = 6
    DENSE_FOG = 7
    HURRICANE = 8
    TROPICAL_STORM = 9
    EXTREME_COLD = 10


class FlightsKind(IntEnum):
    """A kind of weather in an airport's own record."""

    FREEZING_RAIN = 1
    SNOW = 2
    THUNDER = 3
    FOG = 4
    WIND = 5


class FlightsVerdict(IntEnum):
    """What a record says (the lead's ruling LR-F1). Value 1 (the retired middle verdict) is
    never published."""

    NONE = 0
    """No verdict: the box gives the numbers alone."""
    SOONER = 2
    """Cancels sooner than most."""
    LONGER = 3
    """Holds out longer than most."""


class FlightsHeld(IntEnum):
    """How a past storm day was kept from the model."""

    TEST_YEAR = 0
    """It is in the held-out test year."""
    LEFT_OUT = 1
    """Its winter was left out of a separate fit made for it (the usual rates' window and the
    input groups were chosen on the validation year, which holds it; neither is a fit)."""


# --- airports ----------------------------------------------------------------------------------


class FlightsAirportEntry(PublishedModel):
    """One airport on the map."""

    code: FlightsAirportCode
    name: FlightsPlaceName
    city: FlightsPlaceName
    state: FlightsStateCode
    lat: Latitude
    lon: Longitude
    tz: FlightsZoneName
    per_day: Annotated[float, Field(ge=0.0, le=10_000.0)] = Field(
        description="Scheduled departures per day over the last 12 posted months."
    )


class FlightsAirports(PublishedModel):
    """``flights/airports.json``."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    months: FlightsMonthSpan = Field(
        description="The first and last posted month the departures per day count."
    )
    airports: tuple[FlightsAirportEntry, ...]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        codes = [airport.code for airport in self.airports]
        if len(set(codes)) != len(codes):
            raise ValueError("an airport is listed twice")
        return self


# --- live --------------------------------------------------------------------------------------


class FlightsLatest(PublishedModel):
    """``flights/latest.json``: the newest live file."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    slot: FlightsSlot = Field(description="The newest live file: flights/live/<slot>.json.")
    stamp: FlightsLiveStamp = Field(
        description=(
            "That file's stamp. The three slot files are reused in turn, so a reader takes a slot"
            " file as current only when its own stamp is this one; any other stamp is an older"
            " pass (a cached copy) and is stale."
        )
    )


class FlightsProgramNow(PublishedModel):
    """An FAA program at an airport when it was read."""

    program: FlightsProgram
    minutes: Annotated[int, Field(ge=0, le=1440)] | None = Field(
        description="The average or longest delay it gives, in minutes; none when not given."
    )
    until: UtcInstant | None = Field(description="When it is set to end; none when not given.")
    why: FlightsProgramWhy = Field(description="The kind of reason the FAA gives.")


class FlightsWeatherNow(PublishedModel):
    """The airport's latest weather report."""

    at: UtcInstant
    kinds: tuple[FlightsKind, ...] = Field(description="The record's weather kinds it shows.")
    visibility: Annotated[float, Field(ge=0.0, le=100.0)] | None = Field(description="Miles.")
    gust: Annotated[int, Field(ge=0, le=200)] | None = Field(description="Knots.")


class FlightsAirportLive(PublishedModel):
    """One airport's chances and what is going on now."""

    code: FlightsAirportCode
    today: LocalDate = Field(description="The airport's own date when the file was made.")
    dep_canc: FlightsDayRows
    dep_late: FlightsDayRows
    arr_canc: FlightsDayRows
    arr_late: FlightsDayRows
    rough: FlightsDayChances
    runs: FlightsDayRuns = Field(
        description=(
            "Per day, the 00Z forecast run of the evening (or two or three evenings) before that"
            " day the day's chances come from; none: no run read covers that day."
        )
    )
    usual: FlightsUsualMasks = Field(
        description="Per block target, per day: the blocks whose value is the usual rate."
    )
    rough_usual: FlightsDayMask = Field(
        description="The days whose rough-day value is the usual rate."
    )
    why: FlightsDayWhys = Field(
        description="Per day, the plain reasons in the forecast, strongest first."
    )
    programs: tuple[FlightsProgramNow, ...] | None = Field(
        description=(
            "FAA programs in effect when read (empty: none in effect, as of programs_at); none:"
            " not read for this airport this pass, so nothing is known of them."
        )
    )
    alerts: tuple[FlightsAlert, ...] | None = Field(
        description=(
            "NWS alerts in effect when read (empty: none, as of alerts_at); none: not read for"
            " this airport this pass, so nothing is known of them."
        )
    )
    now: FlightsWeatherNow | None = Field(
        description="The airport's newest weather report; none: no report read this pass."
    )


class FlightsLive(PublishedModel):
    """``flights/live/<slot>.json``: the passes take the three slots in turn, so each file is
    rewritten an hour after it was last written (past any cache) and the host keeps three."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    slot: FlightsSlot
    stamp: FlightsLiveStamp
    run: UtcInstant | None = Field(
        description=(
            "The newest forecast run read; none: no forecast was read. Each airport day names"
            " its own run (runs)."
        )
    )
    programs_at: UtcInstant | None = Field(
        description="When the FAA programs were read; none: they could not be read."
    )
    alerts_at: UtcInstant | None = Field(
        description="When the NWS alerts were read; none: they could not be read."
    )
    weather_at: UtcInstant | None = Field(
        description="When the weather reports were read; none: they could not be read."
    )
    observed_at: UtcInstant | None = Field(
        description=(
            "The newest hour of the observed reports read (the hours before the runs); none:"
            " they could not be read, and every chance is the usual rate. An airport whose own"
            " reports end more than 3 hours before the newest run shows the usual rate."
        )
    )
    airports: tuple[FlightsAirportLive, ...]


# --- routes ------------------------------------------------------------------------------------


class FlightsUsualFlight(PublishedModel):
    """A flight that flew the route in a posted month."""

    carrier: FlightsCarrierCode
    number: Annotated[int, Field(ge=1, le=9999)]
    to_airport: FlightsAirportCode
    leaves: MinuteOfDay = Field(description="Scheduled departure, the departure airport's clock.")
    lands: MinuteOfDay = Field(description="Scheduled arrival, the arrival airport's clock.")
    weekdays: FlightsWeekdayMask
    days: Count = Field(description="Days it flew that month.")
    cancelled: Count
    late: Count = Field(description="Days it left 45+ minutes late.")


class FlightsRouteMonth(PublishedModel):
    """The usual flights of one posted month."""

    month: FlightsMonthLabel
    flights: tuple[FlightsUsualFlight, ...]


class FlightsRoutes(PublishedModel):
    """``flights/routes/<code>.json``: the usual flights from one airport (D11)."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    code: FlightsAirportCode
    months: tuple[FlightsRouteMonth, ...]


# --- own records -------------------------------------------------------------------------------


class FlightsRecordLine(PublishedModel):
    """A record in one kind of weather."""

    kind: FlightsKind
    blocks: Count = Field(
        description=(
            "Time blocks of this weather counted in the record: an airport's with 3+ departures,"
            " a carrier's with 2+ of its own."
        )
    )
    bad: Count = Field(description="Of those, blocks with 10% or more of departures cancelled.")
    days: Count = Field(
        description="Days with a block of this weather and a peer in it the same day."
    )
    bad_days: Count = Field(description="Of those, days with a bad block of this weather.")
    share: FlightsPerMille = Field(description="Its departures cancelled in those blocks.")
    others: FlightsPerMille = Field(
        description=(
            "Its peers' share in the same weather on the same days, each day's weighted by its"
            " own departures that day."
        )
    )
    worse: Count = Field(
        description=(
            "Days the test counts (one cancel or more expected at the peers' share that day) on"
            " which it cancelled clearly more than its peers."
        )
    )
    better: Count = Field(
        description=(
            "Days the test counts on which it cancelled clearly fewer than its peers that day."
        )
    )
    verdict: FlightsVerdict


class FlightsCarrierRecord(PublishedModel):
    """One airline's record at the airport, against the others in the same blocks."""

    carrier: FlightsCarrierCode
    lines: tuple[FlightsRecordLine, ...]


class FlightsRecord(PublishedModel):
    """``flights/records/<code>.json``: one airport's own record (D8)."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    code: FlightsAirportCode
    first: LocalDate
    last: LocalDate
    lines: tuple[FlightsRecordLine, ...]
    carriers: tuple[FlightsCarrierRecord, ...]


# --- the track record --------------------------------------------------------------------------


class FlightsBin(PublishedModel):
    """One bin of the reliability table."""

    low: FlightsPerMille
    high: FlightsPerMille
    units: Count
    said: FlightsPerMille
    seen: FlightsPerMille


class FlightsTargetTest(PublishedModel):
    """The held-out test of one target and lead, pooled over airports."""

    target: FlightsTarget
    lead: Annotated[int, Field(ge=1, le=LEADS)]
    units: Count
    events: Count
    expected: Count
    brier: FlightsScore
    brier_usual: FlightsScore
    skill: FlightsSkill = Field(description="The model's chances at every airport tested.")
    skill_published: FlightsSkill = Field(
        description="What the files show: the chance where it passed, else the usual rate."
    )
    skill_confirmed: FlightsSkill = Field(
        description=(
            "Out of selection: airports chosen on the even weeks of the test year scored on the"
            " odd ones, and the reverse."
        )
    )
    published: Count = Field(description="Airports where this chance passed the test.")
    tested: Count = Field(description="Airports tested.")
    bins: tuple[FlightsBin, ...] = Field(
        description=(
            "Reliability of what the files would have shown in the test year: the model's"
            " chance where it passed, the usual rate elsewhere."
        )
    )


class FlightsAirportGate(PublishedModel):
    """Which of one airport's chances passed the test, per target, by lead class."""

    code: FlightsAirportCode
    passed: FlightsTargetMasks = Field(
        description="Per target in FlightsTarget order, the lead classes that passed."
    )


class FlightsMonthScore(PublishedModel):
    """How the published chances did in one month, scored once its flights were posted."""

    month: FlightsMonthLabel
    target: FlightsTarget
    units: Count
    brier: FlightsScore
    brier_usual: FlightsScore
    rough_days: Count
    caught: Count = Field(description="Rough days given 30% or more the evening before.")
    days_in_month: Annotated[int, Field(ge=28, le=31, description="The month's days.")]
    days_scored: Annotated[
        int,
        Field(
            ge=0,
            le=31,
            description="The month's days whose evening-before chances were scored: a day "
            "whose snapshot was not kept is left out, so fewer than days_in_month says the "
            "month was scored in part.",
        ),
    ]

    @model_validator(mode="after")
    def _days_fit(self) -> Self:
        if self.days_scored > self.days_in_month:
            msg = f"{self.days_scored} days scored in a month of {self.days_in_month}"
            raise ValueError(msg)
        return self


class FlightsTrackRecord(PublishedModel):
    """``flights/track-record.json``: how the flight chances did (D9)."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    test_first: LocalDate
    test_last: LocalDate
    usual_first: LocalDate = Field(
        description="The first day the usual rates average over (the test year's, and the "
        "live files' usual rates, which come from the same model)."
    )
    usual_last: LocalDate = Field(
        description="The last day the usual rates average over, before the test year: they "
        "are a dated average, never a rate of the test year or of today."
    )
    tests: tuple[FlightsTargetTest, ...]
    airports: tuple[FlightsAirportGate, ...]
    months: tuple[FlightsMonthScore, ...]

    @model_validator(mode="after")
    def _usual_before_test(self) -> Self:
        if not self.usual_first <= self.usual_last < self.test_first:
            msg = (
                f"usual window {self.usual_first} to {self.usual_last} must end before the "
                f"test year ({self.test_first})"
            )
            raise ValueError(msg)
        return self


# --- past storms -------------------------------------------------------------------------------


class FlightsReplaySummary(PublishedModel):
    """A past storm day in the index."""

    id: FlightsReplayId
    code: FlightsAirportCode
    day: LocalDate
    apart: FlightsHeld = Field(description="How the day was kept apart from the model.")
    said: FlightsPerMille = Field(description="The rough-day chance the evening before.")
    cancelled: FlightsPerMille = Field(description="The day's departures cancelled.")


class FlightsReplayIndex(PublishedModel):
    """``flights/replays/index.json``."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    replays: tuple[FlightsReplaySummary, ...]


class FlightsReplay(PublishedModel):
    """``flights/replays/<id>.json``: one past storm day (D14)."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    id: FlightsReplayId
    code: FlightsAirportCode
    day: LocalDate
    apart: FlightsHeld = Field(description="How the day was kept apart from the model.")
    run: UtcInstant = Field(description="The forecast run the evening before.")
    said: FlightsBlockRow = Field(description="The departure cancel chance said per block.")
    said_usual: FlightsBlockMask
    departures: FlightsCounts
    cancelled: FlightsCounts
    rough_said: FlightsPerMille
    rough_usual: bool
    why: tuple[FlightsWhy, ...]


# --- the model and the archive -------------------------------------------------------------------


class FlightsInput(IntEnum):
    """One input of the chances' regressions, in the order of their coefficients
    (``snowlight.flights.model.FEATURES``)."""

    BASE = 0
    SNOW = 1
    SNOW_BEFORE = 2
    ICE = 3
    P_SNOW = 4
    P_ZR = 5
    THUNDER = 6
    GUST = 7
    WIND = 8
    LOW_VIS = 9
    LOW_CIG = 10
    COLD = 11
    SOUTH_SNOW = 12
    HUB_SNOW = 13
    HUB_STORM = 14
    DAY_SNOW = 15
    DAY_ICE = 16
    DAY_STORM = 17
    PRE_SNOW = 18
    PRE_ICE = 19
    OBS_SNOW = 20
    OBS_SNOW_OLD = 21
    OBS_FRZ = 22


type FlightsCoefficient = Annotated[float, Field(ge=-1e6, le=1e6)]
type FlightsShare = Annotated[float, Field(ge=0.0, le=1.0, description="A share, 0 to 1.")]
type FlightsMonthShares = tuple[FlightsShare, ...]
"""Twelve shares, January first."""
type FlightsBlockMonths = tuple[FlightsMonthShares, ...]
"""Five blocks (early first) of twelve months."""


def _shape(value: tuple[tuple[float, ...], ...] | tuple[float, ...], blocks: bool) -> None:
    rows = value if blocks else (value,)
    if blocks and len(rows) != BLOCKS:
        raise ValueError(f"{len(rows)} blocks, not {BLOCKS}")
    for row in rows:
        if not isinstance(row, tuple) or len(row) != 12:  # noqa: PLR2004 - months
            raise ValueError("a row of usual rates is not twelve months")


class FlightsFit(PublishedModel):
    """One regression: ``chance = 1 / (1 + exp(-(intercept + sum(coef * (x - mean) / scale))))``
    over the inputs in :class:`FlightsInput` order."""

    target: FlightsTarget
    lead: Annotated[int, Field(ge=1, le=LEADS)]
    intercept: FlightsCoefficient
    coef: tuple[FlightsCoefficient, ...]
    mean: tuple[FlightsCoefficient, ...]
    scale: tuple[Annotated[float, Field(gt=0.0, le=1e6)], ...]
    after_storm: bool = Field(
        description=(
            "Whether its chances passed on the days after an observed storm; where not, those"
            " days show the usual rate."
        )
    )

    @model_validator(mode="after")
    def _lengths(self) -> Self:
        if not len(self.coef) == len(self.mean) == len(self.scale):
            raise ValueError("coef, mean and scale differ in length")
        return self


class FlightsUsualRates(PublishedModel):
    """Usual rates: per block and month the shares cancelled and late, and per month the share
    of rough days."""

    dep_canc: FlightsBlockMonths
    dep_late: FlightsBlockMonths
    arr_canc: FlightsBlockMonths
    arr_late: FlightsBlockMonths
    rough: FlightsMonthShares

    @model_validator(mode="after")
    def _shapes(self) -> Self:
        for table in (self.dep_canc, self.dep_late, self.arr_canc, self.arr_late):
            _shape(table, blocks=True)
        _shape(self.rough, blocks=False)
        return self


class FlightsAirportUsual(PublishedModel):
    """One airport's usual rates."""

    code: FlightsAirportCode
    rates: FlightsUsualRates


class FlightsModel(PublishedModel):
    """``flights/model.json``: the fitted chances the live job uses (the committed model file,
    gzipped, has the same content), refit and published by the monthly job."""

    schema_version: SchemaVersion
    inputs: tuple[FlightsInput, ...] = Field(description="The regressions' inputs, in order.")
    test_first: LocalDate
    test_last: LocalDate
    fits: tuple[FlightsFit, ...]
    gates: tuple[FlightsAirportGate, ...]
    usual: tuple[FlightsAirportUsual, ...]
    national: FlightsUsualRates = Field(description="For an airport with no history.")

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        for fit in self.fits:
            if len(fit.coef) != len(self.inputs):
                raise ValueError(f"{fit.target.name}/{fit.lead}: not one coefficient per input")
        keys = [(fit.target, fit.lead) for fit in self.fits]
        if len(set(keys)) != len(keys):
            raise ValueError("a regression is listed twice")
        codes = [entry.code for entry in self.usual]
        if len(set(codes)) != len(codes):
            raise ValueError("an airport's usual rates are listed twice")
        if self.test_last < self.test_first:
            raise ValueError("the test year ends before it starts")
        return self


type FlightsProgramText = Annotated[
    str,
    StringConstraints(max_length=80),
    AfterValidator(screen_text),
    SCREENED,
    Field(description="The FAA's reason as it wrote it (screened)."),
]
type FlightsForecastText = Annotated[
    str,
    StringConstraints(max_length=1200),
    AfterValidator(screen_text),
    SCREENED,
    Field(description="An airport forecast (TAF) as issued, in its coded form."),
]


class FlightsUsualTomorrow(PublishedModel):
    """An airport's usual rates for the day after the snapshot's ``today``, as published."""

    code: FlightsAirportCode
    dep_canc: FlightsBlockRow
    rough: FlightsPerMille


class FlightsArchiveProgram(PublishedModel):
    """An FAA program as read."""

    code: FlightsAirportCode
    program: FlightsProgram
    minutes: Annotated[int, Field(ge=0, le=1440)] | None
    why: FlightsProgramText


class FlightsArchiveReport(PublishedModel):
    """An airport's latest weather report as read."""

    code: FlightsAirportCode
    report: FlightsWeatherNow


class FlightsArchiveForecast(PublishedModel):
    """An airport's newest TAF as read."""

    code: FlightsAirportCode
    text: FlightsForecastText


class FlightsArchive(PublishedModel):
    """``flights/archive/<NNN>.json``: one day's snapshot (D9), kept in a ring of slots."""

    schema_version: SchemaVersion
    slot: Annotated[str, StringConstraints(pattern=r"^\d{3}$")] = Field(
        description="The ring slot it is kept in: the day's ordinal modulo the ring's days."
    )
    day: LocalDate = Field(description="The UTC date of the 00Z run the snapshot holds.")
    live: FlightsLive = Field(description="The live file published.")
    usual_tomorrow: tuple[FlightsUsualTomorrow, ...] = Field(
        description="The usual rates behind it, rounded as the published chances are."
    )
    programs: tuple[FlightsArchiveProgram, ...]
    reports: tuple[FlightsArchiveReport, ...]
    forecasts: tuple[FlightsArchiveForecast, ...]
