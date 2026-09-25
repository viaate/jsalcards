"""The Census Bureau's 2020 ZCTA-to-county relationship file.

``tab20_zcta520_county20_natl.txt`` is a pipe-delimited UTF-8 table with one row
for every piece of a 2020 ZCTA that lies in a 2020 county (and rows with an empty
ZCTA for county land outside every ZCTA). The first two digits of
``GEOID_COUNTY_20`` are the state FIPS code, and ``AREALAND_PART`` is the land
area of the piece in square meters. :func:`zcta_state_land` sums those pieces
into the land each ZCTA has in each state.

ZCTAs are redrawn only after each decennial census, so the 2020 file stays
current until the 2030 ZCTAs are published; the places build checks that its
ZCTAs are exactly the Gazetteer's.
"""

import re
from collections import defaultdict
from pathlib import Path

from snowlight.sources.census import CensusFormatError
from snowlight.sources.census.table import decode, require_columns, split_table

ZCTA_COUNTY_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_county20_natl.txt"
)
_COLUMNS = ("GEOID_ZCTA5_20", "GEOID_COUNTY_20", "AREALAND_PART")
_ZCTA = re.compile(r"\d{5}")
_COUNTY = re.compile(r"\d{5}")


def zcta_state_land(text: str, label: str) -> dict[str, dict[str, int]]:
    """Return ``{zcta: {state FIPS: land square meters}}`` from the file text.

    Rows without a ZCTA (county land outside every ZCTA) are skipped.

    Raises:
        CensusFormatError: on a malformed code or area.
    """
    header, rows = split_table(text, label)
    require_columns(header, _COLUMNS, label)
    land: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        zcta, county, area = row["GEOID_ZCTA5_20"], row["GEOID_COUNTY_20"], row["AREALAND_PART"]
        if zcta == "":
            continue
        if not _ZCTA.fullmatch(zcta) or not _COUNTY.fullmatch(county) or not area.isdigit():
            raise CensusFormatError(f"{label}: bad row {zcta!r} {county!r} {area!r}")
        land[zcta][county[:2]] += int(area)
    return {zcta: dict(states) for zcta, states in land.items()}


def read_zcta_state_land(path: Path) -> dict[str, dict[str, int]]:
    """Parse the relationship file at ``path`` with :func:`zcta_state_land`."""
    return zcta_state_land(decode(path.read_bytes(), path.name), path.name)
