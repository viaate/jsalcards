"""``stats/season.json`` and ``track-record.json``: what has happened, counted.

Every number here is a count of observed events. Rates and percentages are left to
the reader, so the files never hold a rounded figure that disagrees with its parts.
"""

from typing import Annotated, Self

from pydantic import Field, model_validator

from snowlight.schemas.base import PublishedModel
from snowlight.schemas.scalars import (
    Count,
    LocalDate,
    Percent,
    SchemaVersion,
    SchoolYear,
    Usps,
    UtcInstant,
    school_year_bounds,
)

_STATUS_COLUMNS = 4

type DayCounts = Annotated[
    tuple[
        Annotated[LocalDate, Field(title="day")],
        Annotated[Count, Field(title="closed")],
        Annotated[Count, Field(title="delayed")],
        Annotated[Count, Field(title="remote")],
        Annotated[Count, Field(title="early_dismissal")],
    ],
    Field(description="Schools with each status on one local day."),
]

type StateCounts = Annotated[
    tuple[
        Annotated[Usps, Field(title="state")],
        Annotated[Count, Field(title="closed")],
        Annotated[Count, Field(title="delayed")],
        Annotated[Count, Field(title="remote")],
        Annotated[Count, Field(title="early_dismissal")],
    ],
    Field(description="School-days with each status in one state, over the season so far."),
]


class SeasonStats(PublishedModel):
    """stats/season.json: this school year's weather closures so far.

    days lists every local day with at least one affected school, in order; states
    sums the same school-days by state, so both add up to the same totals.
    """

    schema_version: SchemaVersion
    generated_at: UtcInstant
    season: SchoolYear
    through: LocalDate = Field(description="The last local day counted.")
    days: tuple[DayCounts, ...]
    states: tuple[StateCounts, ...]
    schools: Count = Field(description="Distinct schools with any status this season.")
    districts: Count = Field(description="Distinct districts with an affected school.")

    @model_validator(mode="after")
    def _check(self) -> Self:
        first, last = school_year_bounds(self.season)
        if not first <= self.through <= last:
            raise ValueError(f"through {self.through} is outside the {self.season} school year")
        previous = None
        for position, (day, *counts) in enumerate(self.days):
            if not first <= day <= self.through:
                raise ValueError(f"days[{position}]: {day} is outside {first}..{self.through}")
            if previous is not None and day <= previous:
                raise ValueError(f"days[{position}]: days must be sorted and unique")
            if not any(counts):
                raise ValueError(f"days[{position}]: a listed day has at least one school")
            previous = day
        codes = [row[0] for row in self.states]
        if codes != sorted(set(codes)):
            raise ValueError("states must be sorted and unique")
        day_rows = [row[1:] for row in self.days]
        state_rows = [row[1:] for row in self.states]
        by_day = [sum(row[i] for row in day_rows) for i in range(_STATUS_COLUMNS)]
        by_state = [sum(row[i] for row in state_rows) for i in range(_STATUS_COLUMNS)]
        if by_day != by_state:
            raise ValueError(f"days add up to {by_day} but states to {by_state}")
        total = sum(by_day)
        if self.schools > total or (self.schools == 0) != (total == 0):
            raise ValueError(f"{self.schools} distinct schools cannot give {total} school-days")
        if self.districts > self.schools:
            raise ValueError("more affected districts than affected schools")
        return self


type CalibrationBin = Annotated[
    tuple[
        Annotated[Percent, Field(title="low")],
        Annotated[Percent, Field(title="high")],
        Annotated[Count, Field(title="forecasts")],
        Annotated[Count, Field(title="outcomes")],
    ],
    Field(
        description=(
            "[low, high, forecasts, outcomes]: of the district-days given a chance from "
            "low up to (not including) high percent (the last bin includes 100), how "
            "many there were and how many had the outcome."
        )
    ),
]


class Calibration(PublishedModel):
    """How often one outcome happened, grouped by the chance given for it."""

    forecasts: Count
    outcomes: Count
    bins: tuple[CalibrationBin, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.bins:
            raise ValueError("bins must cover 0 to 100")
        edge = 0
        for position, (low, high, forecasts, outcomes) in enumerate(self.bins):
            if low != edge or high <= low:
                raise ValueError(f"bins[{position}]: bins must run from 0 to 100 without gaps")
            if outcomes > forecasts:
                raise ValueError(f"bins[{position}]: more outcomes than forecasts")
            edge = high
        if edge != 100:  # noqa: PLR2004 - percentages end at 100
            raise ValueError("bins must cover 0 to 100")
        if self.forecasts != sum(row[2] for row in self.bins):
            raise ValueError("forecasts is not the sum of the bins")
        if self.outcomes != sum(row[3] for row in self.bins):
            raise ValueError("outcomes is not the sum of the bins")
        return self


type LeadDays = Annotated[
    int,
    Field(
        ge=0,
        le=2,
        description="How far ahead a chance was given: 0 that morning, 1 the day before.",
    ),
]


class LeadRecord(PublishedModel):
    """How the chances given some days ahead compared with what schools did."""

    lead_days: LeadDays
    no_school: Calibration
    delay: Calibration


class TrackRecord(PublishedModel):
    """track-record.json: how past chances compared with what schools did.

    first_day and last_day bound the local days scored; both are null, and every
    count is 0, until a day has been scored.
    """

    schema_version: SchemaVersion
    generated_at: UtcInstant
    first_day: LocalDate | None
    last_day: LocalDate | None
    leads: tuple[LeadRecord, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        leads = [lead.lead_days for lead in self.leads]
        if leads != sorted(set(leads)):
            raise ValueError("leads must be sorted by lead_days and unique")
        scored = any(lead.no_school.forecasts or lead.delay.forecasts for lead in self.leads)
        if self.first_day is None or self.last_day is None:
            if self.first_day != self.last_day or scored:
                raise ValueError("first_day and last_day are set once any day is scored")
        elif self.first_day > self.last_day or not scored:
            raise ValueError("first_day..last_day must be a scored span")
        return self
