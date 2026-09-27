"""Television markets (DMAs) as county FIPS codes, read for the station priority.

The station priority (:mod:`snowlight.weights.priority`) gives each station the
counties of its market. The weights build reads the same three reference files
the station registry's county lists were made from, with its own readers here,
so this package depends on nothing outside the committed pipeline:

* the DMA county list ``alex-patton/US-TVDMA-BY-COUNTY`` ``usa-tvdma-county.csv``,
  pinned to commit ``7f254b8c1843c62ec976a71c40d366d45f6f29cd`` and to its SHA-256
  (:data:`DMA_CROSSWALK_SHA256`; the build refuses any other bytes). Nielsen does
  not publish its DMA county assignments openly; this list was compiled from
  Nielsen's listings in February 2017 and last corrected on 2026-03-09. Columns
  ``STATE``, ``STATE_AB``, ``COUNTY`` (upper case, without "County"),
  ``Internal_State_Region`` and ``TVDMA`` (the market, e.g. "Kansas City, MO - KS
  DMA"); the header is repeated between states. Its author warns that it was not
  reviewed exhaustively, so a border county can be a market off;
* the Census Bureau's 2025 county Gazetteer, ``2025_Gaz_counties_national.zip``
  (pipe-delimited text; ``USPS``, ``GEOID``, ``NAME``), which turns the list's
  county names into today's FIPS codes;
* the Census Bureau's Connecticut crosswalk, ``ct_cou_to_cousub_crosswalk.xlsx``:
  Connecticut replaced its eight counties with nine planning regions in 2022 and
  the school directory uses the regions, so an old county's market is given to
  every planning region that holds one of its towns (a region straddling two old
  counties in different markets belongs to both).

Rows for states outside the continental scope are dropped. A name that matches
no current county (the Virginia cities of Bedford, Clifton Forge and South
Boston, which became parts of counties) is reported in
:attr:`DmaCounties.unmatched`, never guessed at. Four names the list writes in an
old or shortened form are mapped by :data:`RENAMED`, each checked against the
Gazetteer by hand.

When the station registry (``pipeline/config/sources/*.yaml``) is present, the
build checks every DMA-based county list in it against :func:`read_crosswalk`'s
result (:func:`snowlight.weights.registered.market_agreement`), so the two cannot
drift apart unnoticed.
"""

import csv
import io
import re
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from snowlight.places.xlsx import XlsxError, read_table

DMA_CROSSWALK_URL = (
    "https://raw.githubusercontent.com/alex-patton/US-TVDMA-BY-COUNTY/"
    "7f254b8c1843c62ec976a71c40d366d45f6f29cd/usa-tvdma-county.csv"
)
DMA_CROSSWALK_SHA256 = "2e2cd00265a8d7040d8aa44ae779f2d5e595fcf3fa4633bca682a1f43622fd5c"
"""The SHA-256 of the pinned crosswalk file (the same bytes the station registry used)."""
COUNTY_GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/"
    "2025_Gaz_counties_national.zip"
)
CT_CROSSWALK_URL = (
    "https://www2.census.gov/geo/docs/reference/ct_change/ct_cou_to_cousub_crosswalk.xlsx"
)
OUT_OF_SCOPE_STATES = frozenset({"AK", "HI", "PR", "GU", "VI", "AS", "MP"})
RENAMED: dict[tuple[str, str], str] = {
    ("SD", "SHANNON"): "OGLALA LAKOTA",  # renamed in 2015 (46113 became 46102)
    ("FL", "DADE"): "MIAMI-DADE",  # renamed in 1997
    ("LA", "ST JOHN THE BAP"): "ST JOHN THE BAPTIST",  # truncated in the list
    ("MN", "LAKE OF WOODS"): "LAKE OF THE WOODS",  # "the" dropped in the list
}
"""(state, the name as the list writes it) to the Gazetteer's name."""
CROSSWALK_HEADER = ("STATE", "STATE_AB", "COUNTY", "Internal_State_Region", "TVDMA")
_SUFFIX = re.compile(
    r"\s+(county|parish|borough|census area|city and borough|municipality|planning region)$",
    re.IGNORECASE,
)
_CITY = " city"


class MarketsError(ValueError):
    """A market reference file does not have the shape read here."""


def normalize_county(name: str) -> str:
    """Return a comparison key for a county name.

    Accents, case, spaces and punctuation are dropped, and "Saint"/"St." become
    "ST", so "St. Mary's" and "SAINT MARYS" compare equal, as do "DeKalb" and
    "De Kalb". An independent city keeps the word CITY.
    """
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    upper = ascii_text.upper()
    for before, after in (("SAINT ", "ST "), ("STE. ", "STE "), ("ST. ", "ST ")):
        upper = upper.replace(before, after)
    return re.sub(r"[^A-Z0-9]", "", upper)


@dataclass(frozen=True, slots=True)
class GazetteerCounty:
    """One county or county equivalent of the Census Gazetteer."""

    state: str
    fips: str
    name: str


def read_gazetteer(path: Path) -> list[GazetteerCounty]:
    """Read the national county Gazetteer zip (one pipe-delimited text member).

    Raises:
        MarketsError: the file is not a zip holding exactly one UTF-8 text member, a
            column is missing, or a GEOID is not five digits.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.endswith(".txt")]
            if len(members) != 1:
                raise MarketsError(f"{path.name}: expected one text member, found {members}")
            text = archive.read(members[0]).decode("utf-8-sig")
    except (zipfile.BadZipFile, UnicodeDecodeError) as error:
        raise MarketsError(f"{path.name}: {error}") from error
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    columns = {column.strip() for column in reader.fieldnames or ()}
    if not {"USPS", "GEOID", "NAME"} <= columns:
        raise MarketsError(f"{path.name}: missing the USPS, GEOID or NAME column")
    counties: list[GazetteerCounty] = []
    for row in reader:
        values = {key.strip(): (value or "").strip() for key, value in row.items() if key}
        if not re.fullmatch(r"[0-9]{5}", values["GEOID"]):
            raise MarketsError(f"{path.name}: bad GEOID {values['GEOID']!r}")
        counties.append(GazetteerCounty(values["USPS"], values["GEOID"], values["NAME"]))
    return counties


def county_index(counties: list[GazetteerCounty]) -> dict[tuple[str, str], str]:
    """Map (state, normalized name) to FIPS, with and without the county suffix.

    An independent city ("Fairfax city") is found as "FAIRFAXCITY", and as
    "FAIRFAX" only when the state has no county of that name. Nevada's Carson City
    is a consolidated city whose Gazetteer name is "Carson City", not an
    independent city, so it is indexed like a county.
    """
    index: dict[tuple[str, str], str] = {}
    cities: list[tuple[tuple[str, str], str]] = []
    for county in counties:
        if county.name.endswith(_CITY) and county.state != "NV":
            base = county.name[: -len(_CITY)]
            index[(county.state, normalize_county(f"{base} CITY"))] = county.fips
            cities.append(((county.state, normalize_county(base)), county.fips))
            continue
        index[(county.state, normalize_county(_SUFFIX.sub("", county.name)))] = county.fips
        index[(county.state, normalize_county(county.name))] = county.fips
    for key, fips in cities:
        index.setdefault(key, fips)
    return index


@dataclass(frozen=True, slots=True)
class CtRegions:
    """Connecticut's old counties and the planning regions that hold their towns."""

    old_by_name: dict[str, str]
    """Normalized old county name to the old county's FIPS code."""
    regions: dict[str, frozenset[str]]
    """Old county FIPS code to the planning region FIPS codes."""


def read_ct_regions(path: Path) -> CtRegions:
    """Read the Census Connecticut county-to-town crosswalk workbook.

    Raises:
        MarketsError: the workbook does not read, a needed column is missing, or no
            Connecticut row is found.
    """
    try:
        header, rows = read_table(path, path.name)
    except (XlsxError, zipfile.BadZipFile) as error:
        raise MarketsError(f"{path.name}: {error}") from error
    columns = {name.split("\n")[0].strip(): position for position, name in enumerate(header)}
    for column in ("STATEFP", "OLD_COUNTYFP", "OLD_COUNTY_NAMELSAD", "NEW_COUNTYFP"):
        if column not in columns:
            raise MarketsError(f"{path.name}: missing column {column}")
    old_by_name: dict[str, str] = {}
    regions: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        state = row[columns["STATEFP"]].strip()
        old = row[columns["OLD_COUNTYFP"]].strip()
        new = row[columns["NEW_COUNTYFP"]].strip()
        name = row[columns["OLD_COUNTY_NAMELSAD"]].strip()
        if state != "09" or not (old and new and name):
            continue
        old_by_name[normalize_county(_SUFFIX.sub("", name))] = f"09{old}"
        regions[f"09{old}"].add(f"09{new}")
    if not regions:
        raise MarketsError(f"{path.name}: no Connecticut rows")
    return CtRegions(old_by_name, {old: frozenset(new) for old, new in regions.items()})


@dataclass(frozen=True, slots=True)
class DmaCounties:
    """Every market's counties as current FIPS codes, and the rows that name none."""

    by_dma: dict[str, tuple[str, ...]]
    """Market label to its counties (sorted)."""
    unmatched: tuple[tuple[str, str, str], ...]
    """(state, county as written, market) rows that name no current county."""

    def dma_of(self, fips: str) -> tuple[str, ...]:
        """Return the markets holding a county (two for a few Connecticut regions)."""
        return tuple(sorted(label for label, codes in self.by_dma.items() if fips in codes))


def read_crosswalk(
    path: Path, counties: list[GazetteerCounty], connecticut: CtRegions
) -> DmaCounties:
    """Read the DMA crosswalk and resolve every in-scope row to current FIPS codes.

    Raises:
        MarketsError: the file does not start with :data:`CROSSWALK_HEADER`, or is
            not UTF-8.
    """
    try:
        text = path.read_bytes().decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise MarketsError(f"{path.name}: not UTF-8 ({error})") from error
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    width = len(CROSSWALK_HEADER)
    if header is None or tuple(header[:width]) != CROSSWALK_HEADER:
        raise MarketsError(f"{path.name}: unexpected header {header}")
    index = county_index(counties)
    by_dma: dict[str, set[str]] = defaultdict(set)
    unmatched: list[tuple[str, str, str]] = []
    for row in reader:
        if len(row) < width or tuple(row[:width]) == CROSSWALK_HEADER:
            continue  # blank lines and the header the file repeats between states
        state, county, label = row[1].strip(), row[2].strip(), row[4].strip()
        if state in OUT_OF_SCOPE_STATES:
            continue
        if not label:
            unmatched.append((state, county, label))
            continue
        name = RENAMED.get((state, county), county)
        if state == "CT":
            old = connecticut.old_by_name.get(normalize_county(name))
            if old is None:
                unmatched.append((state, county, label))
            else:
                by_dma[label].update(connecticut.regions[old])
            continue
        fips = index.get((state, normalize_county(name)))
        if fips is None:
            unmatched.append((state, county, label))
        else:
            by_dma[label].add(fips)
    return DmaCounties(
        by_dma={label: tuple(sorted(codes)) for label, codes in sorted(by_dma.items())},
        unmatched=tuple(unmatched),
    )
