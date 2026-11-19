"""predictions/standing/<stamp>.json: what each storm-class day's chance is made of, step by step.

The school panel's why on an advisory, warning or cold class day (WHY-TRANSPARENT) shows the
start, the standing, the region, every hold and the forecast, each with its points, and the
district's own record first. ``predictions/latest.json`` names the file by its ``standing``
stamp; the numbers here change only when a class start, a delay share, a hold or a usual snow
moves (a new stamp), so the file is written once per stamp and read once per stamp.

Per district (directory position) and class, in :data:`CLASSES` order where a row has one value
per class. Published models hold no free-form keys, so a class's columns are named fields and
every sparse column is a tuple of rows led by the unit's index.
"""

from itertools import pairwise
from typing import Annotated, Final, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from snowlight.schemas.base import CompactModel
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.predictions import PlausibilityClause
from snowlight.schemas.scalars import Percent, SchemaVersion, UtcInstant

CLASSES: Final = ("advisory", "warning", "cold")
"""The storm classes, in the order of a row's values."""

FLAG_BORROWED: Final = 1
"""The district's exposure is its county's median (it has none of its own)."""
FLAG_MIXED: Final = 2
"""The district's deciding schools leave out a charter or virtual school."""
FLAG_ONE: Final = 4
"""The district has one deciding school."""
FLAG_POOL_REGION: Final = {"advisory": 8, "warning": 32}
"""Its usual snow's 10 more days are its region's (its county holds too few)."""
FLAG_POOL_NONE: Final = {"advisory": 16, "warning": 64}
"""Its usual snow takes no 10 more days (neither its county nor its region holds any)."""
FLAG_CLAMP: Final = {"advisory": 128, "warning": 256}
"""Its snow alone's floor is held at a third of its usual snow."""
FLAG_CAPPED: Final = {"advisory": 512, "warning": 1024, "cold": 2048}
"""The 6-a-winter cap lowered every kind of its days."""

PRIVATE_TROPICAL: Final = 1
"""A private row's county exposure holds a tropical storm or hurricane warning day."""
PRIVATE_CAPPED: Final = {"advisory": 2, "warning": 4, "cold": 8}
"""A private row's class lowered by the 6-a-winter cap."""

type StandingStamp = Annotated[str, Field(pattern=r"^[0-9a-f]{12}$")]

type Clause = PlausibilityClause

type RegionName = Literal[
    "northeast",
    "upper_midwest",
    "ohio_valley",
    "southeast",
    "northern_rockies",
    "south",
    "southwest",
    "northwest",
    "west",
]


def _tenths(value: float) -> float:
    if round(value, 1) != value:
        raise ValueError(f"days a winter are given in tenths, not {value!r}")
    return value


def _hundredths(value: float) -> float:
    if round(value, 2) != value:
        raise ValueError(f"a share is given in hundredths, not {value!r}")
    return value


type WinterTenths = Annotated[float, Field(ge=0.0, le=999.9), AfterValidator(_tenths)]
type WinterDays = tuple[
    Annotated[WinterTenths, Field(title="advisory")],
    Annotated[WinterTenths, Field(title="warning")],
    Annotated[WinterTenths, Field(title="cold")],
]
"""School days a winter of each class (advisory, warning, cold)."""

type StandingIndex = Annotated[int, Field(ge=0)]
type StandingCount = Annotated[int, Field(ge=0)]
type StandingPoints = Annotated[int, Field(ge=-100, le=100)]
type Inches100 = Annotated[int, Field(ge=0, le=3000)]
"""Inches of snow in hundredths (562 is 5.62 inches)."""

type StandingFlags = Annotated[int, Field(ge=0, le=4095)]
type FallYear = Annotated[int, Field(ge=2000, le=2100)]


class StandingLevel(CompactModel):
    """A class's start: before this winter, as this winter's storms would move it, and as
    served (whole percent at a district with the middle exposure)."""

    prior: Percent
    fit: Percent
    now: Percent
    storms: StandingCount
    """This winter's storms the start has counted."""
    q: Annotated[float, Field(ge=0.0, le=1.0), AfterValidator(_hundredths)]
    """The class's share of delayed starts among its days with school."""
    shrunk: Annotated[tuple[Clause, ...], Field(max_length=3)] = ()
    """The clauses that held the start back toward its prior (empty: none)."""
    alpha: float
    """The served alpha (log odds at the middle exposure, before the spread)."""
    tau: Annotated[float, Field(gt=0.0)]
    """The served spread between districts (log odds)."""


class StandingLevels(CompactModel):
    advisory: StandingLevel
    warning: StandingLevel
    cold: StandingLevel


class StandingRefs(CompactModel):
    """Each class's middle of the school days a winter, over districts that get any."""

    advisory: WinterTenths
    warning: WinterTenths
    cold: WinterTenths


class StandingRegionDelta(CompactModel):
    region: RegionName
    delta: float
    clipped: bool = False
    """The region's difference hit the set limit."""


class StandingRegionDeltas(CompactModel):
    advisory: tuple[StandingRegionDelta, ...]
    warning: tuple[StandingRegionDelta, ...]
    cold: tuple[StandingRegionDelta, ...]


type UsualColumn = tuple[Inches100 | None, ...]


class StandingSnow(CompactModel):
    """Per district, for the two classes the forecast moves."""

    advisory: UsualColumn
    warning: UsualColumn


class StandingOwn(CompactModel):
    """Per district, its own 9 PM forecasts of each class's school days."""

    advisory: tuple[StandingCount, ...]
    warning: tuple[StandingCount, ...]


type RegionRow = tuple[
    Annotated[StandingIndex, Field(title="unit")],
    Annotated[StandingPoints, Field(title="points")],
    Annotated[int, Field(ge=0, le=1, title="clipped")],
]
"""[unit, region points, 1 where its region's difference hit the limit]."""
type HeldRow = tuple[
    Annotated[StandingIndex, Field(title="unit")],
    Annotated[StandingPoints, Field(title="district")],
    Annotated[StandingPoints, Field(title="national")],
    Annotated[StandingPoints, Field(title="rounding")],
    Annotated[int, Field(ge=0, le=3, title="acted")],
]
"""[unit, district stage, national stage, rounding] points, and the stages that moved the chance
at all: 1 the district pull or cap, 2 the national steps (a stage that moved it under a point is
a "0" row)."""
type RecordRow = tuple[
    Annotated[StandingIndex, Field(title="unit")],
    Annotated[StandingCount, Field(title="closed")],
    Annotated[StandingCount, Field(title="delayed")],
    Annotated[StandingCount, Field(title="of")],
]
"""[unit, no school, a late start, days the lists tell us about]."""
type RecordSum = tuple[
    Annotated[StandingCount, Field(title="closed")],
    Annotated[StandingCount, Field(title="delayed")],
    Annotated[StandingCount, Field(title="of")],
]
"""[no school, a late start, days], summed over a record."""


class StandingRegion(CompactModel):
    advisory: tuple[RegionRow, ...]
    warning: tuple[RegionRow, ...]
    cold: tuple[RegionRow, ...]


class StandingHeld(CompactModel):
    advisory: tuple[HeldRow, ...]
    warning: tuple[HeldRow, ...]
    cold: tuple[HeldRow, ...]


class StandingRecord(CompactModel):
    advisory: tuple[RecordRow, ...]
    warning: tuple[RecordRow, ...]
    cold: tuple[RecordRow, ...]


class StandingSums(CompactModel):
    advisory: RecordSum
    warning: RecordSum
    cold: RecordSum


type PrivateRow = tuple[
    Annotated[WinterDays | None, Field(title="winter")],
    Annotated[StandingPoints, Field(title="region")],
    Annotated[int, Field(ge=0, le=15, title="bits")],
]
"""[its county's days a winter or null, advisory region points, bits]."""


class PrivateStanding(CompactModel):
    """The private schools, by row: each distinct county exposure, region, tropical flag and
    hold; ``of`` gives each school's row in ``predictions/latest.json``'s ``schools`` order."""

    rows: tuple[PrivateRow, ...]
    of: tuple[Annotated[int, Field(ge=-1)], ...]
    record: StandingRecord
    """[school's place in ``of``, no school, a late start, days]."""
    record_sum: StandingSums
    held: StandingHeld
    """Keyed by row."""

    @model_validator(mode="after")
    def _check(self) -> Self:
        if any(row >= len(self.rows) for row in self.of):
            raise ValueError("private: a school names a row the file does not hold")
        return self


class StandingFile(CompactModel):
    """predictions/standing/<stamp>.json (see the module docstring)."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    directory: DirectoryStamp
    stamp: StandingStamp
    ref: StandingRefs
    nodes: Annotated[int, Field(ge=1, le=999)]
    """The quadrature points of each start's spread."""
    winters: tuple[
        Annotated[FallYear, Field(title="first")], Annotated[FallYear, Field(title="last")]
    ]
    """The first and last fall of the winters the days a winter count."""
    climate_winters: tuple[
        Annotated[FallYear, Field(title="first")], Annotated[FallYear, Field(title="last")]
    ]
    """... the 9 PM forecasts the usual snow is set from."""
    record_winters: tuple[
        Annotated[FallYear, Field(title="first")], Annotated[FallYear, Field(title="last")]
    ]
    """... the closings lists the record counts."""
    climate_window: Literal["whole", "still_to_come"]
    levels: StandingLevels
    region_delta: StandingRegionDeltas
    winter: tuple[WinterDays | None, ...]
    flags: tuple[StandingFlags, ...]
    usual: StandingSnow
    alone: StandingSnow
    own: StandingOwn
    region: StandingRegion
    held: StandingHeld
    held_clauses: Annotated[tuple[Clause, ...], Field(max_length=4)] = ()
    record: StandingRecord
    record_sum: StandingSums
    private: PrivateStanding

    @model_validator(mode="after")
    def _check(self) -> Self:
        count = self.directory.districts
        columns = (
            self.winter,
            self.flags,
            self.usual.advisory,
            self.usual.warning,
            self.alone.advisory,
            self.alone.warning,
            self.own.advisory,
            self.own.warning,
        )
        if any(len(column) != count for column in columns):
            raise ValueError("standing: a per-district column is not one value per district")
        for klass in CLASSES:
            for table in (self.region, self.held, self.record):
                rows = getattr(table, klass)
                if any(row[0] >= count for row in rows):
                    raise ValueError(f"standing: a {klass} row names no district")
                if any(b[0] <= a[0] for a, b in pairwise(rows)):
                    raise ValueError(f"standing: {klass} rows are sorted and unique")
        for klass in CLASSES:
            for row in (*getattr(self.record, klass), *getattr(self.private.record, klass)):
                if row[1] + row[2] > row[3] or row[3] < 1:
                    raise ValueError("standing: a record's parts are more than its days")
        for klass in ("advisory", "warning"):
            usual, alone = getattr(self.usual, klass), getattr(self.alone, klass)
            if any(
                b is not None and (u is None or b >= u) for u, b in zip(usual, alone, strict=True)
            ):
                raise ValueError("standing: a snow alone shows only under its usual snow")
        return self
