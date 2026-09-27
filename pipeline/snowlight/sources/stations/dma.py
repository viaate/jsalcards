"""Designated Market Area (DMA) county lists, keyed by today's county FIPS codes.

Nielsen does not publish its DMA county assignments openly, and neither the FCC
nor the Census Bureau republishes them. The list used here is a published
compilation, pinned to one commit so it cannot change underneath the pipeline:

* ``alex-patton/US-TVDMA-BY-COUNTY`` ``usa-tvdma-county.csv`` at commit
  ``7f254b8c1843c62ec976a71c40d366d45f6f29cd`` (compiled in February 2017 from
  Nielsen's DMA listings; last corrected 2026-03-09). Columns ``STATE_AB``,
  ``COUNTY`` (upper case, no "County") and ``TVDMA`` (the market, e.g.
  "Kansas City, MO - KS DMA"). Its author warns it was not reviewed exhaustively
  and that DMAs shift over time; border counties can therefore be a market off.

County names are turned into FIPS codes with the Census Bureau's 2025 county
Gazetteer (``2025_Gaz_counties_national.zip``: ``USPS``, ``GEOID``, ``NAME``).
Connecticut replaced its eight counties with nine planning regions in 2022, and
the school directory uses the regions; each old county's market is carried to
every planning region that holds one of its towns, using the Census Bureau's
``ct_cou_to_cousub_crosswalk.xlsx``. So a region that straddles two old counties
in different markets belongs to both.

Rows the list gives for Alaska and Hawaii are out of scope. Names that no longer
exist (the Virginia cities of Bedford, Clifton Forge and South Boston, which
became parts of counties) are reported as unmatched rather than guessed at. The
list has no row for the District of Columbia, Broomfield County, Colorado, or
Williams County, North Dakota.

Those counties are placed with a second published compilation, used only for
counties the first list has no row for at all (:func:`fill_missing`):

* ``BritCrit/dma_county_zip`` ``dma_county_zip_data_set.csv`` at commit
  ``02f847923bd218c30a8c5488d561eca42ecf3614`` (December 2021): one row per county
  FIPS code and ZIP code with the county's Nielsen DMA code and name (``fips``,
  ``county``, ``st``, ``dma_code``, ``dma_name``, ``zipcode``). It puts the District
  in DMA 511 (Washington, DC-Hagerstown), Broomfield in 751 (Denver) and Williams in
  687 (Minot-Bismarck-Dickinson). A missing county joins the first list's market
  that holds more than half of its DMA code's counties in the second list; one with
  no such market stays unplaced. Where the two lists disagree about a county both
  place, the first list wins: the second fills gaps, it overrides nothing.
"""

import csv
import io
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from snowlight.places.xlsx import read_table

DMA_CROSSWALK_URL = (
    "https://raw.githubusercontent.com/alex-patton/US-TVDMA-BY-COUNTY/"
    "7f254b8c1843c62ec976a71c40d366d45f6f29cd/usa-tvdma-county.csv"
)
DMA_CROSSWALK_SHA256 = "2e2cd00265a8d7040d8aa44ae779f2d5e595fcf3fa4633bca682a1f43622fd5c"
COUNTY_GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/"
    "2025_Gaz_counties_national.zip"
)
DMA_SUPPLEMENT_URL = (
    "https://raw.githubusercontent.com/BritCrit/dma_county_zip/"
    "02f847923bd218c30a8c5488d561eca42ecf3614/dma_county_zip_data_set.csv"
)
DMA_SUPPLEMENT_SHA256 = "c931c30cef1b5d2997e1a181dfaa91ecd71516e85813889ad2988424528cf8fe"
CT_CROSSWALK_URL = (
    "https://www2.census.gov/geo/docs/reference/ct_change/ct_cou_to_cousub_crosswalk.xlsx"
)
OUT_OF_SCOPE_STATES = frozenset({"AK", "HI", "PR", "GU", "VI", "AS", "MP"})
# Names the list gives in an old or shortened form, each checked against the 2025
# Gazetteer by hand: (state, as the list writes it) -> the Gazetteer's name.
RENAMED = {
    ("SD", "SHANNON"): "OGLALA LAKOTA",  # renamed 2015 (FIPS 46113 became 46102)
    ("FL", "DADE"): "MIAMI-DADE",  # renamed 1997
    ("LA", "ST JOHN THE BAP"): "ST JOHN THE BAPTIST",  # truncated in the list
    ("MN", "LAKE OF WOODS"): "LAKE OF THE WOODS",  # "the" dropped in the list
}
_SUFFIXES = re.compile(
    r"\s+(county|parish|borough|census area|city and borough|municipality|planning region)$",
    re.IGNORECASE,
)


class DmaError(ValueError):
    """A reference file does not have the shape this module reads."""


def normalize_county(name: str) -> str:
    """Return a comparison key for a county name: accents, case, punctuation dropped.

    "St." and "Saint" compare equal, as do "DeKalb" and "De Kalb". An independent
    city keeps the word CITY ("Fairfax city" and "FAIRFAX CITY").
    """
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = text.upper().replace("SAINT ", "ST ").replace("STE. ", "STE ").replace("ST. ", "ST ")
    return re.sub(r"[^A-Z0-9]", "", text)


@dataclass(frozen=True, slots=True)
class GazetteerCounty:
    """One county or county equivalent from the Census Gazetteer."""

    state: str
    fips: str
    name: str


def read_gazetteer(path: Path) -> list[GazetteerCounty]:
    """Read the national county Gazetteer zip (pipe-delimited text inside)."""
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.endswith(".txt")]
        if len(members) != 1:
            raise DmaError(f"{path.name}: expected one text member, found {members}")
        text = archive.read(members[0]).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    fields = {field.strip() for field in reader.fieldnames or ()}
    if not {"USPS", "GEOID", "NAME"} <= fields:
        raise DmaError(f"{path.name}: missing USPS, GEOID or NAME columns")
    counties = []
    for row in reader:
        clean = {key.strip(): (value or "").strip() for key, value in row.items() if key}
        if not re.fullmatch(r"[0-9]{5}", clean["GEOID"]):
            raise DmaError(f"{path.name}: bad GEOID {clean['GEOID']!r}")
        counties.append(GazetteerCounty(clean["USPS"], clean["GEOID"], clean["NAME"]))
    return counties


def county_index(counties: list[GazetteerCounty]) -> dict[tuple[str, str], str]:
    """Map (state, normalized name) to FIPS, with and without a county suffix.

    An independent city ("Fairfax city") is indexed as "FAIRFAXCITY", and also
    as "FAIRFAX" when no county of that name exists in the state.
    """
    index: dict[tuple[str, str], str] = {}
    plain_cities: list[tuple[tuple[str, str], str]] = []
    for county in counties:
        name = county.name
        if name.endswith(" city") and county.state != "NV":
            base = name[: -len(" city")]
            index[(county.state, normalize_county(base + " CITY"))] = county.fips
            plain_cities.append(((county.state, normalize_county(base)), county.fips))
            continue
        index[(county.state, normalize_county(_SUFFIXES.sub("", name)))] = county.fips
        index[(county.state, normalize_county(name))] = county.fips
    for key, fips in plain_cities:
        index.setdefault(key, fips)
    return index


@dataclass(frozen=True, slots=True)
class CtRegions:
    """Connecticut's old counties, by name, and the planning regions holding their towns."""

    old_by_name: dict[str, str]
    """Normalized old county name to its old FIPS code."""
    regions: dict[str, frozenset[str]]
    """Old county FIPS code to planning region FIPS codes."""


def read_ct_regions(path: Path) -> CtRegions:
    """Read the Census Connecticut county-to-town crosswalk workbook."""
    header, rows = read_table(path, path.name)
    columns = {name.split("\n")[0].strip(): position for position, name in enumerate(header)}
    needed = ("STATEFP", "OLD_COUNTYFP", "OLD_COUNTY_NAMELSAD", "NEW_COUNTYFP")
    for column in needed:
        if column not in columns:
            raise DmaError(f"{path.name}: missing column {column}")
    names: dict[str, str] = {}
    regions: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        state = row[columns["STATEFP"]].strip()
        old, new = row[columns["OLD_COUNTYFP"]].strip(), row[columns["NEW_COUNTYFP"]].strip()
        name = row[columns["OLD_COUNTY_NAMELSAD"]].strip()
        if state != "09" or not old or not new or not name:
            continue
        names[normalize_county(_SUFFIXES.sub("", name))] = f"09{old}"
        regions[f"09{old}"].add(f"09{new}")
    if not regions:
        raise DmaError(f"{path.name}: no Connecticut rows")
    return CtRegions(names, {old: frozenset(new) for old, new in regions.items()})


@dataclass(frozen=True, slots=True)
class DmaCounties:
    """Every market's counties as current FIPS codes, and what could not be placed."""

    by_dma: dict[str, tuple[str, ...]]
    unmatched: tuple[tuple[str, str, str], ...]
    """(state, county as written, market) rows that name no current county."""
    supplemented: tuple[tuple[str, str], ...] = ()
    """(county FIPS, market) placed by the second list (see :func:`fill_missing`)."""

    def dma_of(self, fips: str) -> tuple[str, ...]:
        """Return the markets a county belongs to (two for a few CT regions)."""
        return tuple(sorted(dma for dma, counties in self.by_dma.items() if fips in counties))


def read_crosswalk(
    path: Path, counties: list[GazetteerCounty], connecticut: CtRegions
) -> DmaCounties:
    """Read the DMA crosswalk CSV and resolve every row to current FIPS codes."""
    text = path.read_bytes().decode("utf-8", errors="strict")
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    expected = ["STATE", "STATE_AB", "COUNTY", "Internal_State_Region", "TVDMA"]
    width = len(expected)
    if header is None or header[:width] != expected:
        raise DmaError(f"{path.name}: unexpected header {header}")
    index = county_index(counties)
    by_dma: dict[str, set[str]] = defaultdict(set)
    unmatched: list[tuple[str, str, str]] = []
    for row in reader:
        if len(row) < width or row[:width] == expected:
            continue  # the file repeats its header between states
        state, county, dma = row[1].strip(), row[2].strip(), row[4].strip()
        if not dma or state in OUT_OF_SCOPE_STATES:
            if state not in OUT_OF_SCOPE_STATES:
                unmatched.append((state, county, dma))
            continue
        name = RENAMED.get((state, county), county)
        if state == "CT":
            old = connecticut.old_by_name.get(normalize_county(name))
            if old is None:
                unmatched.append((state, county, dma))
                continue
            by_dma[dma].update(connecticut.regions[old])
            continue
        fips = index.get((state, normalize_county(name)))
        if fips is None:
            unmatched.append((state, county, dma))
            continue
        by_dma[dma].add(fips)
    return DmaCounties(
        by_dma={dma: tuple(sorted(fips)) for dma, fips in sorted(by_dma.items())},
        unmatched=tuple(unmatched),
    )


NON_DMA = "0"
"""The second list's code for counties in no market (in Alaska)."""


def read_supplement(path: Path) -> dict[str, str]:
    """Read the second DMA list: each county FIPS code to its Nielsen DMA code.

    Counties in no market (code ``0``) are left out.

    Raises:
        DmaError: the file lacks its columns, a FIPS or DMA code is malformed, or a
            county is given two DMA codes.
    """
    text = path.read_bytes().decode("utf-8", errors="strict")
    reader = csv.DictReader(io.StringIO(text))
    if not {"fips", "dma_code"} <= set(reader.fieldnames or ()):
        raise DmaError(f"{path.name}: missing fips or dma_code columns")
    codes: dict[str, str] = {}
    for row in reader:
        fips, code = row["fips"].strip().zfill(5), row["dma_code"].strip()
        if not re.fullmatch(r"[0-9]{5}", fips) or not re.fullmatch(r"[0-9]{1,3}", code):
            raise DmaError(f"{path.name}: bad row {row}")
        if code == NON_DMA:
            continue
        if codes.setdefault(fips, code) != code:
            raise DmaError(f"{path.name}: county {fips} is in two markets")
    if not codes:
        raise DmaError(f"{path.name}: no rows")
    return codes


def fill_missing(
    markets: DmaCounties, supplement: Mapping[str, str], counties: Iterable[GazetteerCounty]
) -> DmaCounties:
    """Place the in-scope counties no market in ``markets`` holds, using the second list.

    A county is placed in the market of ``markets`` that holds more than half of the
    counties the second list gives the county's DMA code (see the module docstring);
    otherwise it stays unplaced. Counties ``markets`` already places are untouched.
    """
    placed = {fips for members in markets.by_dma.values() for fips in members}
    by_code: dict[str, set[str]] = defaultdict(set)
    for fips, market in supplement.items():
        by_code[market].add(fips)
    added: dict[str, set[str]] = defaultdict(set)
    for county in sorted(counties, key=lambda c: c.fips):
        if county.state in OUT_OF_SCOPE_STATES or county.fips in placed:
            continue
        code = supplement.get(county.fips)
        if code is None:
            continue
        members = by_code[code]
        overlap = Counter(
            {label: len(members.intersection(fips)) for label, fips in markets.by_dma.items()}
        )
        label, shared = overlap.most_common(1)[0]
        if 2 * shared > len(members):
            added[label].add(county.fips)
    by_dma = {
        label: tuple(sorted({*fips, *added.get(label, ())}))
        for label, fips in markets.by_dma.items()
    }
    supplemented = tuple(sorted((fips, label) for label, codes in added.items() for fips in codes))
    return DmaCounties(by_dma=by_dma, unmatched=markets.unmatched, supplemented=supplemented)
