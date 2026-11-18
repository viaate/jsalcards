"""Public state records of past school days, joined to districts and kept in each district's
own record (each-school P2d; docs/predict.md, "Past records").

The owner's ruling: each district's own record (whether it tends to close early or hold out)
is the spine of the prediction. A state that publishes its districts' missed days gives the
record years the live map never saw. **This changes no number**: nothing that learns or
serves reads these rows (no pass, no refit, no published file). They are written to the
evidence store's ``record`` kind (append-only) and to the internal ``record.parquet`` and
``record-counts.parquet`` (:mod:`snowlight.predict.record`), as their own coarse kind,
``past_records`` (LR8: a page may say "seen live by us" or "from past records", never an
agency's name).

**What is read** (``config/state-records.yaml``, every file by its URL, fetch date, size,
SHA-256 and parser version; a file whose bytes differ from the pinned SHA-256 is refused,
never parsed: a changed file needs a reviewed pin). Kentucky (R1), from its Department of
Education's school calendar page, fetched free by plain GET:

* the **Amended Calendar Summary** of 2024-25 and of 2025-26 (``.xlsx``, one row per
  district): the dated weather days (code ``W``: days missed for the weather that were made
  up), the dated illness (``I``) and district-wide emergency (``D``) days, the count of
  at-home NTI days used (``N``, not dated), and the district's own calendar (its first and
  last student days and every dated day off);
* the **Five Year Weather Trend** (``.pdf``): each district's count of weather make-up days in
  each school year from 2020-21 to 2024-25.

**What is written.**

* :class:`~snowlight.predict.record.PastDay`, one per district and dated weather day: call
  ``closed``, cause ``weather``, ``closings_only`` true and ``source_complete`` false (an NTI
  day is not dated, and a weather day not made up is not listed, so a day the file does not
  list is not known open: spec section 5), scope ``whole`` (the district's own calendar),
  class ``unknown`` until a backfill or P2a2 fills it (LR14), never fit-usable. Its day-after
  flag comes from the district's own calendar in the same file: ``True`` when its previous
  scheduled school day is a listed day off school (``W``, ``I`` or ``D``), else ``None`` (that
  day may have been an undated NTI day).
* :class:`~snowlight.predict.record.YearCount`, one per district, school year and code: the
  weather days of 2020-21 to 2025-26 (the trend for 2020-21 to 2023-24, each summary for its
  own year), and the NTI, illness and emergency days of 2024-25 and 2025-26. Counts stay
  counts: never spread into dates (spec rule 9).

**The written map** (``codes`` in the config) maps the state's calendar codes to the record's:
``W`` to a dated closed row for the weather and a yearly count; ``N``, ``I`` and ``D`` to yearly
counts only in this piece. ``W`` counts the weather days a district made up (one not made up is
removed), and the state's weather code can carry a closing for another cause. The review
checks every ``W`` day outside December to mid-March, every ``W`` date held by three districts
or fewer, and every ``W`` day of the February 2025 illness wave (the config's comment says how).
The config's written ``not_weather`` list names each day found to be another cause: its row
keeps the code ``W`` but has cause ``named`` and is never a weather day (LR12). Its written
``unconfirmed`` list names each checked day the review could not tie to the weather: its row
keeps the code with cause ``any`` and is never a weather day either. The year's ``W`` count
stays the state's number and says how many of its days each list names (``not_weather``,
``unconfirmed``; ``None`` for the trend's undated years, which cannot be checked). A listed
exception the files do not list, or a day in both lists, refuses the files.

**Ids, never guessed.** A district is joined by the written id rule: the state's three-digit
district number is digits 7-9 of the NCES ``ST_LEAID`` (``KY-CCCddd000``), written out once as
the config's ``ids`` table (number to LEAID, from the CCD LEA directory file the config names).
A number in neither ``ids`` nor ``unmapped`` refuses the file; a number in ``unmapped`` (171
of 172 map: 606, the Model Laboratory School, has no LEA) is listed, never matched.

**Checks before anything is written** (each refuses the state's files, said by code):
every summary row's weather-day count equals its dated weather days; the trend's 2024-25 count
equals the 2024-25 summary's in every row; every date lies in the file's school year; every
weather day is a school day by the district's own calendar (one that is not is listed and not
written); no date is listed twice in one cell.

**Written once, by edition.** The record is append-only and each key is written once, so each
file's keys carry its reviewed ``edition`` (``past/<file id>/v<edition>/days``) and the
SHA-256 of each key's bytes is pinned (``written``): a build whose bytes differ from the pins
(a parser, model, map or exception drift) is refused and warned of, never written. A reviewed
change bumps the edition and its pins; the record reads only each file's newest edition.

**New York** (records-ny, edition 1) sent its Schedule A-8 state-aid forms of claim years
2011-12 to 2026-27 on request: 16 received files with no URL, pinned by size and SHA-256 and
read only from ``--files`` (never fetched, never stored: only their pins and the derived keys
leave the records folder). By the state's directions a district fills in the form only when its
schools fell short of the 180 days the state requires because of an extraordinary condition, or
an emergency was declared, so a row is the emergency closing days the district reported to the
state: never an open day, never known to be every closing of its year (that is not measured),
and never a sign that a district that did not file held out. Each dated slot is a
:class:`~snowlight.predict.record.PastDay` (call ``closed``, closings only, class ``unknown``,
never fit-usable) with the form's reason as its code (``WX`` the weather and the only weather
day, ``SOE`` a declared emergency of cause ``any``, six named causes, ``NONE`` a blank reason),
scope ``whole``, ``share`` (a building, its text never kept) or ``unknown`` read from the
building cell as a class of generic words (:func:`a8_scope`; a ``share`` of a district the
pinned directory lists with at most one open school reads ``unknown``), and a day-after flag
from the
same file's written days only. Each district, school year and code with a day is a
:class:`~snowlight.predict.record.YearCount`; a zero is never written (not filing is not zero
closings). Held, counted in the file's line and never written: a date outside the file's school
year (the claim year's year before), a weekend, a day that is not a school day by the default
calendar (``calendar.is_school_day``; the late-June days, lead ruling RN6), a code the id rule
does not map, and the same date twice in one row (one district-day; a repeat with another
reason or building class refuses the file, said by file id). The id rule: the form's six-digit
code is the first six digits of the 12-digit BEDS code NCES writes as ``NY-<BEDS>`` in
``ST_LEAID`` (a district's ends ``0000``, its digits 7-8 are not ``86``), so a code maps only
by the config's ``ids`` table. ``dated_public`` is false: a later published shard shows New
York only as yearly counts or plain lines.

Codes, ids, counts and dates only: no name, no URL and no file text leaves this module but in
the said lines (district numbers, counts and the unmapped row's number; for New York, whose
lines may reach a public log, counts, codes and file ids only, never a district code next to a
date).
"""

import argparse
import hashlib
import re
import sys
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Final, Literal, Self

import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from snowlight.predict.calendar import is_school_day, previous_school_day
from snowlight.predict.config import PIPELINE_ROOT
from snowlight.predict.record import (
    PAST_COUNTS,
    PAST_DAYS,
    Call,
    Cause,
    PastDay,
    RecordError,
    Scope,
    SourceKind,
    YearCount,
    lines_bytes,
    past_key,
)
from snowlight.sources.nces.xlsx import XlsxFormatError, iter_rows

PARSER_VERSION: Final = 1
"""The parsers' version: a file pinned with another is refused."""
STATE_RECORDS_PATH: Final = PIPELINE_ROOT / "config" / "state-records.yaml"
PAST_VERSION: Final = 1
"""The past rows' format version (:class:`~snowlight.predict.record.PastDay`)."""
COVID_YEARS: Final = frozenset({"2019-20", "2020-21"})
"""School years kept and flagged, never in a count fit (spec rule 9)."""
_ONE_DAY: Final = timedelta(days=1)
SATURDAY: Final = 5


class StateRecordError(ValueError):
    """A state file that must not be written (codes, numbers and counts only)."""


# --- the config -------------------------------------------------------------------------------


class StateFile(BaseModel):
    """One state file, pinned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z]{2}-[a-z0-9-]{1,40}$")
    """The file's id: the record's rows name it, never its URL."""
    form: Literal["ky_summary", "ky_trend", "ny_a8"]
    url: str | None = Field(default=None, pattern=r"^https://")
    """Where it is fetched by plain GET; ``None`` for a received file."""
    page: str | None = Field(default=None, pattern=r"^https://")
    """The agency page that links it (only with a ``url``)."""
    received: str | None = Field(default=None, pattern=r"^[a-z0-9-]{1,64}$")
    """A file the agency sent, by a plain label (no person, no request number): it has no
    URL, is read only from ``--files`` and is never fetched."""
    fetched: date
    """The date it was fetched, or for a received file the date it was received."""
    bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    years: tuple[str, ...] = Field(min_length=1)
    """The school years it holds (``2024-25``)."""
    parser: int = Field(ge=1)
    edition: int = Field(ge=1, le=9999)
    """Its rows' edition, in its record keys (``past/<id>/v<edition>/<kind>``): the record is
    append-only, so a reviewed change to its rows bumps this and writes new keys."""
    written: dict[Literal["days", "counts"], str] = Field(default_factory=dict)
    """The SHA-256 of each record key's bytes this edition writes (reviewed): a build whose
    bytes differ (a parser, model or map drift) is refused, never written."""

    @model_validator(mode="after")
    def _one_way(self) -> Self:
        """Exactly one of ``url`` and ``received``; ``page`` only with ``url``."""
        if (self.url is None) == (self.received is None):
            raise ValueError(f"{self.id}: exactly one of url and received")
        if self.page is not None and self.url is None:
            raise ValueError(f"{self.id}: a page only with a url")
        return self


class StateCode(BaseModel):
    """The written map of one of the state's calendar codes to the record's."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    """A short plain label for the code (Kentucky's: the state's own name for it)."""
    match: tuple[str, ...] = ()
    """The form's exact pick-list phrases that read as this code (New York's reasons; form
    words, public in the state's directions, never a district row)."""
    dated: bool
    """Its dated days become :class:`~snowlight.predict.record.PastDay` rows."""
    counted: bool
    """Its yearly count becomes a :class:`~snowlight.predict.record.YearCount`."""
    call: Call | None = None
    cause: Cause | None = None
    weather_day: bool = False
    day_off: Literal["weather", "named", "unknown"] | None = None
    """What a listed day of this code says of the next school day's day-after flags:
    ``weather`` (no school for the weather), ``named`` (no school for another named cause),
    ``unknown`` (no school, cause not said); ``None``: not a day off school (NTI)."""


class NotWeather(BaseModel):
    """A day the state lists under a weather code, written out by review. In the config's
    ``not_weather`` list it was a closing for another cause (checked against the district's own
    notice or local news): its row keeps the state's code but has cause ``named`` and is never a
    weather day (LR12). In its ``unconfirmed`` list the review found no weather closing for the
    district that day: its row keeps the code with cause ``any`` and is never a weather day
    either, until a later review ties it to the weather (a new edition)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: str = Field(pattern=r"^\d{3,6}$")
    """The state's district number (``id_digits`` digits)."""
    day: date
    code: str
    why: str
    """The cause, in plain words (no name of a person)."""
    checked: date


class StateRecords(BaseModel):
    """One state's files, codes and ids."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str = Field(pattern=r"^[a-z]{2}$")
    id_digits: int = Field(default=3, ge=3, le=6)
    """The digits of the state's district number (Kentucky 3, New York 6)."""
    dated_public: bool = False
    """Its dated rows may be published as dated rows (Kentucky's files are public pages). A
    state with ``False`` (New York's received forms) is published only as yearly counts or
    plain lines, never as dated day rows; publishing them needs this set on purpose."""
    complete: str
    """What the files can and cannot say (spec section 5), in words."""
    files: tuple[StateFile, ...] = Field(min_length=1)
    codes: dict[str, StateCode]
    ids: dict[str, str]
    """The state's district number to its LEAID (the written id rule)."""
    id_rule: str
    one_school: tuple[str, ...] = ()
    """Mapped LEAIDs the id rule's pinned directory lists with at most one open school, sorted:
    a building cell of such a district names its one school (or none), so it never says part of
    the district (see :func:`a8_scope`)."""
    unmapped: dict[str, str]
    """District numbers with no LEA, listed (with the state's name for them), never matched."""
    not_weather: tuple[NotWeather, ...] = ()
    """Days listed under a weather code that were not the weather (see :class:`NotWeather`)."""
    unconfirmed: tuple[NotWeather, ...] = ()
    """Days listed under a weather code that the review could not tie to the weather."""

    def other_cause(self, number: str, day: date, code: str) -> bool:
        """The written ``not_weather`` list names this listed day."""
        return any((n.number, n.day, n.code) == (number, day, code) for n in self.not_weather)

    def unsure(self, number: str, day: date, code: str) -> bool:
        """The written ``unconfirmed`` list names this listed day."""
        return any((n.number, n.day, n.code) == (number, day, code) for n in self.unconfirmed)


class StateRecordsConfig(BaseModel):
    """``config/state-records.yaml``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1)
    states: dict[str, StateRecords]


def _check_written(key: str, state: StateRecords) -> None:
    """Each written exception is a mapped district's day of a weather code, in one list once."""
    for name, entries in (
        ("not_weather", state.not_weather),
        ("unconfirmed", state.unconfirmed),
    ):
        for entry in entries:
            mapped = state.codes.get(entry.code)
            if mapped is None or not mapped.weather_day or entry.number not in state.ids:
                raise StateRecordError(
                    f"{key}: {name} {entry.number} {entry.day}: not a mapped weather day"
                )
    listed = [(n.number, n.day, n.code) for n in (*state.not_weather, *state.unconfirmed)]
    if len(set(listed)) != len(listed):
        raise StateRecordError(f"{key}: a day written twice in not_weather and unconfirmed")


def load(path: Path = STATE_RECORDS_PATH) -> StateRecordsConfig:
    """The config, checked: ids are numbers of the state's ``id_digits`` to 7-digit LEAIDs (and
    so are the unmapped and written numbers), no number both mapped and unmapped, no LEAID
    twice, no pick-list phrase of two codes, every file of the parser version."""
    found = StateRecordsConfig.model_validate(yaml.safe_load(path.read_text()))
    for key, state in found.states.items():
        if key != state.state:
            raise StateRecordError(f"{key}: names state {state.state}")
        digits = rf"\d{{{state.id_digits}}}"
        if any(
            not re.fullmatch(digits, n) or not re.fullmatch(r"\d{7}", u)
            for n, u in state.ids.items()
        ):
            raise StateRecordError(f"{key}: an id that is not a number to a LEAID")
        if any(
            not re.fullmatch(digits, n)
            for n in (
                *state.unmapped,
                *(e.number for e in (*state.not_weather, *state.unconfirmed)),
            )
        ):
            raise StateRecordError(f"{key}: a number that is not {state.id_digits} digits")
        phrases = [p for code in state.codes.values() for p in code.match]
        if len(set(phrases)) != len(phrases):
            raise StateRecordError(f"{key}: a pick-list phrase of two codes")
        if set(state.ids) & set(state.unmapped):
            raise StateRecordError(f"{key}: a number both mapped and unmapped")
        if len(set(state.ids.values())) != len(state.ids):
            raise StateRecordError(f"{key}: a LEAID mapped twice")
        if list(state.one_school) != sorted(set(state.one_school)) or not set(
            state.one_school
        ) <= set(state.ids.values()):
            raise StateRecordError(f"{key}: a one-school LEAID not mapped, twice or unsorted")
        for item in state.files:
            if item.parser != PARSER_VERSION:
                raise StateRecordError(f"{item.id}: pinned for parser {item.parser}")
            if set(item.written) != set(KINDS[item.form]) or any(
                not re.fullmatch(r"[0-9a-f]{64}", pin) for pin in item.written.values()
            ):
                raise StateRecordError(f"{item.id}: its written keys are not all pinned")
        _check_written(key, state)
        if len({item.id for item in state.files}) != len(state.files):
            raise StateRecordError(f"{key}: a file id twice")
    return found


# --- the PDF text reader ----------------------------------------------------------------------

_TOKEN: Final = re.compile(
    rb"\s*(?:(\()|(<)|(\[)|(\])|(/[^\s/\[\]()<>{}%]*)|([-+]?(?:\d+\.?\d*|\.\d+))"
    rb"|([A-Za-z'\"*][A-Za-z0-9'\"*]*)|(%[^\r\n]*)|(\{|\}))",
    re.S,
)
_ESCAPES: Final = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
_OBJECT: Final = re.compile(rb"(\d+) 0 obj(.*?)endobj", re.S)
_STREAM: Final = re.compile(rb"<<(.*?)>>\s*stream\r?\n", re.S)
_CONTENTS: Final = re.compile(rb"/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)")
_REF: Final = re.compile(rb"(\d+)\s+0\s+R")
_ROW_GAP: Final = 1.0
"""Text runs whose baselines are this close (in points) are one line of a table."""
_SPACE_KERN: Final = -200.0
"""A ``TJ`` adjustment at or below this (thousandths of an em) reads as a space."""
_OCTAL_DIGITS: Final = 3
_HEX_PAIR: Final = 2
_MATRIX: Final = 6
_BACKSLASH: Final = 0x5C
_OPEN: Final = 0x28
_CLOSE: Final = 0x29
_ZERO: Final = 0x30
_SEVEN: Final = 0x37


def _literal(data: bytes, start: int) -> tuple[bytes, int]:
    """A PDF literal string from just after its ``(``; its bytes and the index after it."""
    depth, out, i = 1, bytearray(), start
    while i < len(data):
        char = data[i]
        if char == _BACKSLASH:
            nxt = data[i + 1] if i + 1 < len(data) else 0
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
            elif _ZERO <= nxt <= _SEVEN:
                j, value = i + 1, 0
                while j < i + 1 + _OCTAL_DIGITS and j < len(data) and _ZERO <= data[j] <= _SEVEN:
                    value = value * 8 + data[j] - _ZERO
                    j += 1
                out.append(value & 0xFF)
                i = j
            elif nxt in {10, 13}:
                i += 2
            else:
                out.append(nxt)
                i += 2
            continue
        if char == _OPEN:
            depth += 1
        elif char == _CLOSE:
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
        out.append(char)
        i += 1
    raise StateRecordError("a PDF string does not end")


def text_runs(content: bytes) -> list[tuple[float, float, str]]:
    """Each shown text run of a page's content as ``(x, y, text)`` (the text line matrix's
    origin): ``Tm``, ``Td``, ``TD``, ``Tj`` and ``TJ`` (a WinAnsi simple font, as the trend's
    Calibri is). Enough for a table drawn one cell a run; not a general PDF reader."""
    i = 0
    operands: list[object] = []
    array: list[object] | None = None
    line = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    found: list[tuple[float, float, str]] = []
    while i < len(content):
        if content[i] in b" \t\r\n\f\x00":
            i += 1
            continue
        if content.startswith((b"<<", b">>"), i):
            i += 2
            continue
        match = _TOKEN.match(content, i)
        if match is None:
            i += 1
            continue
        i = match.end()
        target: list[object] = array if array is not None else operands
        if match.group(1):
            text, i = _literal(content, i)
            target.append(text)
        elif match.group(2):
            end = content.index(b">", i)
            digits = re.sub(rb"\s", b"", content[i:end])
            i = end + 1
            if len(digits) % _HEX_PAIR:
                digits += b"0"
            try:
                target.append(bytes.fromhex(digits.decode("ascii")))
            except ValueError as error:
                raise StateRecordError("a PDF hex string does not read") from error
        elif match.group(3):
            array = []
        elif match.group(4):
            operands.append(array)
            array = None
        elif match.group(6):
            target.append(float(match.group(6)))
        elif match.group(7):
            line = _operate(match.group(7), operands, line, found)
            operands = []
    return found


def _operate(
    op: bytes, operands: list[object], line: list[float], found: list[tuple[float, float, str]]
) -> list[float]:
    numbers = [x for x in operands if isinstance(x, float)]
    if op == b"BT":
        return [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    if op == b"Tm" and len(numbers) >= _MATRIX:
        return numbers[-_MATRIX:]
    if op in {b"Td", b"TD"} and len(numbers) >= _HEX_PAIR:
        tx, ty = numbers[-2:]
        a, b, c, d, e, f = line
        return [a, b, c, d, e + tx * a + ty * c, f + tx * b + ty * d]
    if op == b"Tj" and operands and isinstance(operands[-1], bytes):
        found.append((line[4], line[5], operands[-1].decode("cp1252", "replace")))
    elif op == b"TJ" and operands and isinstance(operands[-1], list):
        parts = [
            x.decode("cp1252", "replace")
            if isinstance(x, bytes)
            else (" " if isinstance(x, float) and x <= _SPACE_KERN else "")
            for x in operands[-1]
        ]
        found.append((line[4], line[5], "".join(parts)))
    return line


def pdf_lines(data: bytes) -> list[list[str]]:
    """Every page's text as lines of cells, top line first, cells left to right: a page's
    content streams joined in order, its runs grouped by baseline.

    Raises:
        StateRecordError: a content stream does not inflate, or a page names none.
    """
    objects = {int(num): body for num, body in _OBJECT.findall(data)}
    pages = [
        body
        for body in objects.values()
        if re.search(rb"/Type\s*/Page(?![s\w])", body) and _CONTENTS.search(body)
    ]
    if not pages:
        raise StateRecordError("the PDF names no page")
    lines: list[list[str]] = []
    for page in pages:
        refs = _CONTENTS.search(page)
        assert refs is not None  # noqa: S101 - filtered above
        content = b"\n".join(_stream(objects, int(ref)) for ref in _REF.findall(refs.group(1)))
        rows: list[tuple[float, list[tuple[float, str]]]] = []
        for x, y, text in sorted(text_runs(content), key=lambda run: (-run[1], run[0])):
            if rows and abs(rows[-1][0] - y) <= _ROW_GAP:
                rows[-1][1].append((x, text))
            else:
                rows.append((y, [(x, text)]))
        lines.extend([t.strip() for _, t in sorted(cells) if t.strip()] for _, cells in rows)
    return lines


def _stream(objects: Mapping[int, bytes], num: int) -> bytes:
    body = objects.get(num)
    match = None if body is None else _STREAM.search(body)
    if body is None or match is None:
        raise StateRecordError(f"PDF object {num} is not a stream")
    raw = body[match.end() :]
    raw = raw[: raw.rfind(b"endstream")]
    if b"/FlateDecode" not in match.group(1):
        return raw
    try:
        return zlib.decompressobj().decompress(raw)
    except zlib.error as error:
        raise StateRecordError(f"PDF object {num} does not inflate") from error


# --- Kentucky's files -------------------------------------------------------------------------

_SHORT_DATE: Final = re.compile(r"(\d{2})/(\d{2})/(\d{2})")
_LONG_DATE: Final = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_NUMBER: Final = re.compile(r"\d{3}")
_COUNT: Final = re.compile(r"\d+(?:\.0+)?")
_TREND_YEAR: Final = re.compile(r"(\d{4})-(\d{4})")

KY_DATED: Final[Mapping[str, str]] = {
    "W": "Weather Days",
    "I": "Illness Days",
    "D": "District Wide Disaster Days",
}
"""Each dated code and its column (its dates, ``MM/DD/YY, ...``)."""
KY_COUNTS: Final[Mapping[str, str]] = {
    "W": "Total Number of Weather Days",
    "I": "Total Number of Illness Days",
    "N": "Number of NTI Days Used",
}
"""Each counted code and its column. A ``W`` or ``I`` count must equal its dated days. ``D`` is
counted from its dated days: the file's "Total Number of District Wide Disaster Days" reads 0
in 11 of the 12 rows of the two files that list ``D`` days, so it is not their count."""
KY_OFF: Final = (
    "Professional Development Days",
    "Holiday Days",
    "Planning Days",
    "Fall Break Days",
    "Winter Break Days",
    "Spring Break Days",
    "Other Break Days",
)
"""The dated days with no school for students on the district's own calendar."""
KY_FIRST: Final = "Students First Day"
KY_LAST: Final = "Students Last Day"
KY_NUMBER: Final = "District Number"


@dataclass(frozen=True, slots=True)
class SummaryRow:
    """One district's row of an Amended Calendar Summary (numbers and dates only)."""

    number: str
    first: date
    last: date
    off: frozenset[date]
    """Its dated days with no school for students (breaks, holidays, planning, PD)."""
    dated: Mapping[str, tuple[date, ...]]
    """Each dated code's days, as listed."""
    counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class TrendRow:
    """One district's row of the Five Year Weather Trend."""

    number: str
    counts: Mapping[str, int]
    """Weather make-up days by school year (``2020-21``)."""


def _year_of(day: date) -> str:
    start = day.year if day.month >= 7 else day.year - 1  # noqa: PLR2004 - July
    return f"{start}-{(start + 1) % 100:02d}"


def _dates(cell: str | None, where: str) -> tuple[date, ...]:
    text = (cell or "").strip()
    if not text:
        return ()
    found: list[date] = []
    for token in (t.strip() for t in text.split(",")):
        match = _SHORT_DATE.fullmatch(token)
        if match is None:
            raise StateRecordError(f"{where}: a date that does not read")
        month, day, year = (int(x) for x in match.groups())
        try:
            found.append(date(2000 + year, month, day))
        except ValueError as error:
            raise StateRecordError(f"{where}: a date that does not read") from error
    return tuple(found)


def _long_date(cell: str | None, where: str) -> date:
    match = _LONG_DATE.fullmatch((cell or "").strip())
    if match is None:
        raise StateRecordError(f"{where}: a date that does not read")
    month, day, year = (int(x) for x in match.groups())
    return date(year, month, day)


def _count(cell: str | None, where: str) -> int:
    text = (cell or "0").strip() or "0"
    if not _COUNT.fullmatch(text):
        raise StateRecordError(f"{where}: a count that does not read")
    return int(float(text))


def read_summary(data: bytes, year: str) -> list[SummaryRow]:
    """An Amended Calendar Summary's district rows (every row whose first cell is a 3-digit
    district number). Columns are found by their header's first line, never by position.

    Raises:
        StateRecordError: a column is missing, a cell does not read, or a date is outside
            ``year``.
    """
    try:
        rows = list(iter_rows(data))
    except (XlsxFormatError, KeyError, ValueError) as error:
        raise StateRecordError(f"{year}: the workbook does not read") from error
    if not rows:
        raise StateRecordError(f"{year}: an empty workbook")
    header = {(cell or "").split("\n")[0].strip(): i for i, cell in enumerate(rows[0])}
    wanted = (KY_NUMBER, KY_FIRST, KY_LAST, *KY_DATED.values(), *KY_COUNTS.values(), *KY_OFF)
    missing = [name for name in wanted if name not in header]
    if missing:
        raise StateRecordError(f"{year}: {len(missing)} columns missing")

    def cell(row: Sequence[str | None], name: str) -> str | None:
        index = header[name]
        return row[index] if index < len(row) else None

    found: list[SummaryRow] = []
    for row in rows[1:]:
        number = (cell(row, KY_NUMBER) or "").strip()
        if not _NUMBER.fullmatch(number):
            continue
        where = f"{year} {number}"
        dated = {
            code: _dates(cell(row, name), f"{where} {code}") for code, name in KY_DATED.items()
        }
        off = frozenset(d for name in KY_OFF for d in _dates(cell(row, name), f"{where} off"))
        counts = {c: _count(cell(row, n), f"{where} {c}") for c, n in KY_COUNTS.items()}
        counts["D"] = len(dated["D"])
        found.append(
            SummaryRow(
                number=number,
                first=_long_date(cell(row, KY_FIRST), f"{where} first day"),
                last=_long_date(cell(row, KY_LAST), f"{where} last day"),
                off=off,
                dated=dated,
                counts=counts,
            )
        )
        for day in (*(d for days in dated.values() for d in days), *off):
            if _year_of(day) != year:
                raise StateRecordError(f"{where}: a date outside {year}")
    if len({r.number for r in found}) != len(found):
        raise StateRecordError(f"{year}: a district number twice")
    return found


def read_trend(data: bytes) -> list[TrendRow]:
    """The Five Year Weather Trend's district rows: a 3-digit number, the name, one count per
    school year of its header, and the "highest" column (left out: it is floored at 1 in rows
    whose years are all 0, so it is not the years' maximum).

    Raises:
        StateRecordError: the PDF or its header does not read, a row does not, or a number
            comes twice.
    """
    lines = pdf_lines(data)
    years: list[str] = []
    for cells in lines:
        found = [m.groups() for c in cells for m in [_TREND_YEAR.fullmatch(c)] if m]
        if found:
            years = [f"{a}-{int(b) % 100:02d}" for a, b in found]
            break
    if not years:
        raise StateRecordError("trend: no school years in its header")
    rows: list[TrendRow] = []
    for cells in lines:
        if not cells or not _NUMBER.fullmatch(cells[0]):
            continue
        counts = cells[-(len(years) + 1) : -1]
        if len(cells) < len(years) + 3 or not all(
            re.fullmatch(r"\d+", c) for c in cells[-(len(years) + 1) :]
        ):
            raise StateRecordError(f"trend {cells[0]}: a row that does not read")
        rows.append(TrendRow(cells[0], dict(zip(years, (int(c) for c in counts), strict=True))))
    if len({r.number for r in rows}) != len(rows):
        raise StateRecordError("trend: a district number twice")
    return rows


# --- the rows ---------------------------------------------------------------------------------


@dataclass(slots=True)
class Built:
    """A state's rows, by record key, and what was said of them."""

    keys: dict[str, bytes] = field(default_factory=dict)
    days: list[PastDay] = field(default_factory=list)
    counts: list[YearCount] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    dropped: list[tuple[str, date]] = field(default_factory=list)
    """Weather days that are not school days by the district's own calendar (number, day)."""


def school_day(row: SummaryRow, day: date) -> bool:
    """A scheduled student day on the district's own calendar: a weekday from its first to its
    last student day that is none of its dated days off."""
    return row.first <= day <= row.last and day.weekday() < SATURDAY and day not in row.off


def previous_day(row: SummaryRow, day: date) -> date | None:
    """The district's scheduled student day before ``day`` (``None``: ``day`` is its first)."""
    before = day - _ONE_DAY
    while before >= row.first:
        if school_day(row, before):
            return before
        before -= _ONE_DAY
    return None


def _after(row: SummaryRow, day: date, state: StateRecords) -> tuple[bool | None, bool | None]:
    """``(after, after_weather)`` of a dated day from the district's own calendar (a listed
    day the written ``not_weather`` list names is a day off for a named cause; one its
    ``unconfirmed`` list names is a day off of a cause not known)."""
    prior = previous_day(row, day)
    if prior is None:
        return None, None
    said = {
        "named"
        if state.other_cause(row.number, prior, c)
        else "unsure"
        if state.unsure(row.number, prior, c)
        else state.codes[c].day_off
        for c, days in row.dated.items()
        if prior in days and c in state.codes
    }
    said.discard(None)
    if not said:
        return None, None  # a school day held, or an undated at-home NTI day
    if "weather" in said:
        return True, True
    if said == {"named"}:
        return True, False
    return True, None


def _map(state: StateRecords, number: str, built: Built) -> str | None:
    if number in state.ids:
        return state.ids[number]
    if number in state.unmapped:
        if number not in built.unmapped:
            built.unmapped.append(number)
        return None
    raise StateRecordError(f"{state.state} {number}: a district number in neither ids nor unmapped")


def build_ky(state: StateRecords, files: Mapping[str, bytes]) -> Built:
    """Kentucky's rows from its pinned files' bytes (by file id), checked (see the module).

    Raises:
        StateRecordError: a file is missing, does not read, or fails a check.
    """
    built = Built()
    summaries: dict[str, tuple[StateFile, list[SummaryRow]]] = {}
    trends: list[tuple[StateFile, list[TrendRow]]] = []
    for item in state.files:
        if item.id not in files:
            raise StateRecordError(f"{item.id}: not read")
        if item.form == "ky_summary":
            (year,) = item.years
            summaries[year] = (item, read_summary(files[item.id], year))
        else:
            trends.append((item, read_trend(files[item.id])))
    for year, (item, listed) in sorted(summaries.items()):
        days, counts = _summary_rows(state, item, year, listed, built)
        built.keys[past_key(item.id, item.edition, PAST_DAYS)] = lines_bytes(days, item.id)
        built.keys[past_key(item.id, item.edition, PAST_COUNTS)] = lines_bytes(counts, item.id)
        built.days.extend(days)
        built.counts.extend(counts)
    for item, trend in trends:
        counts = _trend_counts(state, item, trend, summaries, built)
        built.keys[past_key(item.id, item.edition, PAST_COUNTS)] = lines_bytes(counts, item.id)
        built.counts.extend(counts)
    for list_name, written in (
        ("not_weather", state.not_weather),
        ("unconfirmed", state.unconfirmed),
    ):
        unused = [
            n
            for n in written
            if not any(
                n.day in row.dated.get(n.code, ())
                for _, rows in summaries.values()
                for row in rows
                if row.number == n.number
            )
        ]
        if unused:
            raise StateRecordError(
                f"{state.state}: {list_name} days the files do not list: "
                + ", ".join(f"{n.number} {n.day.isoformat()}" for n in unused)
            )
    if state.not_weather:
        built.lines.append(
            f"predict each-school past: {state.state}: {len(state.not_weather)} days listed under"
            f" a weather code were another cause (written list), kept with cause named and never"
            f" a weather day: "
            + ", ".join(f"{n.number} {n.day.isoformat()}" for n in state.not_weather)
        )
    if state.unconfirmed:
        built.lines.append(
            f"predict each-school past: {state.state}: {len(state.unconfirmed)} days listed under"
            f" a weather code the review could not tie to the weather (written list), kept with"
            f" cause any and never a weather day: "
            + ", ".join(f"{n.number} {n.day.isoformat()}" for n in state.unconfirmed)
        )
    if built.unmapped:
        built.lines.append(
            f"predict each-school past: {state.state}: district numbers with no LEA, listed and"
            f" not matched: {', '.join(sorted(built.unmapped))}"
        )
    return built


def _summary_rows(
    state: StateRecords, item: StateFile, year: str, rows: Sequence[SummaryRow], built: Built
) -> tuple[list[PastDay], list[YearCount]]:
    days: list[PastDay] = []
    counts: list[YearCount] = []
    for row in rows:
        for code, listed in row.dated.items():
            if len(set(listed)) != len(listed):
                raise StateRecordError(f"{item.id} {row.number}: a {code} date twice")
            if (
                code in state.codes
                and state.codes[code].counted
                and row.counts[code] != len(listed)
            ):
                raise StateRecordError(
                    f"{item.id} {row.number}: {row.counts[code]} {code} days counted,"
                    f" {len(listed)} dated"
                )
        unit = _map(state, row.number, built)
        if unit is None:
            continue
        for code, mapped in sorted(state.codes.items()):
            other = [d for d in row.dated.get(code, ()) if state.other_cause(row.number, d, code)]
            unsure = [d for d in row.dated.get(code, ()) if state.unsure(row.number, d, code)]
            if mapped.counted and code in row.counts:
                counts.append(
                    _year_count(
                        unit, year, code, row.counts[code], item, row, (len(other), len(unsure))
                    )
                )
            if not mapped.dated:
                continue
            for day in sorted(row.dated.get(code, ())):
                if not school_day(row, day):
                    built.dropped.append((row.number, day))
                    continue
                days.append(
                    _past_day(
                        unit,
                        day,
                        code,
                        mapped,
                        item,
                        *_after(row, day, state),
                        other=day in other,
                        unsure=day in unsure,
                    )
                )
    days.sort(key=lambda d: (d.day, d.unit))
    built.lines.append(_say_file(item, days, counts))
    return days, counts


def _year_count(  # noqa: PLR0913, PLR0917 - one count and where it was read
    unit: str,
    year: str,
    code: str,
    days: int,
    item: StateFile,
    row: SummaryRow | None,
    checked: tuple[int, int] | None,
) -> YearCount:
    """``checked``: ``(not_weather, unconfirmed)`` of a dated count; ``None`` for an undated one
    (the trend's years), which cannot be checked."""
    return YearCount(
        version=PAST_VERSION,
        unit=unit,
        year=year,
        code=code,
        days=days,
        not_weather=None if checked is None else checked[0],
        unconfirmed=None if checked is None else checked[1],
        source_kind=SourceKind.PAST_RECORDS,
        sources=(item.id,),
        covid=year in COVID_YEARS,
        disaster=None if row is None else bool(row.counts.get("D", 0)),
    )


def _past_day(  # noqa: PLR0913, PLR0917 - one dated day and its flags
    unit: str,
    day: date,
    code: str,
    mapped: StateCode,
    item: StateFile,
    after: bool | None,
    after_weather: bool | None,
    *,
    other: bool = False,
    unsure: bool = False,
) -> PastDay:
    """``other``: the written ``not_weather`` list names the day (cause named, never a weather
    day). ``unsure``: its ``unconfirmed`` list names it (cause any, never a weather day)."""
    if mapped.call is None or mapped.cause is None:
        raise StateRecordError(f"{item.id}: code {code} is dated with no call or cause")
    return PastDay(
        version=PAST_VERSION,
        day=day,
        unit=unit,
        weather=None,
        klass="unknown",
        after=after,
        after_weather=after_weather,
        situation=None,
        call=mapped.call,
        source_kind=SourceKind.PAST_RECORDS,
        source_complete=False,
        closings_only=True,
        scope=Scope.WHOLE,
        cause=Cause.NAMED if other else Cause.ANY if unsure else mapped.cause,
        weather_day=mapped.weather_day and not other and not unsure,
        fit_usable=False,
        reasons=(),
        tropical=None,
        sources=(item.id,),
        code=code,
    )


def _trend_counts(
    state: StateRecords,
    item: StateFile,
    rows: Sequence[TrendRow],
    summaries: Mapping[str, tuple[StateFile, list[SummaryRow]]],
    built: Built,
) -> list[YearCount]:
    """The trend's weather counts for its years no summary holds; the years a summary holds
    are checked against it (every row equal), and kept from the summary."""
    counts: list[YearCount] = []
    for year in item.years:
        if year not in summaries:
            continue
        theirs = {r.number: r.counts["W"] for r in summaries[year][1]}
        ours = {r.number: r.counts.get(year) for r in rows}
        same = sum(ours.get(n) == c for n, c in theirs.items())
        if same != len(theirs) or set(ours) != set(theirs):
            raise StateRecordError(
                f"{item.id}: {year} equals the summary in {same} of {len(theirs)} rows"
            )
        built.lines.append(
            f"predict each-school past: {item.id}: {year} equals the summary in {same} of"
            f" {len(theirs)} rows"
        )
    for row in rows:
        unit = _map(state, row.number, built)
        if unit is None:
            continue
        counts.extend(
            _year_count(unit, year, "W", row.counts[year], item, None, None)
            for year in item.years
            if year not in summaries
        )
    counts.sort(key=lambda c: (c.unit, c.year, c.code))
    built.lines.append(_say_file(item, [], counts))
    return counts


def _say_file(item: StateFile, days: Sequence[PastDay], counts: Sequence[YearCount]) -> str:
    unknown = sum(d.klass == "unknown" for d in days)
    after = sum(d.after is True for d in days)
    usable = sum(d.fit_usable for d in days)
    weather = sum(d.weather_day for d in days)
    by_code: dict[str, int] = {}
    other: dict[str, int] = {}
    unsure: dict[str, int] = {}
    for count in counts:
        by_code[count.code] = by_code.get(count.code, 0) + count.days
        if count.not_weather:
            other[count.code] = other.get(count.code, 0) + count.not_weather
        if count.unconfirmed:
            unsure[count.code] = unsure.get(count.code, 0) + count.unconfirmed
    totals = ", ".join(f"{code} {n}" for code, n in sorted(by_code.items())) or "none"
    not_weather = "".join(
        f", {n} {code} days not the weather" for code, n in sorted(other.items())
    ) + "".join(
        f", {n} {code} days not confirmed the weather" for code, n in sorted(unsure.items())
    )
    return (
        f"predict each-school past: {item.id}: {len(days)} dated rows over"
        f" {len({d.unit for d in days})} districts ({weather} weather days, {unknown} of class"
        f" unknown, {after} the day after a day off school, {usable} fit-usable); {len(counts)}"
        f" yearly counts ({totals} days{not_weather})"
    )


# --- New York's Schedule A-8 --------------------------------------------------------------------

NY_TITLE: Final = re.compile(r"Claim Year (\d{4})-(\d{4})")
NY_CODE: Final = "Beds Code"
"""The second header row's label of the district code column."""
NY_SEQ: Final = "SEQ:"
NY_MARKER: Final = "XXXXXX"
"""The one row allowed after the district rows."""
NY_HEADER_ROWS: Final = 4
"""The title, the Refkey row (with the code column's label), the column labels and the SEQ
row; the sheet's empty fifth row is not a row of the reader."""
_NY_NUMBER: Final = re.compile(r"\d{6}")
_NY_SERIAL: Final = re.compile(r"\d{5}")
_NY_SLOT: Final = re.compile(r"Sch A8:Extra Condition (?:Date(\d*)|(Reason|Building)-(\d+))")
_NY_TOTAL: Final = re.compile(r".*(?:Total Days-\d+|TotalDays)")
NY_DISTRICT: Final = "DISTRICT"
NY_WHOLE: Final = frozenset(
    {
        ("DISTRICT",),
        ("DISTRICTWIDE",),
        ("DISTRICT", "WIDE"),
        ("WHOLE", "DISTRICT"),
        ("ENTIRE", "DISTRICT"),
        ("WHOLE", "SCHOOL", "DISTRICT"),
        ("ENTIRE", "SCHOOL", "DISTRICT"),
        ("ALL",),
        ("ALL", "SCHOOLS"),
        ("ALL", "BUILDINGS"),
    }
)
"""The reviewed building-cell phrases that say the whole district (generic words only, never a
name), as words; a misspelled ``DISTRICT`` (one letter added, dropped, changed or swapped) reads
as ``DISTRICT``."""
NY_WHOLE_LEAD: Final = frozenset({"WHOLE", "ENTIRE"})
"""A cell whose first words are ``WHOLE`` or ``ENTIRE`` and ``DISTRICT`` (or ``SCHOOL
DISTRICT``) says the whole district when the words after them are a reason
(:data:`NY_REASON_WORDS`)."""
NY_DISTRICT_KIND: Final = frozenset({"CSD", "UFSD", "SD", "CCSD"})
"""A district-kind word: a cell that ends in one (or in ``SCHOOL DISTRICT``) with no building
word before it (:data:`NY_BUILDING_WORDS`) names the district itself, so the whole district."""
NY_BUILDING_WORDS: Final = frozenset(
    {
        "SCHOOL",
        "SCHOOLS",
        "ELEMENTARY",
        "INTERMEDIATE",
        "PRIMARY",
        "MIDDLE",
        "HIGH",
        "JR",
        "SR",
        "ACADEMY",
        "BUILDING",
        "BUILDINGS",
        "CAMPUS",
        "GRADE",
        "GRADES",
        "OFFICE",
        "PS",
    }
)
"""Words of a building or a part of the district: one before a district-kind word means the
cell names a building of the district, not the district."""
NY_REASON_WORDS: Final = frozenset(
    {
        *("STATE", "OF", "EMERGENCY", "DECLARED", "DECLARE", "DECLARATION"),
        *("GOVERNOR", "GOVERNORS", "GOV", "COUNTY", "LOCAL", "CITY", "TOWN"),
        *("SPECIAL", "ELECTION", "VOTE", "VOTING", "DAY"),
        *("WEATHER", "ADVERSE", "CONDITIONS", "SNOW", "ICE", "STORM", "WIND", "FLOOD", "COLD"),
        *("NO", "POWER", "OUTAGE", "LACK", "ELECTRICITY", "HEAT", "WATER"),
        *("DUE", "TO", "THE", "A", "AND", "FOR"),
    }
)
"""The generic words of a reason written after a whole-district phrase (a declared emergency,
an election, the weather, a lost utility). A note of other words, a name or a number may say a
part (``EXCEPT``, ``ONLY``, a building), so the cell reads ``unknown``."""
NY_LIMIT_WORDS: Final = frozenset(
    {"EXCEPT", "EXCLUDING", "WITHOUT", "ONLY", "BUT", "NOT", "PARTIAL", "PARTIALLY", "PART"}
)
"""Words that limit a whole-district phrase: a note holding one is never a reason."""
NY_CUT: Final = 3
"""The fewest letters of a reason word the cell's last word may be cut to (the form's cell
width cuts a long note: ``EMER`` for ``EMERGENCY``)."""
NY_PLACEHOLDER: Final = frozenset({"SCHOOL", "BUILDING", "NAME", "N/A", "NA", "NONE", "UNKNOWN"})
"""The form's own label words: a cell of these words only names no part of the district."""
NY_NOTE: Final = re.compile(r"\bSTATE OF EMERGENCY\b|\bDECLARED\b")
"""A reason written in the building cell (with no building before a note): no part is said."""
_NY_NOTE_SPLIT: Final = re.compile(r"\s+-\s+|\(")
_NY_WORDS: Final = re.compile(r"[\s/]+")
_NY_ALL_WORDS: Final = re.compile(r"[\s/()-]+")
_NY_NOTE_WORDS: Final = re.compile(r"[A-Z]+|\d+")
NY_BLANK: Final = "NONE"
"""The code of a dated slot with a blank reason."""
EXCEL_EPOCH: Final = date(1899, 12, 30)
type NyHeld = Literal["outside", "weekend", "not_school_day", "unmapped", "repeat"]
NY_HELD: Final[Mapping[NyHeld, str]] = {
    "outside": "outside the school year",
    "weekend": "on a weekend",
    "not_school_day": "not a school day by the default calendar",
    "unmapped": "of a code the id rule does not map",
    "repeat": "the same date twice in a row",
}
"""Each edition-1 rule that holds a dated entry, in the order applied."""


@dataclass(frozen=True, slots=True)
class A8Entry:
    """One dated slot of an A-8 row: its date, reason code and scope (no building text)."""

    slot: int
    day: date
    code: str
    scope: Scope


@dataclass(frozen=True, slots=True)
class A8Row:
    """One district's row of a yearly A-8 export (its code, its dated slots, its largest day
    total; no name, comment, status, URL or building text)."""

    number: str
    entries: tuple[A8Entry, ...]
    total: float | None
    """The largest of its day totals (a parse check, never a count); ``None``: all blank."""


def _blank(cell: str | None) -> bool:
    return cell is None or not cell.strip()


def _a8_columns(labels: Sequence[str | None], where: str) -> dict[int, tuple[int, int, int]]:
    """Each slot's (date, reason, building) columns, found by their row-3 label."""
    found: dict[tuple[str, int], int] = {}
    for index, cell in enumerate(labels):
        label = (cell or "").split("|")[0].strip()
        match = _NY_SLOT.fullmatch(label)
        if match is None:
            continue
        kind, slot = (
            ("date", int(match.group(1) or 1))
            if match.group(2) is None
            else (match.group(2).lower(), int(match.group(3)))
        )
        if (kind, slot) in found:
            raise StateRecordError(f"{where}: a {kind} column twice")
        found[kind, slot] = index
    slots = {slot for kind, slot in found if kind == "date"}
    if {s for _, s in found} != slots or any(
        (k, s) not in found for s in slots for k in ("reason", "building")
    ):
        raise StateRecordError(f"{where}: a slot without its date, reason or building column")
    return {s: (found["date", s], found["reason", s], found["building", s]) for s in slots}


def _near_district(word: str) -> bool:
    """``DISTRICT`` or one edit from it (a letter added, dropped, changed, or two swapped)."""
    target = NY_DISTRICT
    if word == target:
        return True
    if abs(len(word) - len(target)) > 1:
        return False
    if len(word) == len(target):
        diff = [i for i, (a, b) in enumerate(zip(word, target, strict=True)) if a != b]
        return len(diff) == 1 or (
            len(diff) == 2  # noqa: PLR2004 - two letters swapped
            and diff[1] == diff[0] + 1
            and word[diff[0]] == target[diff[1]]
            and word[diff[1]] == target[diff[0]]
        )
    short, long = sorted((word, target), key=len)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def _a8_reason(note: Sequence[str]) -> bool:
    """The words after a whole-district phrase are none, or a reason only: each a reason word
    (the last may be cut to :data:`NY_CUT` letters or more of one), none a limiting word."""
    if not note:
        return True
    if any(w in NY_LIMIT_WORDS for w in note):
        return False
    *full, last = note
    return all(w in NY_REASON_WORDS for w in full) and (
        last in NY_REASON_WORDS
        or (len(last) >= NY_CUT and any(r.startswith(last) for r in NY_REASON_WORDS))
    )


def _a8_whole_words(read: tuple[str, ...]) -> int | None:
    """How many of the head's first words say the whole district, or ``None``: a reviewed
    phrase (all of them), ``WHOLE``/``ENTIRE`` and ``DISTRICT`` or ``SCHOOL DISTRICT`` (two or
    three), or a cell ending in a district-kind word or ``SCHOOL DISTRICT`` with no building
    word before it (all of them: the district's own name)."""
    if read in NY_WHOLE:
        return len(read)
    if read[0] in NY_WHOLE_LEAD:
        if read[1:2] == (NY_DISTRICT,):
            return 2
        if read[1:3] == ("SCHOOL", NY_DISTRICT):
            return 3  # WHOLE SCHOOL DISTRICT
    kind = 1 if read[-1] in NY_DISTRICT_KIND else 2 if read[-2:] == ("SCHOOL", NY_DISTRICT) else 0
    if kind and not set(read[:-kind]) & NY_BUILDING_WORDS:
        return len(read)
    return None


def a8_scope(cell: str | None) -> Scope:
    """The scope a building cell says, read as a class of generic words, never by a name (its
    text is never kept). In order: a blank cell, or one of the form's own label words only
    (:data:`NY_PLACEHOLDER`), is ``unknown``; a whole-district head (:func:`_a8_whole_words`,
    the words before any `` - `` or ``(`` note) is ``whole`` when every word after it, in the
    head and the note, is a reason (:func:`_a8_reason`), and ``unknown`` when not (a note may
    say a part: ``EXCEPT``, ``ONLY``, a building); a reason written in the cell with no
    building before a note (:data:`NY_NOTE`) is ``unknown``; any other text is ``share`` (a
    building). The district's own schools are never seen here: :func:`build_ny` reads a
    ``share`` of a one-school district (:attr:`StateRecords.one_school`) as ``unknown``."""
    if cell is None or _blank(cell):
        return Scope.UNKNOWN
    text = " ".join(cell.upper().split())
    head, *rest = _NY_NOTE_SPLIT.split(text, maxsplit=1)
    head = head.strip()
    if text.replace(" ", "") in NY_PLACEHOLDER or set(_NY_ALL_WORDS.split(text)) - {""} <= (
        NY_PLACEHOLDER
    ):
        return Scope.UNKNOWN
    words = tuple(w for w in _NY_WORDS.split(head) if w)
    if not words:
        return Scope.SHARE  # a note with nothing before it: some text, never the whole
    plain = tuple(
        part
        for word in words
        for part in (word.split("-") if word.replace("-", "").isalpha() else (word,))
        if part
    )
    read = tuple(NY_DISTRICT if _near_district(w) else w for w in plain)
    whole = _a8_whole_words(read)
    if whole is not None:
        note = (*read[whole:], *_NY_NOTE_WORDS.findall(" ".join(rest)))
        return Scope.WHOLE if _a8_reason(note) else Scope.UNKNOWN
    if NY_NOTE.search(head):
        return Scope.UNKNOWN
    return Scope.SHARE


def _a8_total(row: Sequence[str | None], columns: Sequence[int]) -> float | None:
    values: list[float] = []
    for index in columns:
        cell = row[index] if index < len(row) else None
        if _blank(cell):
            continue
        try:
            values.append(float((cell or "").strip()))
        except ValueError:
            continue  # a parse check only: never a refusal
    return max(values) if values else None


def read_a8(data: bytes, claim: str, codes: Mapping[str, StateCode]) -> list[A8Row]:
    """A yearly A-8 export's district rows. Every column is read by its label, never by
    position (the column set changes from year to year): the code by the second header row's
    ``Beds Code``, each slot's date, reason and building by its row-3 label. Comments, status,
    URL, grade flags and names are never read; a building's text only as a class. An empty or
    space-only cell is blank; a dated slot with a blank reason reads as :data:`NY_BLANK`.

    Raises:
        StateRecordError: the workbook does not read; its title's claim year is not ``claim``;
            a header row is not where it must be; a row after the header is neither a 6-digit
            code nor the closing marker (nor empty); a code comes twice; a date cell is not a
            5-digit serial; or a reason is on no code's ``match`` list.
    """
    where = f"ny claim {claim}"
    try:
        rows = list(iter_rows(data))
    except (XlsxFormatError, KeyError, ValueError) as error:
        raise StateRecordError(f"{where}: the workbook does not read") from error
    code_at, columns, totals = _a8_header(rows, claim, where)
    reasons = {phrase: code for code, mapped in codes.items() for phrase in mapped.match}
    if NY_BLANK not in codes:
        raise StateRecordError(f"{where}: no code {NY_BLANK} for a blank reason")
    found: list[A8Row] = []
    for at, row in enumerate(rows[NY_HEADER_ROWS:], start=NY_HEADER_ROWS + 1):
        number = (_at(row, code_at) or "").strip()
        if all(_blank(c) for c in row) or (number == NY_MARKER and at == len(rows)):
            continue
        if not _NY_NUMBER.fullmatch(number):
            raise StateRecordError(f"{where}: a row that is not a district code")
        entries = tuple(
            entry
            for slot, cells in sorted(columns.items())
            if (entry := _a8_entry(row, slot, cells, reasons, where)) is not None
        )
        found.append(A8Row(number=number, entries=entries, total=_a8_total(row, totals)))
    if len({r.number for r in found}) != len(found):
        raise StateRecordError(f"{where}: a district code twice")
    return found


def _at(row: Sequence[str | None], index: int) -> str | None:
    return row[index] if index < len(row) else None


def _a8_header(
    rows: Sequence[Sequence[str | None]], claim: str, where: str
) -> tuple[int, dict[int, tuple[int, int, int]], list[int]]:
    """The code column, each slot's columns and the day-total columns, after the header's
    checks (the title's claim year, the code column's label, the SEQ row)."""
    if len(rows) <= NY_HEADER_ROWS or not rows[0]:
        raise StateRecordError(f"{where}: no header")
    title = NY_TITLE.search(rows[0][0] or "")
    if title is None or f"{title.group(1)}-{title.group(2)[2:]}" != claim:
        raise StateRecordError(f"{where}: the title names another claim year")
    if int(title.group(2)) != int(title.group(1)) + 1:
        raise StateRecordError(f"{where}: the title's claim year does not read")
    names = [(c or "").strip() for c in rows[1]]
    if names.count(NY_CODE) != 1:
        raise StateRecordError(f"{where}: no single code column")
    if any(not _blank(c) and not (c or "").strip().startswith(NY_SEQ) for c in rows[3]):
        raise StateRecordError(f"{where}: the fourth header row is not the SEQ row")
    totals = [
        i for i, c in enumerate(rows[2]) if _NY_TOTAL.fullmatch((c or "").split("|")[0].strip())
    ]
    return names.index(NY_CODE), _a8_columns(rows[2], where), totals


def _a8_entry(
    row: Sequence[str | None],
    slot: int,
    cells: tuple[int, int, int],
    reasons: Mapping[str, str],
    where: str,
) -> A8Entry | None:
    """A slot's dated entry; ``None`` when its date is blank (nothing else of it is read)."""
    day_at, reason_at, building_at = cells
    serial = _at(row, day_at)
    if serial is None or _blank(serial):
        return None
    if not _NY_SERIAL.fullmatch(serial.strip()):
        raise StateRecordError(f"{where} slot {slot}: a date that is not a serial")
    reason = _at(row, reason_at)
    code = NY_BLANK if reason is None or _blank(reason) else reasons.get(reason.strip())
    if code is None:
        raise StateRecordError(f"{where} slot {slot}: a reason on no list")
    return A8Entry(
        slot=slot,
        day=EXCEL_EPOCH + timedelta(days=int(serial.strip())),
        code=code,
        scope=a8_scope(_at(row, building_at)),
    )


def _claim_of(year: str) -> str:
    """The claim year whose form holds ``year``'s days (the year after: 2025-26 in 2026-27)."""
    start = int(year[:4]) + 1
    return f"{start}-{(start + 1) % 100:02d}"


@dataclass(slots=True)
class _NyFile:
    """One file's written days and what was held (counts only)."""

    days: list[PastDay] = field(default_factory=list)
    counts: list[YearCount] = field(default_factory=list)
    held: dict[NyHeld, int] = field(default_factory=lambda: dict.fromkeys(NY_HELD, 0))
    totals: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(("equal", "more", "fewer", "no date", "no total"), 0)
    )


def _ny_written(  # noqa: PLR0913, PLR0917 - one file's rows and where they are said
    state: StateRecords,
    year: str,
    rows: Sequence[A8Row],
    built: Built,
    out: _NyFile,
    where: str,
) -> dict[str, dict[date, A8Entry]]:
    """Each mapped district's written entries by day, after the edition-1 rules in order (a
    repeat of a date is held only when its reason and building class are the kept slot's: a
    repeat that differs would lose one silently, so it refuses the file, said by file id). A
    ``share`` of a district :attr:`StateRecords.one_school` lists reads ``unknown`` first: its
    cell names the district's one school, never a part, and the directory is one year's, so it
    cannot say the district had one school in the row's year either."""
    written: dict[str, dict[date, A8Entry]] = {}
    one = frozenset(state.one_school)
    for row in rows:
        unit = _map(state, row.number, built)
        for found in row.entries:
            entry = (
                replace(found, scope=Scope.UNKNOWN)
                if unit in one and found.scope is Scope.SHARE
                else found
            )
            rule: NyHeld | None = (
                "outside"
                if _year_of(entry.day) != year
                else "weekend"
                if entry.day.weekday() >= SATURDAY
                else "not_school_day"
                if not is_school_day(entry.day)
                else "unmapped"
                if unit is None
                else "repeat"
                if entry.day in written.get(unit, {})
                else None
            )
            if rule == "repeat":
                assert unit is not None  # noqa: S101 - "unmapped" comes first
                kept = written[unit][entry.day]
                if (kept.code, kept.scope) != (entry.code, entry.scope):
                    raise StateRecordError(
                        f"{where}: a date twice in a row with another reason or building"
                    )
            if rule is not None:
                out.held[rule] += 1
                continue
            assert unit is not None  # noqa: S101 - "unmapped" above
            written.setdefault(unit, {})[entry.day] = entry
        dated = len({e.day for e in row.entries})
        total = row.total or 0.0
        if dated or total:
            out.totals[
                "no date"
                if not dated
                else "no total"
                if not total
                else "equal"
                if total == dated
                else "more"
                if total > dated
                else "fewer"
            ] += 1
    return written


def _ny_file(state: StateRecords, item: StateFile, rows: Sequence[A8Row], built: Built) -> _NyFile:
    """One file's written days and counts. A row the record's own models refuse is said by the
    file id only: a model's message names the day and the district, so it never leaves here
    (raised ``from None``, its message and chain dropped)."""
    try:
        return _ny_rows(state, item, rows, built)
    except ValidationError:
        raise StateRecordError(f"{item.id}: a row the record refuses") from None


def _ny_rows(state: StateRecords, item: StateFile, rows: Sequence[A8Row], built: Built) -> _NyFile:
    (year,) = item.years
    out = _NyFile()
    written = _ny_written(state, year, rows, built, out, item.id)
    tally: dict[tuple[str, str], int] = {}
    for unit, by_day in written.items():
        for day, entry in by_day.items():
            mapped = state.codes[entry.code]
            prior = by_day.get(previous_school_day(day))
            off = None if prior is None else state.codes[prior.code].day_off
            if mapped.call is None or mapped.cause is None:
                raise StateRecordError(
                    f"{item.id}: code {entry.code} is dated with no call or cause"
                )
            out.days.append(
                PastDay(
                    version=PAST_VERSION,
                    day=day,
                    unit=unit,
                    weather=None,
                    klass="unknown",
                    after=None if prior is None else True,
                    after_weather=None if off is None or off == "unknown" else off == "weather",
                    situation=None,
                    call=mapped.call,
                    source_kind=SourceKind.PAST_RECORDS,
                    source_complete=False,
                    closings_only=True,
                    scope=entry.scope,
                    cause=mapped.cause,
                    weather_day=mapped.weather_day,
                    fit_usable=False,
                    reasons=(),
                    tropical=None,
                    sources=(item.id,),
                    code=entry.code,
                )
            )
            tally[unit, entry.code] = tally.get((unit, entry.code), 0) + 1
    out.days.sort(key=lambda d: (d.day, d.unit))
    out.counts = [
        YearCount(
            version=PAST_VERSION,
            unit=unit,
            year=year,
            code=code,
            days=days,
            not_weather=0,
            unconfirmed=0,
            source_kind=SourceKind.PAST_RECORDS,
            sources=(item.id,),
            covid=year in COVID_YEARS,
            disaster=None,
        )
        for (unit, code), days in sorted(tally.items())
    ]
    return out


def build_ny(state: StateRecords, files: Mapping[str, bytes]) -> Built:
    """New York's rows from its pinned A-8 files' bytes (by file id; see the module). Every
    file writes both of its keys, empty bytes when no row is written. Its lines hold counts,
    codes and file ids only (a public log): the held entries by rule, the totals check, and the
    codes mapped; ``dropped`` stays empty (a day that is not a school day is held and counted).

    Raises:
        StateRecordError: a file is missing, is not a yearly A-8 file of its pinned claim year,
            does not read, or holds a code in neither ``ids`` nor ``unmapped``.
    """
    built = Built()
    codes: set[str] = set()
    filers: set[str] = set()
    held: dict[NyHeld, int] = dict.fromkeys(NY_HELD, 0)
    empty = 0
    for item in state.files:
        if item.id not in files:
            raise StateRecordError(f"{item.id}: not read")
        if item.form != "ny_a8" or len(item.years) != 1:
            raise StateRecordError(f"{item.id}: not a yearly A-8 file")
        claim = _claim_of(item.years[0])
        if item.id != f"ny-a8-{claim}":
            raise StateRecordError(f"{item.id}: not the id of claim year {claim}")
        rows = read_a8(files[item.id], claim, state.codes)
        codes.update(r.number for r in rows)
        filers.update(r.number for r in rows if r.entries)
        out = _ny_file(state, item, rows, built)
        for kind, rows_of in ((PAST_DAYS, out.days), (PAST_COUNTS, out.counts)):
            data = lines_bytes(rows_of, item.id)
            built.keys[past_key(item.id, item.edition, kind)] = data
            empty += not data
        built.days.extend(out.days)
        built.counts.extend(out.counts)
        for rule, n in out.held.items():
            held[rule] += n
        built.lines.append(
            _say_file(item, out.days, out.counts)
            + "; held "
            + ", ".join(f"{n} {NY_HELD[rule]}" for rule, n in out.held.items())
            + "; totals (a parse check, never a count): the largest equals the dated days in"
            f" {out.totals['equal']} district-years, is more in {out.totals['more']}, fewer in"
            f" {out.totals['fewer']}, a total and no date in {out.totals['no date']}, dates and"
            f" no total in {out.totals['no total']}"
        )
    built.lines.append(
        f"predict each-school past: {state.state}: {len(built.days)} dated rows over"
        f" {len({d.unit for d in built.days})} districts"
        f" ({sum(d.weather_day for d in built.days)} weather days), {len(built.counts)} yearly"
        " counts; held "
        + ", ".join(f"{n} {NY_HELD[rule]}" for rule, n in held.items())
        + f"; {len(codes & set(state.ids))} of {len(codes)} codes mapped,"
        f" {len(filers & set(state.ids))} of {len(filers)} with a date; {len(built.keys)} keys,"
        f" {empty} empty"
    )
    if built.unmapped:
        built.lines.append(
            f"predict each-school past: {state.state}: district codes with no LEA, listed and"
            f" not matched: {', '.join(sorted(built.unmapped))}"
        )
    return built


type Kind = Literal["days", "counts"]
KINDS: Final[Mapping[str, tuple[Kind, ...]]] = {
    "ky_summary": (PAST_DAYS, PAST_COUNTS),
    "ky_trend": (PAST_COUNTS,),
    "ny_a8": (PAST_DAYS, PAST_COUNTS),
}
"""The record keys each file form writes."""


BUILDERS: Final[Mapping[str, Callable[[StateRecords, Mapping[str, bytes]], Built]]] = {
    "ky": build_ky,
    "ny": build_ny,
}
"""Each state's builder (R1 Kentucky, then New York's A-8; the record plan's order adds the
next)."""


def checked(item: StateFile, data: bytes) -> bytes:
    """The file's bytes when they are the pinned ones.

    Raises:
        StateRecordError: another size or SHA-256 than the pin.
    """
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != item.bytes or digest != item.sha256:
        raise StateRecordError(
            f"{item.id}: {len(data)} B, SHA-256 {digest[:12]}, not the pinned"
            f" {item.bytes} B {item.sha256[:12]}: a changed file needs a reviewed pin"
        )
    return data


# --- the step ---------------------------------------------------------------------------------


def register(steps: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``each-school past`` under ``each-school``."""
    past = steps.add_parser(
        "past", help="write the public state records of past school days (once a file)"
    )
    past.add_argument("--config", type=Path, default=STATE_RECORDS_PATH)
    past.add_argument("--state", action="append", default=None, help="only these states")
    past.add_argument(
        "--files", type=Path, default=None, help="read <file id> here instead of its URL"
    )
    past.add_argument(
        "--dry-run",
        type=Path,
        default=None,
        help="write each key's rows to this folder; the evidence store is not asked",
    )
    past.set_defaults(handler=run_past)


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def read_files(
    state: StateRecords, folder: Path | None, fetch: Callable[[str], bytes]
) -> dict[str, bytes]:
    """Each pinned file's checked bytes, from ``folder`` (``<file id>``) or its URL (a received
    file has none: it is read only from ``folder``, never fetched).

    Raises:
        StateRecordError: a file is not the pinned one, did not read, or is a received file
            with no ``folder``.
    """
    found: dict[str, bytes] = {}
    for item in state.files:
        if folder is not None:
            data = (folder / item.id).read_bytes()
        elif item.url is None:
            raise StateRecordError(f"{item.id}: a received file is read only from --files")
        else:
            data = fetch(item.url)
        found[item.id] = checked(item, data)
    return found


def _fetch(url: str) -> bytes:  # pragma: no cover - the network
    import httpx  # noqa: PLC0415

    from snowlight.predict.inputs import client  # noqa: PLC0415

    try:
        with client() as http:
            answer = http.get(url)
    except httpx.HTTPError as error:
        raise StateRecordError(f"a state file did not read: {type(error).__name__}") from error
    if answer.status_code != 200:  # noqa: PLR2004 - HTTP
        raise StateRecordError(f"a state file answered HTTP {answer.status_code}")
    return answer.content


def wanted(state: StateRecords, held: Iterable[str]) -> list[str]:
    """The state's record keys the store does not hold."""
    keys = {
        past_key(item.id, item.edition, kind) for item in state.files for kind in KINDS[item.form]
    }
    return sorted(keys - set(held))


def unpinned(state: StateRecords, built: Built) -> list[str]:
    """Each built key whose bytes are not the SHA-256 its file pins (``written``), said."""
    found: list[str] = []
    for item in state.files:
        for kind in KINDS[item.form]:
            key = past_key(item.id, item.edition, kind)
            digest = hashlib.sha256(built.keys.get(key, b"")).hexdigest()
            pin = item.written.get(kind)
            if pin != digest:
                found.append(f"{key} SHA-256 {digest[:12]}, pinned {(pin or 'none')[:12]}")
    return found


def past_keys(
    states: Sequence[StateRecords],
    held: Iterable[str],
    folder: Path | None,
    fetch: Callable[[str], bytes],
    say: Callable[[str], None],
) -> dict[str, bytes]:
    """Each state's record keys the store does not hold, with their bytes: a state with any
    key missing is read, checked and built whole; one that fails a check, or whose builder
    leaves a wanted key unbuilt, gives none and is warned of (its keys already kept stay as
    they are), and the next state runs. A state with a received file is built only from
    ``folder`` (``--files``): with none it says so in one plain line and gives nothing."""
    held = frozenset(held)
    found: dict[str, bytes] = {}
    for state in states:
        keys = wanted(state, held)
        if not keys:
            say(f"predict each-school past: {state.state}: every key is kept already")
            continue
        received = sum(item.received is not None for item in state.files)
        if folder is None and received:
            say(
                f"predict each-school past: {state.state}: {received} of its files were"
                f" received, never fetched: they are built only with --files, so"
                f" {len(keys)} keys are not written"
            )
            continue
        try:
            built = BUILDERS[state.state](state, read_files(state, folder, fetch))
        except (StateRecordError, RecordError, OSError, ValidationError) as error:
            # a model's own message names a day and a district: only its type is said
            said = error if isinstance(error, StateRecordError) else type(error).__name__
            say(f"::warning::predict each-school past: {state.state}: {said}: nothing written")
            continue
        for line in built.lines:
            say(line)
        if built.dropped:
            say(
                f"predict each-school past: {state.state}: {len(built.dropped)} weather days are"
                f" not school days on the district's own calendar, not written: "
                + ", ".join(f"{n} {d.isoformat()}" for n, d in built.dropped)
            )
        unbuilt = [key for key in keys if key not in built.keys]
        if unbuilt:
            say(
                f"::warning::predict each-school past: {state.state}: built no key"
                f" {', '.join(unbuilt)}: nothing written"
            )
            continue
        drift = unpinned(state, built)
        if drift:
            say(
                f"::warning::predict each-school past: {state.state}: {'; '.join(drift)}: a"
                f" changed output needs a reviewed pin and a new edition: nothing written"
            )
            continue
        found.update((key, built.keys[key]) for key in keys)
    return found


def run_past(args: argparse.Namespace) -> int:  # pragma: no cover - the real world
    """Run ``predict each-school past`` (each-school-record.yml): the keys :func:`past_keys`
    gives are offered to the evidence store's record kind (``--dry-run``: written to a folder,
    the store not asked)."""
    import os  # noqa: PLC0415

    from snowlight.live import evidence  # noqa: PLC0415
    from snowlight.live.cli import make_client  # noqa: PLC0415
    from snowlight.live.d1 import D1Error  # noqa: PLC0415
    from snowlight.output import write_bytes_atomic  # noqa: PLC0415
    from snowlight.predict.record import held_days  # noqa: PLC0415

    config = load(args.config)
    states = [s for k, s in sorted(config.states.items()) if not args.state or k in args.state]
    if args.dry_run is not None:
        for key, data in past_keys(states, (), args.files, _fetch, _say).items():
            write_bytes_atomic(args.dry_run / key.replace("/", "_"), data)
        return 0
    try:
        with make_client() as client:
            store = evidence.make_store(dict(os.environ), client)
            keys = past_keys(states, held_days(store), args.files, _fetch, _say)
            offers = [evidence.Offer(evidence.RECORD, key, data) for key, data in keys.items()]
            if offers:
                for report in store.push(offers, (evidence.RECORD,)):
                    _say(
                        f"predict each-school past {report.database}: {len(offers)} keys offered,"
                        f" {report.kept} kept and read back, {report.copied} copied from the"
                        f" other database"
                    )
    except (D1Error, evidence.EvidenceError) as error:
        _say(f"::error::predict each-school past: {error}")
        return 1
    return 0
