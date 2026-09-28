"""The directory the matcher searches: districts and schools shaped like NCES rows.

A :class:`DirectoryRecord` is one district or one school with the fields the
matcher uses. :class:`Directory` holds them, checks that they fit together, and
answers the lookups the matcher and its callers need, above all
:meth:`Directory.expand`, which turns a matched district into all of its schools.

:func:`load_directory` reads the internal files ``snowlight directory build``
writes (``schools.parquet`` and ``districts.parquet``), so the matcher always
searches the same NCES release the map shows.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import polars as pl

from snowlight.match.grades import GRADE_CODES, Span, span_of

type Kind = Literal["district", "school"]
KINDS: Final[tuple[Kind, ...]] = ("district", "school")

_STATE: Final = re.compile(r"[A-Z]{2}")
_COUNTY: Final = re.compile(r"\d{5}")
_MAX_LATITUDE: Final = 90.0
_MAX_LONGITUDE: Final = 180.0


class DirectoryError(ValueError):
    """The directory records do not fit together (duplicate ids, unknown districts ...)."""


@dataclass(frozen=True, slots=True)
class DirectoryRecord:
    """One district or school, shaped like an NCES row.

    Attributes:
        id: the NCES id (7-digit LEA id, 12-digit school id or 8-character PPIN).
        name: the name as NCES publishes it.
        kind: ``"district"`` or ``"school"``.
        district_id: for a school, its district's id (``None`` for a private
            school); for a district, ``None`` or its own id.
        state: USPS state code.
        county_fips: 5-digit county FIPS code, or ``None`` when unknown.
        city: the location city, or ``None``.
        lat, lon: WGS84 degrees, or ``None`` when not geocoded.
        county: the county's name as NCES writes it (``"Clark County"``), or
            ``None`` when unknown. NCES ends some district names with it
            (``"Evergreen School District (Clark)"``) to tell namesakes apart.
        grade_low, grade_high: a school's lowest and highest grade as NCES codes
            them (``"PK"``, ``"KG"``, ``"01"`` ... ``"12"``, see
            :data:`~snowlight.match.grades.GRADE_CODES`), or ``None`` when unknown;
            always ``None`` for a district.
        level: a school's NCES level (``"Elementary"``, ``"Middle"``, ``"High"``,
            ``"Combined elementary and secondary"`` ...), or ``None``; always
            ``None`` for a district. NCES often leaves a school's level out of its
            name (``"Lincoln"``, ``"ST JOSEPH SCHOOL"``), and these say which a
            listing that names it with a level may mean (:attr:`span`).
    """

    id: str
    name: str
    kind: Kind
    district_id: str | None
    state: str
    county_fips: str | None
    city: str | None
    lat: float | None
    lon: float | None
    county: str | None = None
    grade_low: str | None = None
    grade_high: str | None = None
    level: str | None = None

    @property
    def point(self) -> tuple[float, float] | None:
        """``(lat, lon)`` when the record is geocoded."""
        if self.lat is None or self.lon is None:
            return None
        return (self.lat, self.lon)

    @property
    def span(self) -> Span | None:
        """A school's grades as numbers (:func:`~snowlight.match.grades.span_of`), if known."""
        if self.kind != "school":
            return None
        return span_of(self.grade_low, self.grade_high, self.level)


def _check(record: DirectoryRecord) -> None:
    problems: list[str] = []
    if not record.id or record.id != record.id.strip():
        problems.append("an empty or padded id")
    if not record.name.strip():
        problems.append("an empty name")
    if record.kind not in KINDS:
        problems.append(f"kind {record.kind!r}")
    if not _STATE.fullmatch(record.state):
        problems.append(f"state {record.state!r}")
    if record.county_fips is not None and not _COUNTY.fullmatch(record.county_fips):
        problems.append(f"county FIPS {record.county_fips!r}")
    if record.county is not None and not record.county.strip():
        problems.append("an empty county name")
    problems.extend(_grade_problems(record))
    if (record.lat is None) != (record.lon is None):
        problems.append("only one of lat and lon")
    elif (
        record.lat is not None
        and record.lon is not None
        and (abs(record.lat) > _MAX_LATITUDE or abs(record.lon) > _MAX_LONGITUDE)
    ):
        problems.append(f"coordinates ({record.lat}, {record.lon})")
    if record.kind == "district" and record.district_id not in (None, record.id):
        problems.append(f"district_id {record.district_id!r} on a district")
    if problems:
        raise DirectoryError(f"record {record.id!r} has " + ", ".join(problems))


def _grade_problems(record: DirectoryRecord) -> list[str]:
    """What is wrong with a record's grades and level, if anything."""
    problems: list[str] = []
    grades = (record.grade_low, record.grade_high)
    if record.kind == "district" and (grades != (None, None) or record.level is not None):
        problems.append("grades or a level on a district")
    for code in grades:
        if code is not None and code not in GRADE_CODES:
            problems.append(f"grade {code!r}")
    if (record.grade_low is None) != (record.grade_high is None):
        problems.append("only one of grade_low and grade_high")
    elif (
        record.grade_low in GRADE_CODES
        and record.grade_high in GRADE_CODES
        and _descends(record.grade_low, record.grade_high)
    ):
        problems.append(f"grades {record.grade_low!r} to {record.grade_high!r}")
    if record.level is not None and not record.level.strip():
        problems.append("an empty level")
    return problems


class Directory:
    """Districts and schools, indexed by id and by district.

    Raises:
        DirectoryError: on an invalid record, a repeated id, or a school whose
            ``district_id`` names no district in the directory.
    """

    def __init__(self, records: Iterable[DirectoryRecord]) -> None:
        self._records: tuple[DirectoryRecord, ...] = tuple(records)
        self._by_id: dict[str, DirectoryRecord] = {}
        schools: dict[str, list[DirectoryRecord]] = {}
        for record in self._records:
            _check(record)
            if record.id in self._by_id:
                raise DirectoryError(f"id {record.id!r} appears twice")
            self._by_id[record.id] = record
            if record.kind == "school" and record.district_id is not None:
                schools.setdefault(record.district_id, []).append(record)
        for district_id in schools:
            owner = self._by_id.get(district_id)
            if owner is None or owner.kind != "district":
                raise DirectoryError(f"schools name district {district_id!r}, which is not listed")
        self._schools = {key: tuple(value) for key, value in schools.items()}

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[DirectoryRecord]:
        return iter(self._records)

    def __contains__(self, record_id: object) -> bool:
        return record_id in self._by_id

    def __getitem__(self, record_id: str) -> DirectoryRecord:
        return self._by_id[record_id]

    def get(self, record_id: str) -> DirectoryRecord | None:
        """Return the record with ``record_id``, or ``None``."""
        return self._by_id.get(record_id)

    def schools_of(self, district_id: str) -> tuple[DirectoryRecord, ...]:
        """Return the schools of district ``district_id`` in directory order."""
        return self._schools.get(district_id, ())

    def expand(self, target: DirectoryRecord | str) -> tuple[DirectoryRecord, ...]:
        """Return every school a match covers: a district's schools, or the school itself.

        Raises:
            KeyError: if ``target`` is an id that is not in the directory.
        """
        record = self._by_id[target] if isinstance(target, str) else target
        if record.kind == "district":
            return self.schools_of(record.id)
        return (record,)


_SCHOOL_COLUMNS: Final = (
    "id",
    "name",
    "district_id",
    "state",
    "county_fips",
    "city",
    "lat",
    "lon",
    "grade_low",
    "grade_high",
    "level",
)
_DISTRICT_COLUMNS: Final = ("district_id", "name", "state", "county_fips", "city", "lat", "lon")
_COUNTY_NAME: Final = "county_name"


_OPTIONAL_COLUMNS: Final = frozenset({_COUNTY_NAME, "grade_low", "grade_high", "level"})
"""Columns an older build may lack: read as ``None`` throughout."""


def _read(path: Path, columns: tuple[str, ...]) -> pl.DataFrame:
    """The ``columns`` of one build file and its county names, in that order.

    A column of :data:`_OPTIONAL_COLUMNS` the file lacks reads as ``None``.
    """
    wanted = [*columns, _COUNTY_NAME]
    present = pl.read_parquet_schema(path)
    frame = pl.read_parquet(path, columns=[c for c in wanted if c in present])
    missing = [c for c in wanted if c not in present and c in _OPTIONAL_COLUMNS]
    if missing:
        frame = frame.with_columns(pl.lit(None, dtype=pl.String).alias(c) for c in missing)
    return frame.select(wanted)


def _grade_code(code: str | None) -> str | None:
    """An NCES grade code as the directory keeps it, or ``None`` for one it does not know."""
    return code if code in GRADE_CODES else None


def _grades(low: str | None, high: str | None, level: str | None) -> dict[str, str | None]:
    """A school's grade fields: both codes when the directory knows both, and its level.

    A code the directory does not know (:data:`~snowlight.match.grades.GRADE_CODES`)
    leaves both unknown, as does a lowest grade above the highest, so a new NCES
    code never stops the matcher loading: the school's level then says what it
    can (:func:`~snowlight.match.grades.span_of`).
    """
    first, last = _grade_code(low), _grade_code(high)
    if first is None or last is None or _descends(first, last):
        first = last = None
    return {"grade_low": first, "grade_high": last, "level": (level or "").strip() or None}


def _descends(low: str, high: str) -> bool:
    """True when grade code ``low`` is a higher grade than ``high`` (both known codes)."""
    first, last = GRADE_CODES[low], GRADE_CODES[high]
    return first is not None and last is not None and first > last


def load_directory(directory_dir: Path | str) -> Directory:
    """Read the districts and schools ``snowlight directory build`` kept.

    ``directory_dir`` is the build's internal directory folder, holding
    ``districts.parquet`` and ``schools.parquet``, as a path or a string.
    Districts come first, then schools, each in file order. A school carries its
    NCES grades and level when the files have them.
    """
    folder = Path(directory_dir)
    districts = _read(folder / "districts.parquet", _DISTRICT_COLUMNS)
    schools = _read(folder / "schools.parquet", _SCHOOL_COLUMNS)
    records: list[DirectoryRecord] = [
        DirectoryRecord(
            id=row[0],
            name=row[1],
            kind="district",
            district_id=None,
            state=row[2],
            county_fips=row[3],
            city=row[4],
            lat=row[5],
            lon=row[6],
            county=row[7] or None,
        )
        for row in districts.iter_rows()
    ]
    records.extend(
        DirectoryRecord(
            id=row[0],
            name=row[1],
            kind="school",
            district_id=row[2],
            state=row[3],
            county_fips=row[4],
            city=row[5],
            lat=row[6],
            lon=row[7],
            county=row[11] or None,
            **_grades(row[8], row[9], row[10]),
        )
        for row in schools.iter_rows()
    )
    return Directory(records)
