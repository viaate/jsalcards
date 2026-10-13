"""The rows and reads of the archive that can bear on one replay day.

A row can count for day ``D`` only when its capture falls in ``[D-2 12:00, D 12:00)``
local time in its schools' zone (:func:`snowlight.replays.gates.capture_window`).
The contiguous states run from UTC-4 (Eastern daylight time) to UTC-10 (Hawaii),
so :func:`widest_window` holds every zone's window and each row's own window is
checked later, in its own zone. (UTC-4, not UTC-5: a control day in March or
October is on daylight time in the East.)

:func:`snowlight.listed.evidence.load_rows` keeps a row's name, status, section
and places. A list often keeps more of a row's status in other fields (a
comment such as "AMI Day" beside "Closed Tuesday"), and its own posted time.
:func:`row_extras` reads those from the same ``rows.jsonl``, row for row, so
the reader sees the whole status (:func:`reader_text`) and a row posted days
before the capture can be told apart (:func:`posted_stamp`).
"""

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

from snowlight.listed.evidence import ListRow, LoadedRows, Read, utc_text

EAST: Final = timezone(timedelta(hours=-4))
"""The earliest offset a US local noon falls at (Eastern daylight time)."""
WEST: Final = timezone(timedelta(hours=-10))
"""The latest offset a US local noon falls at (Hawaii)."""
NOON: Final = time(12)
LEAD_DAYS: Final = 2
"""A dated row may be captured from noon two days before its day."""


def instant(text: str) -> datetime:
    """A ``YYYY-MM-DDTHH:MM:SSZ`` read time as an aware UTC datetime."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def widest_window(day: date) -> tuple[datetime, datetime]:
    """The UTC span that holds ``[D-2 12:00, D 12:00)`` local in every US zone."""
    start = datetime.combine(day - timedelta(days=LEAD_DAYS), NOON, tzinfo=EAST)
    end = datetime.combine(day, NOON, tzinfo=WEST)
    return start.astimezone(UTC), end.astimezone(UTC)


def _within(text: str, span: tuple[datetime, datetime]) -> bool:
    moment = instant(text)
    return span[0] <= moment < span[1]


def day_rows(loaded: LoadedRows, day: date) -> list[ListRow]:
    """The rows whose capture falls in ``day``'s widest window, in file order.

    ``loaded`` comes from :func:`snowlight.listed.evidence.load_rows`, which has
    already tied every row to its read and filled in its section and places.
    """
    span = widest_window(day)
    return [row for row in loaded.rows if _within(row.fetched_at, span)]


def populated_reads(loaded: LoadedRows, station: str) -> tuple[Read, ...]:
    """Every read of ``station`` that holds rows, in time order."""
    return tuple(
        sorted(
            (read for read in loaded.reads if read.source_id == station and read.rows > 0),
            key=lambda read: (read.fetched_at, read.variant, read.sha256),
        )
    )


def window_reads(loaded: LoadedRows, day: date) -> dict[str, tuple[Read, ...]]:
    """Each station's populated reads in ``day``'s widest window, in time order."""
    span = widest_window(day)
    found: dict[str, list[Read]] = defaultdict(list)
    for read in loaded.reads:
        if read.rows > 0 and _within(read.fetched_at, span):
            found[read.source_id].append(read)
    return {
        station: tuple(sorted(reads, key=lambda read: (read.fetched_at, read.variant, read.sha256)))
        for station, reads in sorted(found.items())
    }


def rows_by_read(rows: Iterable[ListRow]) -> Mapping[tuple[str, str], tuple[ListRow, ...]]:
    """Rows grouped by their read (source id, read time), each group in file order."""
    grouped: dict[tuple[str, str], list[ListRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.source_id, row.fetched_at)].append(row)
    return {key: tuple(items) for key, items in grouped.items()}


# --- what load_rows leaves out: comments and posted times --------------------------------------

DETAIL_FIELDS: Final = (
    "complete_status",
    "alt_status_text",
    "status_name2",
    "status_name3",
    "status2",
    "Status2",
    "status2_name1",
    "status2_name2",
    "status2_name3",
    "status_two_name_one",
    "comment",
    "comments",
    "Comments",
    "comments_line1",
    "comments_line2",
    "comments_line3",
    "details",
    "notes",
    "note",
    "message",
    "day_label",
)
"""The row fields, on any platform, that carry more of a row's status: comments, second status
lines and the day a list's tab names. Read in this order after the status itself."""
_WORD: Final = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class RowExtra:
    """What one archive row holds beyond what :class:`ListRow` keeps."""

    detail: str = ""
    """The row's other status words (:data:`DETAIL_FIELDS`), joined, minus repeats."""
    posted: str | None = None
    """The list's own posted or updated text for the row (or its page)."""
    posted_zone: str | None = None
    """The zone the list names for that text (``updated_zone``), if any."""
    page_stamp: bool = False
    """The stamp is the page's (``updated_scope`` ``page``): every row on the page was posted
    then or earlier, but a row may be older. It bounds a row's age (``STALE_POST``) and never
    says a row is recent (:func:`snowlight.replays.gates.relative_tomorrow`)."""


NO_EXTRA: Final = RowExtra()


def _texts(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                items = json.loads(text)
            except ValueError:
                return [text]
            return _texts(items) if isinstance(items, list) else [text]
        return [text] if text else []
    if isinstance(value, list):
        return [part for item in value for part in _texts(item)]
    return []


def detail_of(name: str, status: str, extra: Mapping[str, object]) -> str:
    """A row's other status words: each :data:`DETAIL_FIELDS` text that adds a word.

    A text whose words all appear in the name, the status or an earlier text is
    left out, so a field that repeats the status adds nothing.
    """
    seen = set(_WORD.findall(f"{name} {status}".casefold()))
    kept: list[str] = []
    for key in DETAIL_FIELDS:
        for text in _texts(extra.get(key)):
            words = set(_WORD.findall(text.casefold()))
            if not words or words <= seen:
                continue
            seen |= words
            kept.append(" ".join(text.split()))
    return ". ".join(kept)


def reader_text(status: str, detail: str) -> str:
    """The text the status reader is given: the status, then the row's other status words."""
    if not detail:
        return status
    head = status.rstrip(" .;,")
    return f"{head}. {detail}" if head else detail


def _rows_lines(path: Path) -> Iterator[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    yield item


def row_extras(rows_path: Path) -> dict[tuple[str, str], tuple[RowExtra, ...]]:
    """Each read's rows' :class:`RowExtra`, by (source id, read time), in file order.

    This is the order :func:`snowlight.listed.evidence.load_rows` keeps a read's
    rows in, so the n-th extra of a read belongs to its n-th row.
    """
    found: dict[tuple[str, str], list[RowExtra]] = defaultdict(list)
    for item in _rows_lines(rows_path):
        key = (str(item.get("source_id")), utc_text(str(item.get("fetched_at"))))
        raw_extra = item.get("raw_extra")
        extra = raw_extra if isinstance(raw_extra, dict) else {}
        status = item.get("raw_status")
        name = item.get("raw_name")
        posted = item.get("raw_updated_text")
        zone = extra.get("updated_zone")
        found[key].append(
            RowExtra(
                detail=detail_of(
                    name if isinstance(name, str) else "",
                    status if isinstance(status, str) else "",
                    extra,
                ),
                posted=posted.strip() if isinstance(posted, str) and posted.strip() else None,
                posted_zone=zone if isinstance(zone, str) and zone else None,
                page_stamp=extra.get("updated_scope") == "page",
            )
        )
    return {key: tuple(items) for key, items in found.items()}


# --- posted times -------------------------------------------------------------------------------

_MONTHS: Final = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_ABBREVIATIONS: Final = {
    "utc": 0,
    "gmt": 0,
    "est": -5,
    "edt": -4,
    "cst": -6,
    "cdt": -5,
    "mst": -7,
    "mdt": -6,
    "pst": -8,
    "pdt": -7,
    "akst": -9,
    "akdt": -8,
    "hst": -10,
}
_MONTH: Final = r"(?P<month>[a-z]{3,9})\.?"
_CLOCK: Final = r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::\d{2})?\s*(?P<half>[ap])\.?m\.?"
_ABBR: Final = r"(?:\s+(?P<abbr>[a-z]{3,4})\b)?"
_ABBR_NEXT: Final = r"\s+(?P<abbr>[a-z]{3,4})"
_STAMPS: Final = (
    # 1/7/2025 4:41:31 PM, 01/26/2026 12:45am, 02/15/2021 01:19:53 PM CST, 01/07/25 09:12:44 PM EST
    re.compile(
        rf"(?P<mon>\d{{1,2}})/(?P<day>\d{{1,2}})/(?P<year>\d{{4}}|\d{{2}}),?\s+{_CLOCK}{_ABBR}"
    ),
    # 12:10am on 2/23/2026, 10:41pm on 3/04/2015
    re.compile(rf"{_CLOCK}\s+on\s+(?P<mon>\d{{1,2}})/(?P<day>\d{{1,2}})/(?P<year>\d{{2,4}})"),
    # March 16, 2026 10:35 pm CDT
    re.compile(rf"{_MONTH}\s+(?P<day>\d{{1,2}}),\s+(?P<year>\d{{4}})\s+{_CLOCK}{_ABBR}"),
    # 9:41 AM CST January 16, 2024
    re.compile(rf"{_CLOCK}{_ABBR_NEXT}\s+{_MONTH}\s+(?P<day>\d{{1,2}}),\s+(?P<year>\d{{4}})"),
    # UPDATED MONDAY, JAN 26 AT 1:21 AM; Tue. Jan. 4 - 8:30 am (no year)
    re.compile(rf"{_MONTH}\s+(?P<day>\d{{1,2}})\s+(?:at|-)\s+{_CLOCK}{_ABBR}"),
    # Fri Apr 12 10:20:30 CDT 2024 (a 24-hour clock)
    re.compile(
        r"^[a-z]{3}\s+(?P<month>[a-z]{3})\s+(?P<day>\d{1,2})\s+(?P<hour>\d{2}):(?P<minute>\d{2})"
        r"(?::\d{2})?\s+(?P<abbr>[a-z]{3,4})\s+(?P<year>\d{4})$"
    ),
)
_DATE_ONLY: Final = re.compile(
    r"^(?:(?P<year>\d{4})-(?P<mon>\d{2})-(?P<day>\d{2})|"
    r"(?P<mon2>\d{1,2})/(?P<day2>\d{1,2})/(?P<year2>\d{4}))$"
)
_NUMERIC: Final = re.compile(
    r"^(?P<year>\d{4})-(?P<mon>\d{2})-(?P<day>\d{2})[ t](?P<hour>\d{2}):(?P<minute>\d{2})"
    r"(?::\d{2}(?:\.\d+)?)?(?P<offset>z|[+-]\d{2}:?\d{2})?$"
)
POSTED_SLACK: Final = timedelta(hours=1)
"""A posted time later than the capture by more than this is not believed."""


def _zone_of(abbr: str | None, named: str | None, zone: str) -> timezone | ZoneInfo:
    if abbr and abbr in _ABBREVIATIONS:
        return timezone(timedelta(hours=_ABBREVIATIONS[abbr]))
    if named and named.casefold() in _ABBREVIATIONS:
        return timezone(timedelta(hours=_ABBREVIATIONS[named.casefold()]))
    return ZoneInfo(zone)


def _hour(hour: int, half: str | None) -> int:
    if half is None:
        return hour
    return hour % 12 + (12 if half == "p" else 0)


def _numeric(text: str, named: str | None, zone: str) -> datetime | None:
    found = _NUMERIC.match(text)
    if found is None:
        return None
    parts = found.groupdict()
    offset = parts["offset"]
    when = datetime(
        int(parts["year"]),
        int(parts["mon"]),
        int(parts["day"]),
        int(parts["hour"]),
        int(parts["minute"]),
    )
    if offset is None:
        return when.replace(tzinfo=_zone_of(None, named, zone))
    if offset == "z":
        return when.replace(tzinfo=UTC)
    sign = -1 if offset[0] == "-" else 1
    digits = offset[1:].replace(":", "")
    span = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    return when.replace(tzinfo=timezone(sign * span))


def _worded(text: str, captured: datetime, named: str | None, zone: str) -> datetime | None:
    for pattern in _STAMPS:
        found = pattern.search(text)
        if found is None:
            continue
        parts = found.groupdict()
        month = parts.get("mon")
        number = int(month) if month else _MONTHS.get(str(parts.get("month")))
        if number is None:
            continue
        year_text = parts.get("year")
        tz = _zone_of(parts.get("abbr"), named, zone)
        local_year = captured.astimezone(tz).year
        year = int(year_text) if year_text else local_year
        if year < 100:  # noqa: PLR2004 - a two-digit year
            year += 2000
        try:
            when = datetime(
                year,
                number,
                int(parts["day"]),
                _hour(int(parts["hour"]), parts.get("half")),
                int(parts["minute"]),
                tzinfo=tz,
            )
        except ValueError:
            return None
        if not year_text and when > captured + timedelta(days=2):
            when = when.replace(year=year - 1)
        return when
    return None


@dataclass(frozen=True, slots=True)
class Posted:
    """When a list says a row was posted or updated."""

    at: datetime
    """The instant (UTC); for a stamp that gives a date only, noon of that date in the zone."""
    day: date
    """The stamp's local date."""
    date_only: bool = False
    """The stamp names a day and no time ("2025-01-07"): it is known to the day only."""


def _date_only(text: str, zone: str) -> Posted | None:
    found = _DATE_ONLY.match(text)
    if found is None:
        return None
    parts = found.groupdict()
    year, month, number = (
        (parts["year"], parts["mon"], parts["day"])
        if parts["year"]
        else (parts["year2"], parts["mon2"], parts["day2"])
    )
    try:
        day = date(int(year), int(month), int(number))
    except ValueError:
        return None
    noon = datetime.combine(day, NOON, tzinfo=ZoneInfo(zone)).astimezone(UTC)
    return Posted(at=noon, day=day, date_only=True)


def posted_stamp(
    text: str | None, captured: datetime, zone: str, named: str | None = None
) -> Posted | None:
    """When a list's posted or updated text says the row was posted, or ``None``.

    The text is read in ``named`` (the list's ``updated_zone``) or its own zone
    abbreviation, else in ``zone``. A text with no year takes the capture's year
    (the year before, when that would put it after the capture). A stamp later
    than the capture by more than :data:`POSTED_SLACK` is not believed; a stamp
    that names a date and no time (``2025-01-07``) is known to the day, and is
    not believed for a date after the capture's.
    """
    if not text:
        return None
    clean = " ".join(text.casefold().split())
    only = _date_only(clean, zone)
    if only is not None:
        if only.day > captured.astimezone(ZoneInfo(zone)).date():
            return None
        return only
    when = _numeric(clean, named, zone) or _worded(clean, captured, named, zone)
    if when is None or when > captured + POSTED_SLACK:
        return None
    return Posted(at=when.astimezone(UTC), day=when.astimezone(ZoneInfo(zone)).date())
