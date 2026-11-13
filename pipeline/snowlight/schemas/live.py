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

``live/season.json`` (:class:`SeasonFile`) counts each school's days of each status this
school year, from the final day timelines (:mod:`snowlight.live.season`).
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import accumulate, combinations, pairwise
from typing import Annotated, Final, Literal, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from snowlight.schemas.base import SCREENED, PublishedModel, screen_text
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.scalars import (
    INDEX_MAX,
    MINUTES_PER_DAY,
    ContentDigest,
    Count,
    Latitude,
    LocalDate,
    Longitude,
    MinuteOfDay,
    MinutesAgo,
    Probability,
    SchemaVersion,
    SchoolGap,
    SchoolIndex,
    SchoolYear,
    ShiftMinutes,
    UtcInstant,
    minute_of,
    minutes_ago,
    school_year_bounds,
)
from snowlight.schemas.vocab import (
    SHIFTED,
    AlertLevel,
    Detail,
    Hazard,
    Reason,
    Severity,
    Status,
)

REASON_CODE_MAX: Final = 255
"""The highest reason code a live file may hold. :class:`~snowlight.schemas.vocab.Reason`
names 0-7; a reader takes any code up to this one, so a file written by a newer (or a
reverted) pipeline never fails to read for a code this one does not name."""

WEATHER_CODES: Final = frozenset(int(reason) for reason in Reason)
"""The codes :class:`~snowlight.schemas.vocab.Reason` names today (0-7): the weather and a
power outage. :func:`as_dark` reads every other code as dark."""


def _named_reason(code: int) -> int:
    """A code :class:`~snowlight.schemas.vocab.Reason` names, as its member (so a file of
    known codes reads exactly as before); any other code as the plain number."""
    return Reason(code) if code in WEATHER_CODES else code


type ReasonCode = Annotated[
    int,
    Field(
        ge=0,
        le=REASON_CODE_MAX,
        description=(
            "The cause a status was posted for, as a Reason code: 0 winter storm, 1 ice, "
            "2 extreme cold, 3 flooding, 4 hurricane, 5 severe storms, 6 heat, 7 power "
            "outage. A reader takes any other code up to 255 as a stated cause it has no "
            "name for: it shows no words for it and never fails to read the file."
        ),
    ),
    AfterValidator(_named_reason),
]
"""A status's reason code as a live file holds it (closings, day timelines): the named
:class:`~snowlight.schemas.vocab.Reason` codes read as their members, any other code up to
:data:`REASON_CODE_MAX` as its number (ALL-CLOSINGS lane T, docs/live.md "Reasons")."""


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
    reason: ReasonCode | None
    shift_minutes: int | None = None
    clock_minute: int | None = None
    manual: bool = False
    """Whether the site's own team set it by hand (the admin's manual status)."""
    details: tuple[Detail, ...] = ()
    """The plain details its listings state beside the status (:mod:`snowlight.live.details`),
    in code order, each at most once; empty when they state none."""


type RowPosition = Annotated[int, Field(ge=0, le=INDEX_MAX)]
type DetailRow = Annotated[
    tuple[
        Annotated[RowPosition, Field(title="row")],
        Annotated[
            tuple[Detail, ...],
            Field(title="details", min_length=1, max_length=len(Detail)),
        ],
    ],
    Field(description="A row's position in its day and the details it states, ascending."),
]


class ClosingsDay(PublishedModel):
    """Every school with a weather status on one local day, as parallel columns.

    Row i is gaps[i], statuses[i], announced[i] and reasons[i]; rows are in school
    order. shifts and clocks hold one entry for each delayed or early-dismissal
    row, in row order: the k-th entry belongs to the k-th such row. manual lists the
    rows the site's own team set by hand, by position, and details the plain details
    of the rows that have some, by position.
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
        tuple[ReasonCode | None, ...],
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
    manual: Annotated[
        tuple[RowPosition, ...],
        Field(
            description=(
                "The rows the site's own team set by hand, as positions in this day's rows "
                "(0 is the first), ascending; empty when there are none."
            ),
        ),
    ] = ()
    """Always written; a file written before it existed reads as none."""
    details: Annotated[
        tuple[DetailRow, ...],
        Field(
            description=(
                "The plain details the listings state beside each row's status, for the rows "
                "that have some: [row position, [details]], rows ascending, details ascending; "
                "empty when no row has any."
            ),
        ),
    ] = ()
    """Always written; a file written before it existed reads as none."""

    @model_validator(mode="after")
    def _check(self) -> Self:
        rows = len(self.gaps)
        if any(b <= a for a, b in pairwise(self.manual)) or any(i >= rows for i in self.manual):
            raise ValueError(f"{self.day}: manual rows must be ascending positions of its rows")
        positions = [position for position, _ in self.details]
        if any(b <= a for a, b in pairwise(positions)) or any(i >= rows for i in positions):
            raise ValueError(f"{self.day}: detail rows must be ascending positions of its rows")
        if any(any(b <= a for a, b in pairwise(codes)) for _, codes in self.details):
            raise ValueError(f"{self.day}: a row's details must be ascending and distinct")
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
            manual = set(group.manual)
            details = dict(group.details)
            for position, (school, status, ago, reason) in enumerate(
                zip(group.schools(), group.statuses, group.announced, group.reasons, strict=True)
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
                        manual=position in manual,
                        details=details.get(position, ()),
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
                    "manual": tuple(i for i, row in enumerate(rows) if row.manual),
                    "details": tuple(
                        (i, tuple(sorted(set(row.details))))
                        for i, row in enumerate(rows)
                        if row.details
                    ),
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


# --- open statements (owner decision Q8, for the prediction model) ---------------------------


class OpenStatement(PublishedModel):
    """A school's explicit word that it runs as normal on a local day.

    It never lights the map. The prediction model reads it as "school is held that
    day": the chance of no school drops to near zero, leaving at most a small chance
    of an early dismissal.
    """

    school: SchoolIndex
    day: LocalDate
    kind: Literal["open"]
    at: UtcInstant = Field(description="When the statement was first seen.")
    confidence: Probability | None = Field(
        description="The status reader's confidence in the statement (0.9 or more), or null."
    )


class OpensFile(PublishedModel):
    """live/opens.json: the open statements in force, written beside live/closings.json.

    It carries the same generated_at and directory stamp as the closings file of the
    same publish. A school-day appears at most once, and never on a day that file
    shows a status for.
    """

    schema_version: SchemaVersion
    generated_at: UtcInstant
    directory: DirectoryStamp
    opens: Annotated[
        tuple[OpenStatement, ...],
        Field(description="Sorted by day, then school; one per school and day."),
    ]

    @model_validator(mode="after")
    def _check(self) -> Self:
        first, last = local_days(self.generated_at)
        keys = [(item.day, item.school) for item in self.opens]
        if keys != sorted(set(keys)):
            raise ValueError("opens must be sorted by day and school, one per school and day")
        for item in self.opens:
            if not first <= item.day <= last:
                raise ValueError(f"school {item.school}: {item.day} is not today or tomorrow")
            if item.school >= self.directory.schools:
                raise ValueError(f"school {item.school} is not in the directory")
            if item.at > self.generated_at:
                raise ValueError(f"school {item.school}: seen after generated_at")
        return self


# --- the day timeline (owner decisions on replays, 2026-10-14) --------------------------------

MAX_LEAD_MINUTES = 7 * MINUTES_PER_DAY
"""How long before its day a change may be shown: a status posted days ahead."""

type ChangeDetails = Annotated[
    tuple[
        Annotated[Annotated[int, Field(ge=0, le=INDEX_MAX)], Field(title="change")],
        Annotated[
            tuple[Detail, ...],
            Field(title="details", min_length=1, max_length=len(Detail)),
        ],
    ],
    Field(description="A change's position in the day and the details shown with it."),
]

type DayMinute = Annotated[
    int,
    Field(
        ge=-MAX_LEAD_MINUTES,
        lt=2 * MINUTES_PER_DAY,
        description=(
            "Minutes after the start of the day in the school's own zone: negative for a "
            "change before the day began (a closing announced the evening before)."
        ),
    ),
]


class DayTimeline(PublishedModel):
    """live/days/<day>.json: when each school's status for one local day changed.

    One run per school that showed a status for the day, in school order: ``counts[i]``
    changes for the i-th school, read in order from the flat columns. A change is the
    status the map showed from that minute on (``null``: none, the status was taken
    back), with its reason and, for a delay or an early dismissal, its shift and clock
    time (one entry in ``shifts`` and ``clocks`` per such change, in order), and the plain
    details shown with it (``details``, by change position, for the changes that have some).
    A day in progress has ``final`` false and grows; once the day is over everywhere it is
    written one last time with ``final`` true.
    """

    schema_version: SchemaVersion
    day: LocalDate
    generated_at: UtcInstant
    directory: DirectoryStamp
    content_sha256: Annotated[
        ContentDigest | None,
        Field(
            description=(
                "The content digest of the directory edition the school indexes were built "
                "from (two contents can share one stamp); null for an emptied file."
            )
        ),
    ]
    final: bool
    gaps: Annotated[
        tuple[SchoolGap, ...],
        Field(description="Each school, as a gap from the previous school's index."),
    ]
    counts: Annotated[
        tuple[Annotated[int, Field(ge=1, le=MINUTES_PER_DAY)], ...],
        Field(description="How many changes each school has."),
    ]
    minutes: tuple[DayMinute, ...]
    statuses: Annotated[
        tuple[Status | None, ...],
        Field(description="Each change's status; null when the status was taken back."),
    ]
    reasons: tuple[ReasonCode | None, ...]
    shifts: tuple[ShiftMinutes | None, ...]
    clocks: tuple[MinuteOfDay | None, ...]
    details: Annotated[
        tuple[ChangeDetails, ...],
        Field(
            description=(
                "The plain details shown with each change that has some: [change position, "
                "[details]], changes ascending, details ascending; empty when none has any."
            ),
        ),
    ] = ()
    """Always written; a file written before it existed reads as none."""

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(self.counts) != len(self.gaps):
            raise ValueError(f"{self.day}: {len(self.gaps)} schools but {len(self.counts)} counts")
        changes = sum(self.counts)
        lengths = {
            "minutes": len(self.minutes),
            "statuses": len(self.statuses),
            "reasons": len(self.reasons),
        }
        for name, length in lengths.items():
            if length != changes:
                raise ValueError(f"{self.day}: {changes} changes but {length} {name}")
        shifted = [status in SHIFTED for status in self.statuses]
        if not len(self.shifts) == len(self.clocks) == sum(shifted):
            raise ValueError(f"{self.day}: one shift and clock per delay or dismissal")
        positions = [position for position, _ in self.details]
        if any(b <= a for a, b in pairwise(positions)) or any(i >= changes for i in positions):
            raise ValueError(f"{self.day}: detail changes must be ascending positions of changes")
        if any(self.statuses[i] is None for i in positions):
            raise ValueError(f"{self.day}: a status taken back has no details")
        if any(any(b <= a for a, b in pairwise(codes)) for _, codes in self.details):
            raise ValueError(f"{self.day}: a change's details must be ascending and distinct")
        if self.gaps and self.schools()[-1] >= self.directory.schools:
            raise ValueError(f"{self.day}: a school is not in the directory")
        self._check_runs(shifted)
        return self

    def _check_runs(self, shifted: list[bool]) -> None:
        times = iter(zip(self.shifts, self.clocks, strict=True))
        said = dict(self.details)
        details = [
            (status, reason, *(next(times) if is_shifted else (None, None)), said.get(at, ()))
            for at, (status, reason, is_shifted) in enumerate(
                zip(self.statuses, self.reasons, shifted, strict=True)
            )
        ]
        start = 0
        for count in self.counts:
            run = range(start, start + count)
            if details[start][0] is None:
                raise ValueError(f"{self.day}: a school's first change must show a status")
            for here, after in pairwise(run):
                if self.minutes[after] < self.minutes[here]:
                    raise ValueError(f"{self.day}: a school's changes must be in time order")
                if details[after] == details[here]:
                    raise ValueError(f"{self.day}: a change must change something")
            if any(details[at][0] is None and details[at][1] is not None for at in run):
                raise ValueError(f"{self.day}: a status taken back has no reason")
            start += count

    def schools(self) -> tuple[int, ...]:
        """Each school's index, in order."""
        return tuple(index - 1 for index in accumulate(gap + 1 for gap in self.gaps))


def _unnamed(reasons: Iterable[int | None]) -> bool:
    return any(reason is not None and reason not in WEATHER_CODES for reason in reasons)


type _Change = tuple[int, Status | None, int | None, int | None, int | None, tuple[Detail, ...]]


def named_reason(code: int | None) -> Reason | None:
    """A reason code read through :func:`as_dark` (or :func:`as_dark_closings`), as its
    :class:`~snowlight.schemas.vocab.Reason`.

    Raises:
        ValueError: ``code`` is not a named code: the file was not read through ``as_dark``.
    """
    return None if code is None else Reason(code)


def as_dark(timeline: DayTimeline) -> DayTimeline:
    """``timeline`` read as the dark a status of an unnamed reason replaces.

    The one rule by which everything that teaches or serves the prediction, and the season
    counts, read a status whose reason is not a named
    :class:`~snowlight.schemas.vocab.Reason` code (0-7), a stated cause that is not the
    weather or a code this code does not know: exactly as the dark it replaces. Each such
    change becomes a taken-back change (no status, reason, shift, clock or details), then
    each school's run is collapsed again by the timeline's own rules (a leading taken-back
    change dropped, a change equal to the one before it dropped); a school with no change
    left drops out, and a day with none left is an empty timeline (the same file, no
    schools). A timeline whose changes all carry a named code (or none) comes back as is:
    on today's files this is the identity.
    """
    if not _unnamed(timeline.reasons):
        return timeline
    times = iter(zip(timeline.shifts, timeline.clocks, strict=True))
    said = dict(timeline.details)
    changes: list[_Change] = []
    for at, (minute, status, reason) in enumerate(
        zip(timeline.minutes, timeline.statuses, timeline.reasons, strict=True)
    ):
        shift, clock = next(times) if status in SHIFTED else (None, None)
        if reason is not None and reason not in WEATHER_CODES:
            changes.append((minute, None, None, None, None, ()))
        else:
            changes.append((minute, status, reason, shift, clock, said.get(at, ())))
    runs: list[tuple[int, list[_Change]]] = []
    start = 0
    for school, count in zip(timeline.schools(), timeline.counts, strict=True):
        run: list[_Change] = []
        for change in changes[start : start + count]:
            if (not run and change[1] is None) or (run and run[-1][1:] == change[1:]):
                continue
            run.append(change)
        start += count
        if run:
            runs.append((school, run))
    schools = [school for school, _ in runs]
    flat = [change for _, run in runs for change in run]
    shifted = [change for change in flat if change[1] in SHIFTED]
    return DayTimeline.model_validate(
        {
            "schema_version": timeline.schema_version,
            "day": timeline.day,
            "generated_at": timeline.generated_at,
            "directory": timeline.directory,
            "content_sha256": timeline.content_sha256,
            "final": timeline.final,
            "gaps": tuple(
                school - previous - 1
                for previous, school in zip([-1, *schools], schools, strict=False)
            ),
            "counts": tuple(len(run) for _, run in runs),
            "minutes": tuple(change[0] for change in flat),
            "statuses": tuple(change[1] for change in flat),
            "reasons": tuple(change[2] for change in flat),
            "shifts": tuple(change[3] for change in shifted),
            "clocks": tuple(change[4] for change in shifted),
            "details": tuple(
                (position, change[5]) for position, change in enumerate(flat) if change[5]
            ),
        }
    )


def as_dark_closings(closings: ClosingsFile) -> ClosingsFile:
    """``closings`` read as the dark a status of an unnamed reason replaces (:func:`as_dark`):
    every row whose reason is not a named :class:`~snowlight.schemas.vocab.Reason` code
    (0-7) is left out, the columns of its day kept in step, and a day left with no row is
    left out. A file whose rows all carry a named code (or none) comes back as is."""
    if not any(_unnamed(group.reasons) for group in closings.days):
        return closings
    return ClosingsFile.encode(
        (
            closing
            for closing in closings.closings()
            if closing.reason is None or closing.reason in WEATHER_CODES
        ),
        generated_at=closings.generated_at,
        directory=closings.directory,
    )


class DayEntry(PublishedModel):
    """One live day with a timeline."""

    day: LocalDate
    schools: Count = Field(description="How many schools showed a status that day.")
    final: bool


class DayIndex(PublishedModel):
    """live/days/index.json: the live days that have a timeline, newest first."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    days: tuple[DayEntry, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        days = [entry.day for entry in self.days]
        if days != sorted(set(days), reverse=True):
            raise ValueError("days must be unique, newest first")
        return self


SEASON_STATUSES: tuple[Status, ...] = (
    Status.CLOSED,
    Status.DELAYED,
    Status.REMOTE,
    Status.EARLY_DISMISSAL,
)
"""The order of :class:`SeasonFile`'s count columns, and of each :data:`SeasonRow`."""

type SeasonRow = tuple[int, int, int, int]
"""One school's days closed, delayed, remote and dismissed early (:data:`SEASON_STATUSES`)."""

type DayTally = Annotated[
    int,
    Field(ge=0, le=366, description="How many days of a school year one school had a status."),
]


class SeasonFile(PublishedModel):
    """live/season.json: each school's closed, delayed, remote and early-dismissal days this
    school year.

    Counted from the final day timelines (``live/days/<day>.json`` with ``final`` true) of
    every day from ``since`` through ``through``: each school is counted once a day, under
    the status its timeline ended the day on; a status taken back by then counts nowhere.
    One row per school with at least one such day, in school order: ``gaps`` as in
    closings.json, and ``closed[i]``, ``delayed[i]``, ``remote[i]`` and
    ``early_dismissal[i]`` are the i-th school's days.
    """

    schema_version: SchemaVersion
    season: SchoolYear
    since: LocalDate = Field(
        description=(
            "The first day counted: the school year's first day (July 1), or the later day "
            "counting began."
        )
    )
    through: LocalDate = Field(description="The last day counted, the last day over everywhere.")
    directory: DirectoryStamp
    content_sha256: Annotated[
        ContentDigest | None,
        Field(
            description=(
                "The content digest of the directory edition the school indexes point into "
                "(as the day timelines'); null for an emptied file."
            )
        ),
    ]
    gaps: Annotated[
        tuple[SchoolGap, ...],
        Field(description="Each school, as a gap from the previous school's index."),
    ]
    closed: tuple[DayTally, ...]
    delayed: tuple[DayTally, ...]
    remote: tuple[DayTally, ...]
    early_dismissal: tuple[DayTally, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        first, last = school_year_bounds(self.season)
        if not first <= self.since <= self.through <= last:
            raise ValueError(
                f"{self.since} to {self.through} is not a stretch of the {self.season} school year"
            )
        columns = (self.closed, self.delayed, self.remote, self.early_dismissal)
        if any(len(column) != len(self.gaps) for column in columns):
            raise ValueError(f"{len(self.gaps)} schools but count columns of other lengths")
        days = (self.through - self.since).days + 1
        for position, row in enumerate(zip(*columns, strict=True)):
            if sum(row) < 1:
                raise ValueError(f"row {position}: a school is listed only with a day counted")
            if sum(row) > days:
                raise ValueError(f"row {position}: more days counted than {days} days counted")
        if self.gaps and self.schools()[-1] >= self.directory.schools:
            raise ValueError(f"school {self.schools()[-1]} is not in the directory")
        if self.content_sha256 is None and self.gaps:
            raise ValueError("an emptied file lists no school")
        return self

    def schools(self) -> tuple[int, ...]:
        """Each school's index, in order."""
        return tuple(index - 1 for index in accumulate(gap + 1 for gap in self.gaps))

    def rows(self) -> dict[int, SeasonRow]:
        """Each listed school's counts, by its index (the decoded file)."""
        columns = (self.closed, self.delayed, self.remote, self.early_dismissal)
        return {
            school: (closed, delayed, remote, early)
            for school, closed, delayed, remote, early in zip(self.schools(), *columns, strict=True)
        }

    @classmethod
    def encode(  # noqa: PLR0913 - the year, its stretch, the directory and the rows
        cls,
        rows: Mapping[int, SeasonRow],
        *,
        season: str,
        since: date,
        through: date,
        directory: DirectoryStamp,
        content_sha256: str | None,
    ) -> "SeasonFile":
        """The file holding ``rows`` (counts by school index); a school with no day counted
        is left out."""
        listed = sorted(school for school, row in rows.items() if sum(row) > 0)
        gaps = [
            school - previous - 1 for previous, school in zip([-1, *listed], listed, strict=False)
        ]
        return cls.model_validate(
            {
                "schema_version": 1,
                "season": season,
                "since": since,
                "through": through,
                "directory": directory,
                "content_sha256": content_sha256,
                "gaps": tuple(gaps),
                "closed": tuple(rows[school][0] for school in listed),
                "delayed": tuple(rows[school][1] for school in listed),
                "remote": tuple(rows[school][2] for school in listed),
                "early_dismissal": tuple(rows[school][3] for school in listed),
            }
        )
