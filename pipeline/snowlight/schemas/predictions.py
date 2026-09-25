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
"""

from datetime import timedelta
from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from snowlight.schemas.base import PublishedModel
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.scalars import (
    DistrictIndex,
    LocalDate,
    Probability,
    SchemaVersion,
    UtcInstant,
)
from snowlight.schemas.vocab import Reason

MAX_DAYS = 3


class Forecast(PublishedModel):
    """Weather that has closed or delayed these schools before is forecast that day."""

    state: Literal["forecast"]
    p_no_school: Probability
    p_delay: Probability
    reasons: Annotated[
        tuple[Reason, ...],
        Field(min_length=1, description="The forecast weather, most important first."),
    ]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if round(self.p_no_school + self.p_delay, 2) > 1:
            raise ValueError("p_no_school and p_delay exclude each other; their sum is over 1")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("reasons must not repeat")
        return self


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
    days: tuple[DayForecast, ...]


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
            if len(entry.days) != len(self.days):
                raise ValueError(f"{where}: {len(entry.days)} entries for {len(self.days)} days")
        return self
