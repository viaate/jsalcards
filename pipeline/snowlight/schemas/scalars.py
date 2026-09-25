"""Scalar types shared by the published files.

Each is a named alias, so the JSON Schema export lists it once under ``$defs`` and
the generated TypeScript gets a type of the same name with the same description.

Times on the wire:

* :data:`UtcInstant` is text, ``YYYY-MM-DDTHH:MM:SSZ``: UTC, whole seconds, a
  literal ``Z``. Only that form is accepted, so a file parses back to exactly the
  value that was written.
* :data:`MinutesAgo` is a whole number of minutes before a file's ``generated_at``.
  It is used inside the compact columns of ``live/closings.json``, where 60,000
  ISO strings or 10-digit Unix times would cost far more than 1 to 4 digits.
* :data:`LocalDate` is text, ``YYYY-MM-DD``: a calendar day in the school's own
  time zone, with no time and no offset.
"""

import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    PlainSerializer,
    StringConstraints,
    WithJsonSchema,
)

from snowlight.schemas.base import EXACT_INT, SCREENED, exact_int, screen_text

UTC_INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
UTC_INSTANT_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
LOCAL_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
# Indexes stay below 2**32 - 1, which points.bin reserves for "no district".
INDEX_MAX = 0xFFFF_FFFE
COUNT_MAX = 0xFFFF_FFFE
MINUTES_PER_DAY = 1440
MAX_SHIFT_MINUTES = 720
SECONDS_PER_MINUTE = 60
# Two weeks: far more than any weather status is posted ahead of the day it is for,
# and small enough to catch seconds written where minutes belong.
MAX_MINUTES_AGO = 14 * MINUTES_PER_DAY
_INSTANT_RE = re.compile(UTC_INSTANT_PATTERN)
_DATE_RE = re.compile(LOCAL_DATE_PATTERN)


def _parse_instant(value: Any) -> Any:
    if isinstance(value, str):
        if not _INSTANT_RE.fullmatch(value):
            raise ValueError(f"expected YYYY-MM-DDTHH:MM:SSZ, got {value!r}")
        return datetime.strptime(value, UTC_INSTANT_FORMAT).replace(tzinfo=UTC)
    return value


def _require_utc_whole_seconds(value: datetime) -> datetime:
    offset = value.utcoffset()
    if offset is None:
        raise ValueError("a UTC instant needs a time zone; this datetime is naive")
    if offset != timedelta(0):
        raise ValueError(f"a UTC instant must have offset 0, not {offset}")
    if value.microsecond:
        raise ValueError("a UTC instant is whole seconds; drop the microseconds first")
    return value.astimezone(UTC)


def format_instant(value: datetime) -> str:
    """Format a UTC datetime as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return value.astimezone(UTC).strftime(UTC_INSTANT_FORMAT)


def _parse_date(value: Any) -> Any:
    if isinstance(value, datetime):
        raise ValueError("a local date is a calendar day, not a datetime")
    if isinstance(value, str):
        if not _DATE_RE.fullmatch(value):
            raise ValueError(f"expected YYYY-MM-DD, got {value!r}")
        return date.fromisoformat(value)
    return value


def _hundredths(value: float) -> float:
    if round(value, 2) != value:
        raise ValueError(f"a chance is given in hundredths, not {value!r}")
    return value


def _school_year(value: str) -> str:
    start, end = value.split("-")
    if int(end) != int(start) + 1:
        raise ValueError(f"a school year spans two consecutive years, not {value!r}")
    return value


type UtcInstant = Annotated[
    datetime,
    BeforeValidator(_parse_instant),
    AfterValidator(_require_utc_whole_seconds),
    PlainSerializer(format_instant, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "format": "date-time",
            "pattern": UTC_INSTANT_PATTERN,
            "description": "A moment in UTC, whole seconds: YYYY-MM-DDTHH:MM:SSZ.",
        }
    ),
]

type LocalDate = Annotated[
    date,
    BeforeValidator(_parse_date),
    WithJsonSchema(
        {
            "type": "string",
            "format": "date",
            "pattern": LOCAL_DATE_PATTERN,
            "description": "A calendar day in the school's own time zone: YYYY-MM-DD.",
        }
    ),
]

type SchemaVersion = Annotated[
    Literal[1],
    BeforeValidator(exact_int),
    EXACT_INT,
    Field(description="The file format's version. A reader refuses a file with any other."),
]

type MinutesAgo = Annotated[
    int,
    Field(
        ge=0,
        le=MAX_MINUTES_AGO,
        description=(
            "Whole minutes before the minute of generated_at: the moment is the start of "
            "the UTC minute that many minutes earlier, and 0 is generated_at's own minute."
        ),
    ),
]

type SchoolIndex = Annotated[
    int,
    Field(
        ge=0,
        le=INDEX_MAX,
        description="A school's position in schools/meta.json ids (and in points.bin).",
    ),
]

type SchoolGap = Annotated[
    int,
    Field(
        ge=0,
        le=INDEX_MAX,
        description=(
            "A school index written as its distance from the one before it: "
            "index = previous index + 1 + gap, and the first previous index is -1. "
            "So [4, 0, 2] is schools 4, 5 and 8."
        ),
    ),
]

type DistrictIndex = Annotated[
    int,
    Field(
        ge=0,
        le=INDEX_MAX,
        description="A district's position in schools/meta.json districts.ids.",
    ),
]

type Count = Annotated[int, Field(ge=0, le=COUNT_MAX, description="A whole number of things.")]

type Percent = Annotated[int, Field(ge=0, le=100, description="Whole percentage points.")]

type Probability = Annotated[
    float,
    Field(
        ge=0.0,
        le=1.0,
        description="A chance from 0 to 1, in hundredths (0.07, not 0.0734).",
    ),
    AfterValidator(_hundredths),
]

type MinuteOfDay = Annotated[
    int,
    Field(
        ge=0,
        lt=MINUTES_PER_DAY,
        description="A local wall-clock time as minutes after midnight (630 is 10:30).",
    ),
]

type ShiftMinutes = Annotated[
    int,
    Field(ge=1, le=MAX_SHIFT_MINUTES, description="A length of time in whole minutes."),
]

type Longitude = Annotated[
    float, Field(ge=-180.0, le=180.0, description="Degrees east of Greenwich (WGS 84).")
]

type Latitude = Annotated[
    float, Field(ge=-90.0, le=90.0, description="Degrees north of the equator (WGS 84).")
]

type Usps = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z]{2}$"),
    Field(description="Two-letter USPS state code (DC included)."),
]

type SchoolId = Annotated[
    str,
    StringConstraints(pattern=r"^(?:\d{12}|[0-9A-Z]{8})$"),
    Field(
        description=(
            "A school's federal id: 12 digits for a public school, "
            "8 letters or digits for a private one."
        )
    ),
]

type DistrictId = Annotated[
    str,
    StringConstraints(pattern=r"^\d{7}$"),
    Field(description="A school district's 7-digit federal id."),
]

type SchoolYear = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{4}$"),
    AfterValidator(_school_year),
    Field(description="A school year, July to June, as YYYY-YYYY (2026-2027)."),
]

type DirectoryName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200),
    AfterValidator(screen_text),
    SCREENED,
    Field(description="A school's or district's name as the directory spells it."),
]


def school_year_bounds(season: str) -> tuple[date, date]:
    """Return the first and last day (July 1, June 30) of a ``YYYY-YYYY`` school year."""
    start, end = season.split("-")
    return date(int(start), 7, 1), date(int(end), 6, 30)


def unix_seconds(moment: datetime) -> int:
    """Return an aware datetime as whole Unix seconds (fractions are dropped)."""
    if moment.utcoffset() is None:
        raise ValueError("unix_seconds needs an aware datetime")
    return int(moment.timestamp() // 1)


def minutes_ago(generated_at: datetime, moment: datetime) -> int:
    """Return ``moment`` as :data:`MinutesAgo` relative to ``generated_at``.

    Seconds are dropped from both first, so :func:`minute_of` gives back the start of
    ``moment``'s own minute.

    Raises:
        ValueError: ``moment`` is after ``generated_at``.
    """
    if moment > generated_at:
        raise ValueError(f"{format_instant(moment)} is after {format_instant(generated_at)}")
    return (
        unix_seconds(generated_at) // SECONDS_PER_MINUTE
        - unix_seconds(moment) // SECONDS_PER_MINUTE
    )


def minute_of(generated_at: datetime, ago: int) -> datetime:
    """Return the start of the UTC minute that :data:`MinutesAgo` ``ago`` names."""
    minute = unix_seconds(generated_at) // SECONDS_PER_MINUTE - ago
    return datetime.fromtimestamp(minute * SECONDS_PER_MINUTE, UTC)
