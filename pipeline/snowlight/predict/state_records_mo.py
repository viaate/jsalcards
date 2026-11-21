"""Missouri's school calendar file (records-mo, edition 1; docs/predict.md, "Past records").

Missouri's education department sent its school calendar data on request: one workbook with
every day each public district and charter (an LEA) lost to the weather, every day it taught at
home (Alternative Methods of Instruction, AMI) and every make-up day, dated, for the school
years 2017, 2018, 2019, 2025 and 2026 (sheet ``All other years``), and yearly hour totals per
building for 2020 to 2024 (sheet ``2020-2024``, no dates). It is a received file: no URL, pinned
by size and SHA-256 in ``config/state-records.yaml`` (form ``mo_calendar``), read only from
``--files``, never committed. **This changes no number**: what it gives is two derived files,
committed under ``pipeline/data/records/mo/`` and pinned (lead ruling LR-6):

* ``mo-days-ed1.csv``: ``leaid,date,call,scope,weather``, one row per mapped LEA and dated
  district day with a row: call ``C`` closed, ``H`` school at home (AMI), ``S`` a short day
  (school met part of the day), ``M`` a make-up day (school held), ``P`` some schools only, ``N``
  no call (building rows at too few schools), ``U`` unknown (the LEA has no open school in the
  pinned directory); scope ``W`` a district-wide row, ``B`` building rows, ``U`` none to read;
  ``weather`` 1 when a weather day row is among its rows (the open-day rule's reporting test
  reads it), else 0.
* ``mo-counts-ed1.csv``: ``leaid,school_year,weather_full_hours,weather_partial_hours,ami_hours,
  makeup_hours`` for the 2020 to 2024 years: counts only, never spread into dates (``-100`` is
  the file's placeholder and stays as written; a reader takes it as missing).

**What each kind means** (the file and the department's own rules): an *Actual Weather Day* is
a scheduled day lost to the weather (0 hours attended: closed; more than 0: a short day, never a
late start); an *Actual Weather Make-up Day* is a day added to make up hours, so school was held
and it is never a closing; an *AMI Day* is school at home (the call ``remote``). Rows with a
*Half Day Indicator* ``A`` or ``P`` are the morning or afternoon session of a half-day pre-K or
kindergarten program, not a short day: they are left out of the roll-up.

**The roll-up** (one district day at a time): a district-wide row decides (closed, at home, short
or make-up); with building rows only, the LEA's *deciding schools* decide by the label rule's
shares (``config/predict.yaml``): deciding = its open schools of the pinned CCD 2024-25 school
directory that are not charter schools (all of them for a charter LEA, as ``serve.eligible``
does); no school at ``no_school_share`` or more of them is closed (or at home when no weather row
of a deciding school had 0 hours), no school or short at that share is short, at most
``open_max_share`` is no call (a make-up when a deciding school held one), between is ``P``.

**Ids, never by name.** The file's district code, zero filled to six digits, is the NCES
``ST_LEAID`` after ``MO-``: the config's ``ids`` table writes each code's LEAID out once, from
the pinned CCD 2024-25 school directory (a second pinned file of this state, read for the ids
and the deciding schools only); a build whose directory map differs from ``ids`` is refused.
Codes in ``unmapped`` (charters with no school in that directory) are listed, never matched.

Codes, ids, counts and dates only: no district or building name, no building code and no hours
by day leave this module. Its lines may reach a public log, so they hold counts only, never a
code next to a date.
"""

import csv
import hashlib
import io
import re
import zipfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Final, Literal

from snowlight.sources.nces.xlsx import XlsxFormatError, iter_rows, sheet_names

type MoKind = Literal["W", "M", "A"]
type MoCall = Literal["closed", "remote", "short", "makeup", "some", "none", "unknown"]
type MoScope = Literal["whole", "share", "nodeciding"]

KIND_OF: Final[Mapping[str, MoKind]] = {
    "Actual Weather Day": "W",
    "Actual Weather Make-up Day": "M",
    "AMI Day": "A",
}
"""The file's ``RECORD_INDICATOR`` to its kind."""
SHEETS: Final = ("All other years", "2020-2024")
DATED_HEADER: Final = (
    "School Year",
    "District Code",
    "District Name",
    "FK_CH_SCHOOL_CODE",
    "Building Name",
    "Begining Grade",
    "Ending Grade",
    "Half Day Indicator",
    "DAY",
    "HOURS ATTENDED",
    "RECORD_INDICATOR",
)
"""Sheet 1's header, exactly (the file's own spelling)."""
YEARLY_HEADER: Final = (
    "Year",
    "District Code",
    "District Name",
    "SCHOOL_CODE",
    "Building Name",
    "BEGIN_GRADE",
    "END_GRADE",
    "Half Day Indicator",
    "ACTUAL_WEATHER_FULL_DAYS",
    "ACUTAL_WEATHER_FULL_HOURS",
    "ACTUAL_WEATHER_PARTIAL_DAYS",
    "ACTUAL_WEATHER_PARTIAL_HOURS",
    "ALTERNATIVE_METHOD_INSTRUCTION_HOURS",
    "ACTUAL_STD_MAKEUP_DAYS",
    "ACTUAL_STD_MAKEUP_HOURS",
    "ACTUAL_NONSTD_MAKEUP_DAYS",
    "ACTUAL_NONSTD_MAKEUP_HOURS",
)
"""Sheet 2's header, exactly."""
EXCEL_EPOCH: Final = date(1899, 12, 30)
MAX_HOURS: Final = 12.0
CODE_DIGITS: Final = 6
BUILDING_DIGITS: Final = 4
CCD_MEMBER: Final = "ccd_sch_029_2425_w_1a_073025.csv"
NOT_OPEN: Final = frozenset({"Closed", "Inactive", "Future"})
"""CCD ``SY_STATUS_TEXT`` values of a school that is not open."""
CALL_LETTER: Final[Mapping[MoCall, str]] = {
    "closed": "C",
    "remote": "H",
    "short": "S",
    "makeup": "M",
    "some": "P",
    "none": "N",
    "unknown": "U",
}
"""Each call's letter in ``mo-days-ed1.csv``."""
SCOPE_LETTER: Final[Mapping[MoScope, str]] = {"whole": "W", "share": "B", "nodeciding": "U"}
DAYS_HEADER: Final = "leaid,date,call,scope,weather"
COUNTS_HEADER: Final = (
    "leaid,school_year,weather_full_hours,weather_partial_hours,ami_hours,makeup_hours"
)
DAYS_FILE: Final = "mo-days-ed1.csv"
COUNTS_FILE: Final = "mo-counts-ed1.csv"


class MoCalendarError(ValueError):
    """The file is not in the shape this reader understands (counts and codes only)."""


@dataclass(frozen=True, slots=True)
class DatedRow:
    """One row of sheet 1 (no name, no grade span)."""

    year: str
    code: str
    building: str
    """The building code, ``""`` for a district-wide row."""
    day: date
    kind: MoKind
    half: str
    """``""``, ``A`` or ``P`` (a half-day pre-K or kindergarten session)."""
    hours: float


@dataclass(frozen=True, slots=True)
class YearlyRow:
    """One row of sheet 2: a building's (or the district's) hours of one school year."""

    year: str
    code: str
    building: str
    full_hours: str
    partial_hours: str
    ami_hours: str
    std_makeup_hours: str
    nonstd_makeup_hours: str


@dataclass(frozen=True, slots=True)
class Calendar:
    """The file read, with what the parse check counted from the cells."""

    dated: tuple[DatedRow, ...]
    yearly: tuple[YearlyRow, ...]
    cells: Mapping[tuple[str, MoKind], int]
    """Sheet 1's rows per school year and kind, counted from the cells as read."""
    spans: Mapping[tuple[str, MoKind], tuple[date, date]]
    """Each school year and kind's first and last date."""
    names: int
    """District codes of sheet 1 (a count; the names are never kept)."""
    spelled_twice: int
    """Sheet 1 codes with more than one spelling of the district's name (a count)."""


def _cell(row: Sequence[str | None], index: int) -> str:
    return (row[index] if index < len(row) else None) or ""


def _code(text: str) -> str:
    code = text.strip().zfill(CODE_DIGITS)
    if not re.fullmatch(rf"\d{{{CODE_DIGITS}}}", code):
        raise MoCalendarError("a district code that is not six digits")
    return code


def _header(row: Sequence[str | None], want: Sequence[str], sheet: str) -> None:
    if tuple((c or "").strip() for c in row) != tuple(want):
        raise MoCalendarError(f"sheet {sheet!r}: not the pinned header")


def read_calendar(data: bytes) -> Calendar:
    """The file's two sheets, checked: the pinned sheet names and headers, every code six
    digits, every building code digits or blank, every date a whole Excel serial, every kind
    one of the three, every half-day code blank, ``A`` or ``P``, every hours cell 0 to 12. Each
    school year and kind is counted from the cells as read and again from the rows kept, and
    the two must agree.

    Raises:
        MoCalendarError: a sheet, header or cell that does not read (said without its text).
    """
    try:
        if tuple(sheet_names(data)) != SHEETS:
            raise MoCalendarError("not the pinned sheets")
        sheet1 = iter_rows(data, 0)
        _header(next(sheet1), DATED_HEADER, SHEETS[0])
        dated: list[DatedRow] = []
        cells: Counter[tuple[str, MoKind]] = Counter()
        spans: dict[tuple[str, MoKind], tuple[date, date]] = {}
        spellings: dict[str, set[str]] = defaultdict(set)
        for row in sheet1:
            year = _cell(row, 0).strip()
            kind = KIND_OF.get(_cell(row, 10).strip())
            if not re.fullmatch(r"\d{4}", year) or kind is None:
                raise MoCalendarError("a dated row with no school year or kind")
            cells[year, kind] += 1
            code = _code(_cell(row, 1))
            spellings[code].add(_cell(row, 2))
            building = _cell(row, 3).strip()
            if building and not building.isdigit():
                raise MoCalendarError("a building code that is not digits")
            serial = float(_cell(row, 8))
            if serial != int(serial):
                raise MoCalendarError("a date that is not a whole day")
            day = EXCEL_EPOCH + timedelta(days=int(serial))
            half = _cell(row, 7).strip()
            if half not in {"", "A", "P"}:
                raise MoCalendarError("a half-day code that is not A or P")
            hours = float(_cell(row, 9) or 0)
            if not 0 <= hours <= MAX_HOURS:
                raise MoCalendarError("an hours cell outside 0 to 12")
            low, high = spans.get((year, kind), (day, day))
            spans[year, kind] = (min(low, day), max(high, day))
            dated.append(DatedRow(year, code, building, day, kind, half, hours))
        sheet2 = iter_rows(data, 1)
        _header(next(sheet2), YEARLY_HEADER, SHEETS[1])
        yearly = [
            YearlyRow(
                _cell(row, 0).strip(),
                _code(_cell(row, 1)),
                _cell(row, 3).strip(),
                *(_cell(row, i) or "0" for i in (9, 11, 12, 14, 16)),
            )
            for row in sheet2
        ]
    except (XlsxFormatError, ValueError, StopIteration, zipfile.BadZipFile) as error:
        if isinstance(error, MoCalendarError):
            raise
        raise MoCalendarError(f"the file does not read: {type(error).__name__}") from error
    back = Counter((r.year, r.kind) for r in dated)
    if back != cells or len(dated) != sum(cells.values()):
        raise MoCalendarError("the rows kept do not count as the cells")
    return Calendar(
        tuple(dated),
        tuple(yearly),
        dict(cells),
        spans,
        len(spellings),
        sum(len(v) > 1 for v in spellings.values()),
    )


# --- the pinned directory ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Schools:
    """What the pinned CCD 2024-25 school directory says of Missouri's LEAs."""

    leaids: Mapping[str, frozenset[str]]
    """Each code's LEAIDs (by ``ST_LEAID`` ``MO-<code>``)."""
    known: Mapping[str, frozenset[str]]
    """Each code's building codes, open or not."""
    deciding: Mapping[str, frozenset[str]]
    """Each code's deciding building codes: its open schools that are not charter schools, or
    all its open schools when every one is a charter school (``serve.eligible``)."""
    charter: frozenset[str]
    """LEAIDs with a charter school."""


def read_schools(data: bytes) -> Schools:
    """Missouri's rows of the CCD 2024-25 school directory zip (``ST_SCHID``
    ``MO-<code>-<building><code>``).

    Raises:
        MoCalendarError: the zip or a Missouri school id does not read.
    """
    leaids: dict[str, set[str]] = defaultdict(set)
    known: dict[str, set[str]] = defaultdict(set)
    open_all: dict[str, set[str]] = defaultdict(set)
    not_charter: dict[str, set[str]] = defaultdict(set)
    charter: set[str] = set()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as book, book.open(CCD_MEMBER) as member:
            for row in csv.DictReader(io.TextIOWrapper(member, encoding="latin-1")):
                if not row["ST_LEAID"].startswith("MO-"):
                    continue
                code = row["ST_LEAID"][3:]
                leaids[code].add(row["LEAID"])
                if row["CHARTER_TEXT"] == "Yes":
                    charter.add(row["LEAID"])
                parts = row["ST_SCHID"].split("-")
                if (
                    len(parts) != 3  # noqa: PLR2004 - MO, code, building + code
                    or parts[1] != code
                    or parts[2][BUILDING_DIGITS:] != code
                ):
                    raise MoCalendarError("a Missouri school id that does not read")
                building = parts[2][:BUILDING_DIGITS]
                known[code].add(building)
                if row["SY_STATUS_TEXT"] in NOT_OPEN:
                    continue
                open_all[code].add(building)
                if row["CHARTER_TEXT"] != "Yes":
                    not_charter[code].add(building)
    except (KeyError, zipfile.BadZipFile, UnicodeDecodeError) as error:
        raise MoCalendarError(f"the directory does not read: {type(error).__name__}") from error
    return Schools(
        {c: frozenset(v) for c, v in leaids.items()},
        {c: frozenset(v) for c, v in known.items()},
        {c: frozenset(not_charter[c] or v) for c, v in open_all.items()},
        frozenset(charter),
    )


def id_map(schools: Schools) -> dict[str, str]:
    """Each code with exactly one LEAID (the id rule).

    Raises:
        MoCalendarError: a LEAID with two codes.
    """
    found = {c: next(iter(v)) for c, v in schools.leaids.items() if len(v) == 1}
    if len(set(found.values())) != len(found):
        raise MoCalendarError("a LEAID with two codes")
    return found


# --- the roll-up --------------------------------------------------------------------------------


type Status = Literal["no", "part", "mk"]


def _status(kind: MoKind, hours: float) -> Status:
    if kind == "A" or (kind == "W" and hours == 0):
        return "no"
    return "part" if kind == "W" else "mk"


@dataclass(slots=True)
class RollUp:
    """Each (code, day)'s call and how it was decided."""

    calls: dict[tuple[str, date], tuple[MoCall, MoScope]] = field(default_factory=dict)
    years: dict[tuple[str, date], str] = field(default_factory=dict)
    weather: set[tuple[str, date]] = field(default_factory=set)
    """District days with a weather day row among their rows."""
    left_half: int = 0
    """Rows of a half-day program, left out."""


def _wide(items: Sequence[DatedRow]) -> MoCall:
    statuses = {_status(r.kind, r.hours) for r in items}
    if "no" in statuses:
        remote = any(r.kind == "A" for r in items) and not any(
            r.kind == "W" and r.hours == 0 for r in items
        )
        return "remote" if remote else "closed"
    return "short" if "part" in statuses else "makeup"


def _by_buildings(
    items: Sequence[DatedRow], deciding: frozenset[str], no_share: float, open_share: float
) -> MoCall:
    per: dict[str, set[Status]] = defaultdict(set)
    for r in items:
        per[r.building].add(_status(r.kind, r.hours))
    no = {b for b, v in per.items() if "no" in v and b in deciding}
    part = {b for b, v in per.items() if "part" in v and "no" not in v and b in deciding}
    made = {b for b, v in per.items() if v == {"mk"} and b in deciding}
    if len(no) / len(deciding) >= no_share:
        weather = any(r.kind == "W" and r.hours == 0 and r.building in no for r in items)
        return "closed" if weather else "remote"
    if len(no | part) / len(deciding) >= no_share:
        return "short"
    if len(no | part) / len(deciding) <= open_share:
        return "makeup" if made else "none"
    return "some"


def roll_up(calendar: Calendar, schools: Schools, no_share: float, open_share: float) -> RollUp:
    """Each code's district days (see the module): ``none`` when building rows decide no
    call, ``unknown`` when the code has no open school in the directory."""
    found = RollUp()
    grouped: dict[tuple[str, date], list[DatedRow]] = defaultdict(list)
    for r in calendar.dated:
        if r.half:
            found.left_half += 1
            continue
        grouped[r.code, r.day].append(r)
        found.years[r.code, r.day] = r.year
        if r.kind == "W":
            found.weather.add((r.code, r.day))
    for key, items in grouped.items():
        wide = [r for r in items if not r.building]
        if wide:
            found.calls[key] = (_wide(wide), "whole")
            continue
        deciding = schools.deciding.get(key[0], frozenset())
        if not deciding:
            found.calls[key] = ("unknown", "nodeciding")
            continue
        found.calls[key] = (_by_buildings(items, deciding, no_share, open_share), "share")
    return found


def days_file(rolled: RollUp, ids: Mapping[str, str]) -> bytes:
    """``mo-days-ed1.csv``: every mapped code's district day with a row, sorted."""
    rows = sorted(
        f"{ids[code]},{day.isoformat()},{CALL_LETTER[call]},{SCOPE_LETTER[scope]},"
        f"{int((code, day) in rolled.weather)}"
        for (code, day), (call, scope) in rolled.calls.items()
        if code in ids
    )
    return (DAYS_HEADER + "\n" + "".join(r + "\n" for r in rows)).encode()


def _g(text: str) -> str:
    return f"{float(text):g}"


def counts_file(calendar: Calendar, ids: Mapping[str, str]) -> bytes:
    """``mo-counts-ed1.csv``: each mapped code's sheet 2 hours per year: the district-wide row
    when it has one, else each column's largest building value; make-up hours are the standard
    and the non-standard ones together. Values stay as written (``-100`` included)."""
    found: dict[tuple[str, str], tuple[float, float, float, float]] = {}
    wide: set[tuple[str, str]] = set()
    for r in calendar.yearly:
        if r.code not in ids:
            continue
        key = (ids[r.code], r.year)
        values = (
            float(r.full_hours),
            float(r.partial_hours),
            float(r.ami_hours),
            float(r.std_makeup_hours) + float(r.nonstd_makeup_hours),
        )
        if not r.building:
            found[key] = values
            wide.add(key)
        elif key not in wide:
            old = found.get(key, (0.0, 0.0, 0.0, 0.0))
            found[key] = (
                max(old[0], values[0]),
                max(old[1], values[1]),
                max(old[2], values[2]),
                max(old[3], values[3]),
            )
    rows = [
        f"{leaid},{year},{a:g},{b:g},{c:g},{d:g}"
        for (leaid, year), (a, b, c, d) in sorted(found.items())
    ]
    return (COUNTS_HEADER + "\n" + "".join(r + "\n" for r in rows)).encode()


@dataclass(frozen=True, slots=True)
class Derived:
    """The derived files by name, and the counts said of them."""

    files: Mapping[str, bytes]
    lines: tuple[str, ...]
    calendar: Calendar
    schools: Schools
    rolled: RollUp


def build(
    data: bytes,
    directory: bytes,
    ids: Mapping[str, str],
    unmapped: Mapping[str, str],
    shares: tuple[float, float],
) -> Derived:
    """The derived files from the file's and the directory's checked bytes.

    Raises:
        MoCalendarError: the file or the directory does not read; the directory's id map is
            not the config's ``ids``; a file code in neither ``ids`` nor ``unmapped``.
    """
    calendar = read_calendar(data)
    schools = read_schools(directory)
    found = id_map(schools)
    codes = {r.code for r in calendar.dated} | {r.code for r in calendar.yearly}
    if any(found.get(c) != u for c, u in ids.items()) or any(
        c in found and c not in ids for c in codes
    ):
        raise MoCalendarError("the directory's id map is not the config's ids")
    stray = sorted(codes - set(ids) - set(unmapped))
    if stray:
        raise MoCalendarError(f"{len(stray)} codes in neither ids nor unmapped")
    rolled = roll_up(calendar, schools, *shares)
    files = {DAYS_FILE: days_file(rolled, ids), COUNTS_FILE: counts_file(calendar, ids)}
    by_call = Counter(call for call, _scope in rolled.calls.values())
    lines = (
        f"predict each-school past: mo: {len(calendar.dated)} dated rows, {len(calendar.yearly)}"
        f" yearly rows; {len(codes & set(ids))} of {len(codes)} codes mapped,"
        f" {len(codes & set(unmapped))} listed and not matched; {rolled.left_half} half-day"
        " program rows left out",
        f"predict each-school past: mo: {len(rolled.calls)} district days: "
        + ", ".join(f"{n} {call}" for call, n in sorted(by_call.items())),
        *(
            f"predict each-school past: mo: {name} {data.count(b'\n') - 1} rows,"
            f" {len(data)} B, SHA-256 {hashlib.sha256(data).hexdigest()[:12]}"
            for name, data in files.items()
        ),
    )
    return Derived(files, lines, calendar, schools, rolled)
