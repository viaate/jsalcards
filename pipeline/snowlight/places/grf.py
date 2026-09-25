"""NCES EDGE School District Geographic Relationship Files (GRFs).

NCES lists its GRF releases on :data:`GRF_PAGE_URL` as
``/programs/edge/data/GRF<yy>.zip``, where ``<yy>`` is the TIGER/Line release
year the file was built from. Each zip holds, among others,
``GRF<yy>/grf<yy>_lea_zcta5ce<zz>.xlsx``: one row per piece of a school district
(LEA) that falls in a ZIP Code Tabulation Area, with the columns documented in
NCES's GRF technical documentation:

* ``LEAID`` - 7-character NCES local education agency ID,
* ``NAME_LEA<yy>`` - district name,
* ``ZCTA5CE<zz>`` - ZCTA code (``00000`` marks district land outside every ZCTA),
* ``COUNT`` - number of ZCTAs in the district,
* ``LANDAREA`` / ``WATERAREA`` - area of the piece in square miles.

Elementary, secondary and unified districts are all listed, so where a state
has separate elementary and secondary districts one ZCTA piece appears once for
each.
"""

import io
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from snowlight.places.xlsx import read_table
from snowlight.sources.census.listing import page_links

GRF_PAGE_URL = "https://nces.ed.gov/programs/edge/Geographic/RelationshipFiles"
GRF_DATA_URL = "https://nces.ed.gov/programs/edge/data/"
UNASSIGNED_ZCTA = "00000"
_RELEASE = re.compile(r"https://nces\.ed\.gov/programs/edge/data/GRF(\d{2})\.zip", re.IGNORECASE)
_MEMBER = re.compile(r"(?:.*/)?grf(\d{2})_lea_zcta5ce(\d{2})\.xlsx", re.IGNORECASE)
_LEAID = re.compile(r"\d{7}")
_ZCTA = re.compile(r"\d{5}")


class GrfFormatError(ValueError):
    """Raised when a GRF file does not match its documented layout."""


@dataclass(frozen=True, slots=True)
class GrfRelease:
    """One GRF release listed on the NCES page."""

    tiger_year: int
    url: str


@dataclass(frozen=True, slots=True)
class LeaZctaPart:
    """The piece of one school district that lies in one ZCTA."""

    leaid: str
    name: str
    zcta: str
    land_sqmi: float
    water_sqmi: float


@dataclass(frozen=True, slots=True)
class LeaZctaTable:
    """The parsed LEA-ZCTA relationship sheet of one GRF release."""

    member: str
    zcta_vintage: int
    parts: list[LeaZctaPart]


def grf_release(tiger_year: int) -> GrfRelease:
    """Return the release built from the ``tiger_year`` TIGER/Line files."""
    return GrfRelease(tiger_year, f"{GRF_DATA_URL}GRF{tiger_year % 100:02d}.zip")


def grf_releases(page_html: str) -> list[GrfRelease]:
    """Return the GRF zips linked from the NCES page, newest TIGER year first."""
    found: dict[int, str] = {}
    for link in page_links(page_html, GRF_PAGE_URL):
        match = _RELEASE.fullmatch(link)
        if match:
            found[2000 + int(match.group(1))] = link
    return [GrfRelease(year, found[year]) for year in sorted(found, reverse=True)]


def _column(header: list[str], exact: str | None = None, prefix: str | None = None) -> int:
    for index, name in enumerate(header):
        if (exact is not None and name == exact) or (
            prefix is not None and name.startswith(prefix) and name[len(prefix) :].isdigit()
        ):
            return index
    wanted = exact if exact is not None else f"{prefix}<yy>"
    raise GrfFormatError(f"GRF sheet has no {wanted} column: {header}")


def _area(value: str, column: str, where: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise GrfFormatError(f"{where}: {column} {value!r} is not a number") from exc
    if not math.isfinite(number) or number < 0:
        raise GrfFormatError(f"{where}: {column} {value!r} is not a non-negative area")
    return number


def parse_lea_zcta(header: list[str], rows: list[list[str]], member: str) -> list[LeaZctaPart]:
    """Turn the cells of an LEA-ZCTA sheet into typed parts.

    Raises:
        GrfFormatError: on a missing column, malformed code or area, or a
            district-ZCTA pair listed twice.
    """
    leaid_at = _column(header, exact="LEAID")
    name_at = _column(header, prefix="NAME_LEA")
    zcta_at = _column(header, prefix="ZCTA5CE")
    land_at = _column(header, exact="LANDAREA")
    water_at = _column(header, exact="WATERAREA")
    parts: list[LeaZctaPart] = []
    seen: set[tuple[str, str]] = set()
    for number, row in enumerate(rows, start=2):
        where = f"{member} row {number}"
        leaid, zcta, name = row[leaid_at], row[zcta_at], row[name_at].strip()
        if not _LEAID.fullmatch(leaid) or not _ZCTA.fullmatch(zcta) or not name:
            raise GrfFormatError(f"{where}: bad LEAID/ZCTA/name {leaid!r} {zcta!r} {name!r}")
        if (leaid, zcta) in seen:
            raise GrfFormatError(f"{where}: {leaid} x {zcta} repeats")
        seen.add((leaid, zcta))
        parts.append(
            LeaZctaPart(
                leaid=leaid,
                name=name,
                zcta=zcta,
                land_sqmi=_area(row[land_at], "LANDAREA", where),
                water_sqmi=_area(row[water_at], "WATERAREA", where),
            )
        )
    if not parts:
        raise GrfFormatError(f"{member}: no rows")
    return parts


def read_lea_zcta(path: Path, tiger_year: int) -> LeaZctaTable:
    """Read the LEA-ZCTA sheet out of a GRF zip.

    Raises:
        GrfFormatError: unless the zip holds exactly one LEA-ZCTA workbook for
            ``tiger_year``, or if that workbook is malformed.
    """
    with zipfile.ZipFile(path) as archive:
        members = [
            (info.filename, match)
            for info in archive.infolist()
            if (match := _MEMBER.fullmatch(info.filename))
        ]
        if len(members) != 1:
            names = [name for name, _match in members]
            raise GrfFormatError(f"{path.name}: expected one LEA-ZCTA workbook, found {names}")
        member, match = members[0]
        if 2000 + int(match.group(1)) != tiger_year:
            raise GrfFormatError(f"{member}: not the {tiger_year} release")
        data = archive.read(member)
    header, rows = read_table(io.BytesIO(data), member)
    return LeaZctaTable(
        member=member,
        zcta_vintage=2000 + int(match.group(2)),
        parts=parse_lea_zcta(header, rows, member),
    )
