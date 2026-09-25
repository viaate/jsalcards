"""The Population Estimates Program's city and town population totals.

Each vintage is published at
``https://www2.census.gov/programs-surveys/popest/datasets/<base>-<vintage>/cities/totals/sub-est<vintage>.csv``,
one comma-separated row per geography. Rows with ``SUMLEV`` 162 are incorporated
places (plus the "balance" parts of consolidated cities); ``STATE`` + ``PLACE``
is the same 7-digit GEOID the Gazetteer uses, and ``POPESTIMATE<vintage>`` is
the July 1 estimate for the vintage year. Census publishes these files in
ISO-8859-1, which :func:`read_place_estimates` detects and records.
"""

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

from snowlight.sources.census import CensusFormatError
from snowlight.sources.census.listing import child_names

DATASETS_URL = "https://www2.census.gov/programs-surveys/popest/datasets/"
PLACE_SUMLEV = "162"
_SERIES_DIR = re.compile(r"(\d{4})-(\d{4})/")
_ESTIMATE_COLUMN = re.compile(r"POPESTIMATE(\d{4})")
_REQUIRED = ("SUMLEV", "STATE", "COUNTY", "PLACE", "FUNCSTAT", "NAME")


@dataclass(frozen=True, slots=True)
class PlaceEstimate:
    """The latest July 1 population estimate of one incorporated place."""

    geoid: str
    name: str
    funcstat: str
    population: int


@dataclass(frozen=True, slots=True)
class PlaceEstimates:
    """The SUMLEV 162 rows of one ``sub-est`` file, keyed by GEOID."""

    vintage: int
    column: str
    encoding: str
    by_geoid: dict[str, PlaceEstimate]


def estimate_series(index_html: str) -> list[tuple[int, int]]:
    """Return the ``(base year, vintage)`` directories on the index, newest vintage first."""
    series = {
        (int(match.group(1)), int(match.group(2)))
        for name in child_names(index_html, DATASETS_URL)
        if (match := _SERIES_DIR.fullmatch(name))
    }
    return sorted(series, key=lambda pair: (pair[1], pair[0]), reverse=True)


def totals_dir_url(base: int, vintage: int) -> str:
    """Return the directory holding the city and town totals of a series."""
    return f"{DATASETS_URL}{base}-{vintage}/cities/totals/"


def totals_file_name(vintage: int) -> str:
    """Return the national city and town totals file name of a vintage."""
    return f"sub-est{vintage}.csv"


def totals_listed(listing_html: str, base: int, vintage: int) -> bool:
    """Say whether the totals directory listing holds the national file."""
    names = child_names(listing_html, totals_dir_url(base, vintage))
    return totals_file_name(vintage) in names


def _decode(data: bytes) -> tuple[str, str]:
    try:
        return data.decode("utf-8").removeprefix("﻿"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("iso-8859-1"), "iso-8859-1"


def parse_place_estimates(data: bytes, vintage: int, label: str) -> PlaceEstimates:
    """Parse a ``sub-est<vintage>.csv`` file and keep its incorporated-place rows.

    Raises:
        CensusFormatError: if a required column is missing, the newest
            ``POPESTIMATE`` column is not the ``vintage`` year, a place row has
            a malformed code or population, or a GEOID repeats.
    """
    text, encoding = _decode(data)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = reader.fieldnames or []
    missing = [name for name in _REQUIRED if name not in header]
    if missing:
        raise CensusFormatError(f"{label}: missing columns {missing}")
    years = [int(m.group(1)) for name in header if (m := _ESTIMATE_COLUMN.fullmatch(name))]
    if not years or max(years) != vintage:
        raise CensusFormatError(f"{label}: newest estimate column is not {vintage} ({years})")
    column = f"POPESTIMATE{vintage}"
    by_geoid: dict[str, PlaceEstimate] = {}
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise CensusFormatError(f"{label}: ragged row {row.get('NAME')!r}")
        if row["SUMLEV"] != PLACE_SUMLEV:
            continue
        geoid = row["STATE"] + row["PLACE"]
        value = row[column]
        if not re.fullmatch(r"\d{7}", geoid) or row["COUNTY"] != "000" or not value.isdigit():
            raise CensusFormatError(f"{label}: bad place row {geoid!r} {row['NAME']!r}")
        if geoid in by_geoid:
            raise CensusFormatError(f"{label}: place {geoid} repeats")
        by_geoid[geoid] = PlaceEstimate(
            geoid=geoid, name=row["NAME"], funcstat=row["FUNCSTAT"], population=int(value)
        )
    if not by_geoid:
        raise CensusFormatError(f"{label}: no SUMLEV {PLACE_SUMLEV} rows")
    return PlaceEstimates(vintage=vintage, column=column, encoding=encoding, by_geoid=by_geoid)


def read_place_estimates(path: Path, vintage: int) -> PlaceEstimates:
    """Parse the ``sub-est`` file at ``path``."""
    return parse_place_estimates(path.read_bytes(), vintage, path.name)
