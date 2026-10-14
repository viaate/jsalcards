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

* rows that name a place in their text rather than in a county field (a WeatherThreat
  row's ``location``, "Scottsbluff"; a typed list's ``line``; any row's own name, "Laramie
  County School District #1"): read with the school directory's place names
  (:class:`PlaceIndex`: each school's city, its district's name and its county's name, with
  the county they lie in). A name counts only when it is a single county's among the
  states the station lists (``scopes``): "Sheridan" (a Colorado town and a Wyoming county)
  names neither for a Denver list.

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
    named: dict[str, str] = field(default_factory=dict)
    """County (FIPS) to the first row text that named a place in it by the place index."""


_WORD = re.compile(r"[a-z0-9]+")
COMMON_WORDS = frozenset(
    {
        "alpine", "alta", "basin", "buffalo", "burns", "carpenter", "center", "centennial",
        "central", "douglas", "eureka", "garden", "granger", "hanna", "harmony", "hope",
        "independence", "jackson", "kelly", "lake", "liberty", "midwest", "mills", "mission",
        "moran", "opal", "park", "plains", "powell", "recluse", "story", "union", "upton",
        "valley", "victory", "weston", "wilson", "wright", "dayton", "lincoln", "washington",
        "franklin", "madison", "monroe", "clay", "marion", "jefferson", "fremont",
        "summit", "sublette", "riverside", "fairview", "springfield", "salem", "georgetown",
    }
)  # fmt: skip
"""Single-word place names that are also common words or names ("Story", "Mills", "Midwest",
"Wright", Wyoming towns): never read as a place by themselves."""
MIN_PLACE = 4
"""The shortest place name read (in letters)."""


def place_key(text: str) -> str:
    """A place name as the index compares it: lower case, words only, "#" and "&" dropped."""
    return " ".join(_WORD.findall(text.lower().replace("st.", "saint")))


@dataclass(frozen=True, slots=True)
class PlaceIndex:
    """The school directory's place names, each with the counties (FIPS) it lies in."""

    names: Mapping[str, frozenset[str]]
    longest: int

    @classmethod
    def build(cls, places: Iterable[tuple[str | None, str | None, str]]) -> "PlaceIndex":
        """Index (city, district name, county FIPS) triples; each county's own name (from the
        Gazetteer, given as a city-less triple's district name) too."""
        found: dict[str, set[str]] = defaultdict(set)
        for city, district, fips in places:
            for name in (city, district):
                key = place_key(name or "")
                if len(key.replace(" ", "")) < MIN_PLACE or key in COMMON_WORDS:
                    continue
                found[key].add(fips)
        names = {key: frozenset(value) for key, value in found.items()}
        return cls(names, max((len(key.split()) for key in names), default=0))

    def named(self, text: str, scope: frozenset[str] | None = None) -> set[str]:
        """The counties ``text`` names, each by a place name that is a single county's among
        the counties whose state FIPS is in ``scope`` (all states when None). At each word
        the longest name present is read; an ambiguous one names nothing."""
        words = place_key(text).split()
        counties: set[str] = set()
        start = 0
        while start < len(words):
            step = 1
            for size in range(min(self.longest, len(words) - start), 0, -1):
                here = self.names.get(" ".join(words[start : start + size]))
                if here is None:
                    continue
                inside = {f for f in here if scope is None or f[:2] in scope}
                if len(inside) == 1:
                    counties |= inside
                step = size
                break
            start += step
        return counties


TEXT_FIELDS = ("location", "city", "address", "address1", "line", "county")
"""``raw_extra`` fields read for place names, besides the row's own name."""


def row_text(name: str, extra: Mapping[str, JsonScalar]) -> str:
    """A row's name and its place-bearing fields, as one text for :meth:`PlaceIndex.named`."""
    parts = [name] + [str(extra[key]) for key in TEXT_FIELDS if isinstance(extra.get(key), str)]
    return " | ".join(parts)


def observe(  # noqa: PLR0913 - the rows, the references and the place index
    rows: Iterable[RawRow],
    gazetteer: list[GazetteerCounty],
    states: Mapping[str, str],
    connecticut: CtRegions | None = None,
    *,
    places: PlaceIndex | None = None,
    scopes: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, Observed]:
    """Resolve every row's places to county FIPS codes, per source.

    Connecticut's old county names (which station lists still use) resolve to every
    planning region holding one of the old county's towns. With ``places``, a row's name
    and place fields are read for place names too (:meth:`PlaceIndex.named`), within the
    station's states (``scopes``: each source's state FIPS codes).
    """
    index = county_index(gazetteer)
    found: dict[str, Observed] = defaultdict(Observed)
    for row in rows:
        seen = found[row.source_id]
        seen.rows += 1
        if places is not None:
            text = row_text(row.raw_name, row.raw_extra)
            within = scopes.get(row.source_id) if scopes is not None else None
            for county in places.named(text, within) - seen.counties:
                seen.named.setdefault(county, text[:200])
                seen.counties.add(county)
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
