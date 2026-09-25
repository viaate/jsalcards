"""The Census Bureau's national Gazetteer files for places and ZCTAs.

Releases live at ``https://www2.census.gov/geo/docs/maps-data/data/gazetteer/``
as ``<year>_Gazetteer/<year>_Gaz_<layer>_national.zip``, each zip holding one
delimited text file. The columns this module reads, per the Census record
layouts, are:

* places: ``USPS`` (state abbreviation), ``GEOID`` (state + place FIPS),
  ``NAME`` (the full name, descriptor included, e.g. "Abbeville city"),
  ``LSAD`` (legal/statistical area description code), ``FUNCSTAT``,
  ``ALAND`` / ``AWATER`` (square meters), ``INTPTLAT`` / ``INTPTLONG``
  (internal point, decimal degrees);
* ZCTAs: ``GEOID`` (5-digit ZCTA), ``ALAND`` / ``AWATER``,
  ``INTPTLAT`` / ``INTPTLONG``.
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path

from snowlight.sources.census import CensusFormatError
from snowlight.sources.census.listing import child_names
from snowlight.sources.census.table import (
    decode,
    read_single_member,
    require_columns,
    split_table,
)

INDEX_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
_YEAR_DIR = re.compile(r"(\d{4})_Gazetteer/")
_PLACE_GEOID = re.compile(r"\d{7}")
_ZCTA_GEOID = re.compile(r"\d{5}")
_USPS = re.compile(r"[A-Z]{2}")
_PLACE_COLUMNS = (
    "USPS",
    "GEOID",
    "NAME",
    "LSAD",
    "FUNCSTAT",
    "ALAND",
    "AWATER",
    "INTPTLAT",
    "INTPTLONG",
)
_ZCTA_COLUMNS = ("GEOID", "ALAND", "AWATER", "INTPTLAT", "INTPTLONG")


@dataclass(frozen=True, slots=True)
class GazetteerPlace:
    """One row of a national places Gazetteer file."""

    usps: str
    geoid: str
    name: str
    lsad: str
    funcstat: str
    aland: int
    awater: int
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class GazetteerZcta:
    """One row of a national ZCTA Gazetteer file."""

    geoid: str
    aland: int
    awater: int
    lat: float
    lon: float


def release_years(index_html: str) -> list[int]:
    """Return the Gazetteer release years listed on the index page, newest first."""
    years = {
        int(match.group(1))
        for name in child_names(index_html, INDEX_URL)
        if (match := _YEAR_DIR.fullmatch(name))
    }
    return sorted(years, reverse=True)


def release_dir_url(year: int) -> str:
    """Return the directory URL of the ``year`` release."""
    return f"{INDEX_URL}{year}_Gazetteer/"


def national_file_name(year: int, layer: str) -> str:
    """Return the file name of the national ``layer`` file (``place``, ``zcta``, ...)."""
    return f"{year}_Gaz_{layer}_national.zip"


def national_file_url(year: int, layer: str) -> str:
    """Return the URL of the national ``layer`` file of the ``year`` release."""
    return release_dir_url(year) + national_file_name(year, layer)


def release_has(year_listing_html: str, year: int, layers: tuple[str, ...]) -> bool:
    """Say whether the ``year`` directory listing holds every national ``layers`` file."""
    names = set(child_names(year_listing_html, release_dir_url(year)))
    return all(national_file_name(year, layer) in names for layer in layers)


def _integer(value: str, column: str, label: str) -> int:
    if not value.isdigit():
        raise CensusFormatError(f"{label}: {column} {value!r} is not a whole number")
    return int(value)


def _coordinate(value: str, column: str, label: str, limit: float) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise CensusFormatError(f"{label}: {column} {value!r} is not a number") from exc
    if not math.isfinite(number) or not -limit <= number <= limit:
        raise CensusFormatError(f"{label}: {column} {value!r} is out of range")
    return number


def _checked_unique(geoids: list[str], label: str) -> None:
    if len(set(geoids)) != len(geoids):
        raise CensusFormatError(f"{label}: repeated GEOID")


def parse_places(text: str, label: str) -> list[GazetteerPlace]:
    """Parse the text of a national places Gazetteer file."""
    header, rows = split_table(text, label)
    require_columns(header, _PLACE_COLUMNS, label)
    places: list[GazetteerPlace] = []
    for row in rows:
        geoid, usps = row["GEOID"], row["USPS"]
        if not _PLACE_GEOID.fullmatch(geoid) or not _USPS.fullmatch(usps):
            raise CensusFormatError(f"{label}: bad place GEOID/USPS {geoid!r}/{usps!r}")
        if not row["NAME"] or not row["LSAD"]:
            raise CensusFormatError(f"{label}: place {geoid} has no NAME or LSAD")
        places.append(
            GazetteerPlace(
                usps=usps,
                geoid=geoid,
                name=row["NAME"],
                lsad=row["LSAD"],
                funcstat=row["FUNCSTAT"],
                aland=_integer(row["ALAND"], "ALAND", label),
                awater=_integer(row["AWATER"], "AWATER", label),
                lat=_coordinate(row["INTPTLAT"], "INTPTLAT", label, 90.0),
                lon=_coordinate(row["INTPTLONG"], "INTPTLONG", label, 180.0),
            )
        )
    _checked_unique([p.geoid for p in places], label)
    return places


def parse_zctas(text: str, label: str) -> list[GazetteerZcta]:
    """Parse the text of a national ZCTA Gazetteer file."""
    header, rows = split_table(text, label)
    require_columns(header, _ZCTA_COLUMNS, label)
    zctas: list[GazetteerZcta] = []
    for row in rows:
        geoid = row["GEOID"]
        if not _ZCTA_GEOID.fullmatch(geoid):
            raise CensusFormatError(f"{label}: bad ZCTA GEOID {geoid!r}")
        zctas.append(
            GazetteerZcta(
                geoid=geoid,
                aland=_integer(row["ALAND"], "ALAND", label),
                awater=_integer(row["AWATER"], "AWATER", label),
                lat=_coordinate(row["INTPTLAT"], "INTPTLAT", label, 90.0),
                lon=_coordinate(row["INTPTLONG"], "INTPTLONG", label, 180.0),
            )
        )
    _checked_unique([z.geoid for z in zctas], label)
    return zctas


def read_places(path: Path) -> tuple[str, list[GazetteerPlace]]:
    """Return ``(member name, places)`` from a national places Gazetteer zip."""
    member, data = read_single_member(path)
    return member, parse_places(decode(data, member), member)


def read_zctas(path: Path) -> tuple[str, list[GazetteerZcta]]:
    """Return ``(member name, ZCTAs)`` from a national ZCTA Gazetteer zip."""
    member, data = read_single_member(path)
    return member, parse_zctas(decode(data, member), member)
