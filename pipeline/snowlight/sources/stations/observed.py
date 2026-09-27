"""Counties that actually appear in a station's own lists: a check on its county basis.

A station's county list comes from its market (``basis: dma`` in the registry). The
rows its archived lists held name places, so the counties they name can be compared
with that list: a county a station listed schools in but that its market list lacks
is a sign the market list is wrong for it (or that the station reaches past its
market). Places are read from each row's ``raw_extra`` as the adapter kept it:

* Hearst rows: ``location`` ("County, City, ST", several joined with " | "), or on the
  Next.js page ``locations`` (a JSON list of ``{"city", "county", "state"}``), or on
  the 2014-2015 ibsys page ``address`` ("City / County / ST", rows with a ``bucket``);
* Gray page rows: ``county`` with ``stateAabbreviation`` or ``state``;
* Gray export rows: ``county_name1`` with ``state``, ``stateName`` or ``forced_county_name``
  (which, despite its name, holds the state).

States are resolved with the Census Bureau's state code file (``state.txt``: code,
USPS abbreviation and name) and counties with the county Gazetteer, both as
:mod:`snowlight.sources.stations.dma` reads them. A place that does not resolve is
counted as unmatched, never guessed.
"""

import csv
import io
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from snowlight.sources.stations.dma import (
    CtRegions,
    GazetteerCounty,
    county_index,
    normalize_county,
)
from snowlight.sources.stations.model import JsonScalar, RawRow

STATE_CODES_URL = "https://www2.census.gov/geo/docs/reference/state.txt"
_SUFFIX = re.compile(r"\s+(county|parish|borough)$", re.IGNORECASE)
_USPS = re.compile(r"^[A-Z]{2}$")
_LOCATION_PARTS = 3


class ObservedError(ValueError):
    """The state code file does not have the expected shape."""


def read_states(path: Path) -> dict[str, str]:
    """Map every state's USPS code and normalized name to its USPS code."""
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    if not {"STUSAB", "STATE_NAME"} <= set(reader.fieldnames or ()):
        raise ObservedError(f"{path.name}: missing STUSAB or STATE_NAME")
    states: dict[str, str] = {}
    for row in reader:
        code = row["STUSAB"].strip().upper()
        states[code] = code
        states[_key(row["STATE_NAME"])] = code
    return states


def _key(name: str) -> str:
    return re.sub(r"[^A-Z]", "", name.upper())


def _state(value: JsonScalar, states: Mapping[str, str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if _USPS.match(text.upper()) and text.upper() in states:
        return text.upper()
    return states.get(_key(text))


def _hearst_places(extra: Mapping[str, JsonScalar]) -> list[tuple[str, str]]:
    places: list[tuple[str, str]] = []
    location = extra.get("location")
    if isinstance(location, str):
        for entry in location.split(" | "):
            parts = [part.strip() for part in entry.split(",")]
            if len(parts) >= _LOCATION_PARTS and parts[0]:
                places.append((parts[-1], parts[0]))
    address = extra.get("address")
    if "bucket" in extra and isinstance(address, str):
        parts = [part.strip() for part in address.split("/")]
        if len(parts) == _LOCATION_PARTS and parts[1]:
            places.append((parts[2], parts[1]))
    locations = extra.get("locations")
    if isinstance(locations, str):
        try:
            items = json.loads(locations)
        except ValueError:
            items = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("county") and item.get("state"):
                places.append((str(item["state"]), str(item["county"])))
    return places


def _gray_places(extra: Mapping[str, JsonScalar]) -> list[tuple[str, str]]:
    county = extra.get("county_name1") or extra.get("county")
    if not isinstance(county, str) or not county.strip():
        return []
    for key in ("stateAabbreviation", "state", "stateName", "forced_county_name"):
        value = extra.get(key)
        if isinstance(value, str) and value.strip():
            return [(value, county)]
    return []


def row_places(extra: Mapping[str, JsonScalar]) -> list[tuple[str, str]]:
    """Return the (state as written, county as written) pairs a row names."""
    return _hearst_places(extra) + _gray_places(extra)


@dataclass(slots=True)
class Observed:
    """What one station's archived rows say about where it lists schools."""

    rows: int = 0
    counties: set[str] = field(default_factory=set)
    unmatched: set[str] = field(default_factory=set)


def observe(
    rows: Iterable[RawRow],
    gazetteer: list[GazetteerCounty],
    states: Mapping[str, str],
    connecticut: CtRegions | None = None,
) -> dict[str, Observed]:
    """Resolve every row's places to county FIPS codes, per source.

    Connecticut's old county names (which station lists still use) resolve to every
    planning region holding one of the old county's towns.
    """
    index = county_index(gazetteer)
    found: dict[str, Observed] = defaultdict(Observed)
    for row in rows:
        seen = found[row.source_id]
        seen.rows += 1
        for state_text, county_text in row_places(row.raw_extra):
            state = _state(state_text, states)
            name = normalize_county(_SUFFIX.sub("", county_text.strip()))
            fips = index.get((state, name)) if state else None
            if fips is not None:
                seen.counties.add(fips)
                continue
            old = connecticut.old_by_name.get(name) if connecticut and state == "CT" else None
            if old is not None and connecticut is not None:
                seen.counties.update(connecticut.regions[old])
            else:
                seen.unmatched.add(f"{county_text.strip()}, {state_text.strip()}")
    return dict(found)


def read_rows(path: Path) -> list[RawRow]:
    """Read ``rows.jsonl`` as written by ``stations fetch`` or ``stations archive parse``."""
    if not path.is_file():
        return []
    return [
        RawRow.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
