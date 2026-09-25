"""The live files: ``live/closings.json``, ``live/covered.json`` and ``live/alerts.json``.

``closings.json`` and ``covered.json`` are written together by one ingest run and
carry the same ``generated_at`` and :class:`~snowlight.schemas.directory.DirectoryStamp`
(:func:`check_live_pair`). The site shows a school as open only when it is in a
``covered.json`` range, has no row in ``closings.json``, and both files match.

``closings.json`` is the one file that grows with a storm, so it is laid out for
size: one group per local day, stating the day once, and inside each group one
column per field instead of one array per school. School indexes are written as
gaps from the previous index, times as minutes before ``generated_at``, and the
delay and dismissal times only for the rows that can have them. A day with
schools 4, 5 and 8 closed, delayed and remote reads::

    {"day": "2027-01-12", "gaps": [4, 0, 2], "statuses": [0, 1, 2],
     "announced": [125, 3, null], "reasons": [0, 1, null],
     "shifts": [120], "clocks": [null]}

30,000 schools with a row for today and for tomorrow fit in the 400 KB gzip budget:
about 300 KB with every status, reason and time drawn at random, and about 375 KB
when every row is a delay or dismissal with a random shift and clock time
(``tests/schemas/test_schema_wire_size.py``). Only a file built to defeat
compression, with shifts and clocks spread evenly over their whole ranges on
every row, goes past it.
:class:`Closing` is the decoded row; :meth:`ClosingsFile.encode` and
:meth:`ClosingsFile.closings` convert between the two.

``alerts.json`` is written by ``snowlight alerts`` (:mod:`snowlight.weather.publish`)
and keeps that command's camelCase keys (``asOf``, ``generatedAt``) and its
``schema`` version key.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import accumulate, combinations
from typing import Annotated, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from snowlight.schemas.base import SCREENED, PublishedModel, screen_text
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.scalars import (
    Latitude,
    LocalDate,
    Longitude,
    MinuteOfDay,
    MinutesAgo,
    SchemaVersion,
    SchoolGap,
    SchoolIndex,
    ShiftMinutes,
    UtcInstant,
    minute_of,
    minutes_ago,
)
from snowlight.schemas.vocab import SHIFTED, AlertLevel, Hazard, Reason, Severity, Status

# The directory holds contiguous-US schools only, and every contiguous-US time zone
# is 4 (EDT) to 8 (PST) hours behind UTC. So at any moment the local todays and
# tomorrows of all schools span two dates, or three between 04:00 and 08:00 UTC,
# while midnight crosses the country; each school has two of them.
_EAST_BEHIND_UTC = timedelta(hours=4)
_WEST_BEHIND_UTC = timedelta(hours=8)
_DAY = timedelta(days=1)
MAX_DAYS = 3


def local_days(generated_at: datetime) -> tuple[date, date]:
    """Return the first and last local day that is today or tomorrow somewhere at a moment.

    The first is the local today in the far west, the last the local tomorrow in
    the far east.
    """
    return (generated_at - _WEST_BEHIND_UTC).date(), (generated_at - _EAST_BEHIND_UTC).date() + _DAY


@dataclass(frozen=True, slots=True)
class Closing:
    """One school's weather status on one local day: a decoded row of closings.json.

    ``announced_at`` is the start of the UTC minute the status was first posted, or
    None when the listing gave no time. ``shift_minutes`` (how late a delayed day
    starts, how early a dismissal comes) and ``clock_minute`` (the stated opening
    or dismissal time, local minutes after midnight) are None unless the listing
    states them, and always None for closed and remote days.
    """

    school: int
    day: date
    status: Status
    announced_at: datetime | None
    reason: Reason | None
    shift_minutes: int | None = None
    clock_minute: int | None = None


class ClosingsDay(PublishedModel):
    """Every school with a weather status on one local day, as parallel columns.

    Row i is gaps[i], statuses[i], announced[i] and reasons[i]; rows are in school
    order. shifts and clocks hold one entry for each delayed or early-dismissal
    row, in row order: the k-th entry belongs to the k-th such row.
    """

    day: LocalDate
    gaps: Annotated[
        tuple[SchoolGap, ...],
        Field(min_length=1, description="Each row's school, as a gap from the previous row's."),
    ]
    statuses: Annotated[tuple[Status, ...], Field(description="Each row's status.")]
    announced: Annotated[
        tuple[MinutesAgo | None, ...],
        Field(
            description=(
                "When each row's status was first posted, in minutes before generated_at; "
                "null when the listing gave no time."
            )
        ),
    ]
    reasons: Annotated[
        tuple[Reason | None, ...],
        Field(description="The weather each row names; null when none was named."),
    ]
    shifts: Annotated[
        tuple[ShiftMinutes | None, ...],
        Field(
            description=(
                "For each delayed or early-dismissal row, how late the day starts or how "
                "early it ends; null unless the listing states it."
            )
        ),
    ]
    clocks: Annotated[
        tuple[MinuteOfDay | None, ...],
        Field(
            description=(
                "For each delayed or early-dismissal row, the stated opening or dismissal "
                "time; null unless the listing states it."
            )
        ),
    ]

    @model_validator(mode="after")
    def _check(self) -> Self:
        rows = len(self.gaps)
        for name, column in (
            ("statuses", self.statuses),
            ("announced", self.announced),
            ("reasons", self.reasons),
        ):
            if len(column) != rows:
                raise ValueError(f"{self.day}: {rows} gaps but {len(column)} {name}")
        shifted = sum(status in SHIFTED for status in self.statuses)
        for name, column in (("shifts", self.shifts), ("clocks", self.clocks)):
            if len(column) != shifted:
                raise ValueError(
                    f"{self.day}: {shifted} delays and early dismissals but {len(column)} {name}"
                )
        return self

    def schools(self) -> tuple[int, ...]:
        """Return the school index of every row, in row order."""
        indexes = accumulate(self.gaps, lambda previous, gap: previous + 1 + gap, initial=-1)
        return tuple(indexes)[1:]

    def last_school(self) -> int:
        """Return the highest school index in the day."""
        return sum(self.gaps) + len(self.gaps) - 1


class ClosingsFile(PublishedModel):
    """live/closings.json: every school closed, delayed, remote or dismissing early for weather.

    One group per local day, in date order; each school has a row on at most two
    of them, its local today and tomorrow. A school with no row has no weather
    status on file; whether it is open is known only where live/covered.json says so.
    """

    schema_version: SchemaVersion
    generated_at: UtcInstant
    directory: DirectoryStamp
    days: Annotated[
        tuple[ClosingsDay, ...],
        Field(
            max_length=MAX_DAYS,
            description=(
                "The local days with a status, sorted. Each is today or tomorrow somewhere "
                "in the contiguous US at generated_at: two dates, or three between 04:00 "
                "and 08:00 UTC."
            ),
        ),
    ]

    @model_validator(mode="after")
    def _check(self) -> Self:
        first, last = local_days(self.generated_at)
        previous: date | None = None
        for position, group in enumerate(self.days):
            where = f"days[{position}]"
            if previous is not None and group.day <= previous:
                raise ValueError(f"{where}: days must be sorted and unique")
            previous = group.day
            if group.day < first:
                raise ValueError(f"{where}: {group.day} is over everywhere at generated_at")
            if group.day > last:
                raise ValueError(f"{where}: {group.day} is not today or tomorrow anywhere yet")
            if group.last_school() >= self.directory.schools:
                raise ValueError(f"{where}: school {group.last_school()} is not in the directory")
        for early, late in combinations(self.days, 2):
            if late.day - early.day > _DAY:
                shared = set(early.schools()).intersection(late.schools())
                if shared:
                    raise ValueError(
                        f"school {min(shared)} has rows on {early.day} and {late.day}; "
                        "a school has rows only for its today and tomorrow"
                    )
        return self

    def closings(self) -> list[Closing]:
        """Return every row decoded, by day, then school."""
        decoded: list[Closing] = []
        for group in self.days:
            times = iter(zip(group.shifts, group.clocks, strict=True))
            for school, status, ago, reason in zip(
                group.schools(), group.statuses, group.announced, group.reasons, strict=True
            ):
                shift, clock = next(times) if status in SHIFTED else (None, None)
                decoded.append(
                    Closing(
                        school=school,
                        day=group.day,
                        status=status,
                        announced_at=None if ago is None else minute_of(self.generated_at, ago),
                        reason=reason,
                        shift_minutes=shift,
                        clock_minute=clock,
                    )
                )
        return decoded

    @classmethod
    def encode(
        cls,
        closings: Iterable[Closing],
        *,
        generated_at: datetime,
        directory: DirectoryStamp,
    ) -> Self:
        """Build the file from decoded rows, in any order.

        ``announced_at`` keeps its minute; seconds are dropped.

        Raises:
            ValueError: two rows share a school and day, a closed or remote row has
                times, a row was announced after ``generated_at``, or the result
                breaks a rule of the file (a pydantic ``ValidationError``).
        """
        by_day: dict[date, dict[int, Closing]] = {}
        for closing in closings:
            if closing.status not in SHIFTED and (
                closing.shift_minutes is not None or closing.clock_minute is not None
            ):
                raise ValueError(f"school {closing.school}: only delays and dismissals have times")
            same_day = by_day.setdefault(closing.day, {})
            if closing.school in same_day:
                raise ValueError(f"school {closing.school} has two rows for {closing.day}")
            same_day[closing.school] = closing
        days = []
        for day in sorted(by_day):
            rows = [by_day[day][school] for school in sorted(by_day[day])]
            schools = [row.school for row in rows]
            shifted = [row for row in rows if row.status in SHIFTED]
            days.append(
                {
                    "day": day,
                    "gaps": tuple(
                        school - previous - 1
                        for previous, school in zip([-1, *schools], schools, strict=False)
                    ),
                    "statuses": tuple(row.status for row in rows),
                    "announced": tuple(
                        None
                        if row.announced_at is None
                        else minutes_ago(generated_at, row.announced_at)
                        for row in rows
                    ),
                    "reasons": tuple(row.reason for row in rows),
                    "shifts": tuple(row.shift_minutes for row in shifted),
                    "clocks": tuple(row.clock_minute for row in shifted),
                }
            )
        return cls.model_validate(
            {
                "schema_version": 1,
                "generated_at": generated_at,
                "directory": directory,
                "days": tuple(days),
            }
        )


type SchoolRange = Annotated[
    tuple[
        Annotated[SchoolIndex, Field(title="first")],
        Annotated[SchoolIndex, Field(title="last")],
    ],
    Field(description="An inclusive run of school indexes: [first, last]."),
]


class CoveredFile(PublishedModel):
    """live/covered.json: the schools whose closings were checked live at generated_at.

    Ranges are sorted, do not overlap and do not touch, so each set of schools has
    exactly one encoding. Only these schools can be shown as open.
    """

    schema_version: SchemaVersion
    generated_at: UtcInstant
    directory: DirectoryStamp
    ranges: tuple[SchoolRange, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        previous_last = -2
        for position, (first, last) in enumerate(self.ranges):
            where = f"ranges[{position}]"
            if first > last:
                raise ValueError(f"{where}: first {first} is after last {last}")
            if first <= previous_last + 1:
                raise ValueError(f"{where}: ranges must be sorted, apart and not touching")
            previous_last = last
        if previous_last >= self.directory.schools:
            raise ValueError(f"school {previous_last} is not in the directory")
        return self

    def covers(self, school: int) -> bool:
        """Return whether ``school`` is in one of the ranges."""
        low, high = 0, len(self.ranges)
        while low < high:
            middle = (low + high) // 2
            first, last = self.ranges[middle]
            if school < first:
                high = middle
            elif school > last:
                low = middle + 1
            else:
                return True
        return False

    def count(self) -> int:
        """Return how many schools the ranges cover."""
        return sum(last - first + 1 for first, last in self.ranges)


def ranges_from_indices(indices: Iterable[int]) -> tuple[tuple[int, int], ...]:
    """Return the canonical inclusive runs for a set of school indexes."""
    runs: list[tuple[int, int]] = []
    for index in sorted(set(indices)):
        if runs and index == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return tuple(runs)


def check_live_pair(closings: ClosingsFile, covered: CoveredFile) -> None:
    """Raise ValueError unless the two files come from the same run and directory."""
    if closings.generated_at != covered.generated_at:
        raise ValueError("closings.json and covered.json have different generated_at")
    if closings.directory != covered.directory:
        raise ValueError("closings.json and covered.json index different directories")


# Alerts --------------------------------------------------------------------------------

_BBOX_SLACK = 1e-6  # the bbox is rounded to the coordinates' own grid


def _closed_ring(ring: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    if ring[0] != ring[-1]:
        raise ValueError("a ring must end where it starts")
    return ring


type Position = Annotated[
    tuple[
        Annotated[Longitude, Field(title="lon")],
        Annotated[Latitude, Field(title="lat")],
    ],
    Field(description="[longitude, latitude] in degrees."),
]

type Ring = Annotated[
    tuple[Position, ...],
    Field(min_length=4, description="A closed ring: four or more positions, last = first."),
    AfterValidator(_closed_ring),
]

type Polygon = Annotated[
    tuple[Ring, ...],
    Field(min_length=1, description="An exterior ring (counter-clockwise), then its holes."),
]

type BBox = Annotated[
    tuple[
        Annotated[Longitude, Field(title="west")],
        Annotated[Latitude, Field(title="south")],
        Annotated[Longitude, Field(title="east")],
        Annotated[Latitude, Field(title="north")],
    ],
    Field(description="[west, south, east, north] of every polygon, in degrees."),
]

type AlertId = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{12}$"),
    Field(description="12 hex digits, the same for the same member alerts from run to run."),
]

type AlertEvent = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][a-z]+(?: [A-Z][a-z]+){1,5}$", max_length=60),
    AfterValidator(screen_text),
    SCREENED,
    Field(description="The alert type, such as Winter Storm Warning."),
]


class Alert(PublishedModel):
    """One weather alert area; alerts with the same event, severity, onset and end are merged."""

    id: AlertId
    event: AlertEvent
    hazard: Hazard
    level: AlertLevel
    severity: Severity
    onset: UtcInstant
    ends: UtcInstant | None = Field(description="When it ends; null until further notice.")
    bbox: BBox
    polygons: Annotated[tuple[Polygon, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.ends is not None and self.ends < self.onset:
            raise ValueError(f"alert {self.id} ends before its onset")
        west, south, east, north = self.bbox
        if west > east or south > north:
            raise ValueError(f"alert {self.id}: bbox is inverted")
        lons = [lon for polygon in self.polygons for ring in polygon for lon, _ in ring]
        lats = [lat for polygon in self.polygons for ring in polygon for _, lat in ring]
        edges = ((west, min(lons)), (south, min(lats)), (east, max(lons)), (north, max(lats)))
        if any(not math.isclose(edge, extent, abs_tol=_BBOX_SLACK) for edge, extent in edges):
            raise ValueError(f"alert {self.id}: bbox does not fit the polygons")
        return self


class AlertsFile(PublishedModel):
    """live/alerts.json: today's weather alerts that bear on schools, simplified for the map."""

    schema_version: SchemaVersion = Field(alias="schema")
    as_of: UtcInstant | None = Field(
        alias="asOf", description="When the alert feed itself was generated."
    )
    generated_at: UtcInstant = Field(alias="generatedAt")
    alerts: tuple[Alert, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.as_of is not None and self.as_of > self.generated_at:
            raise ValueError("asOf is after generatedAt")
        ids = [alert.id for alert in self.alerts]
        if len(set(ids)) != len(ids):
            raise ValueError("alert ids must be unique")
        return self
