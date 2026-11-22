"""The airports table (D5): every US airport in the BTS history of the last 12 months, with its
weather station, place, time zone, NWS office and forecast zone, and departures per day.

Built by :func:`build` from three public tables, all read once into RAM and never committed:

* the BTS compact tables (:mod:`snowlight.flights.bts`): which airports had departures, how many,
  and their city and state;
* the OurAirports list (``airports.csv``, public domain): each airport's name, ICAO code and
  location;
* the IEM station tables (``<ST>_ASOS.geojson``): each airport's weather station, time zone, NWS
  office and forecast zone and county.

The result is committed as ``pipeline/data/flights/airports.json`` (:data:`AIRPORTS_FILE`), which
the live job and the monthly job read, and published as ``flights/airports.json``.
"""

import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

import polars as pl

DATA_DIR: Final = Path(__file__).resolve().parents[2] / "data" / "flights"
AIRPORTS_FILE: Final = DATA_DIR / "airports.json"

US_AREAS: Final = frozenset({"US", "PR", "VI", "GU", "AS", "MP"})

RENAMED: Final[dict[str, str]] = {"PBI": "DJT"}
"""Airports whose code changed, old to new: the history under the old code is the same airport
(BTS writes DJT from August 2026, PBI before)."""


def current_code(column: str) -> pl.Expr:
    """A code column with every old code (:data:`RENAMED`) replaced by the current one."""
    return pl.col(column).replace(RENAMED)


@dataclass(frozen=True, slots=True)
class Airport:
    """One airport."""

    code: str
    """The code people use (BTS and IATA), such as ``MCI``."""
    icao: str
    """The four-letter code, such as ``KMCI``; the forecast bulletin's station id."""
    wx: str
    """The weather station's id in the IEM archive (``MCI``, ``PANC``)."""
    name: str
    city: str
    state: str
    lat: float
    lon: float
    tz: str
    wfo: str
    zone: str
    county: str
    per_day: float
    """Scheduled departures per day over the last 12 months."""

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> "Airport":
        """Read one row of :data:`AIRPORTS_FILE`."""
        return cls(
            code=str(value["code"]),
            icao=str(value["icao"]),
            wx=str(value["wx"]),
            name=str(value["name"]),
            city=str(value["city"]),
            state=str(value["state"]),
            lat=float(str(value["lat"])),
            lon=float(str(value["lon"])),
            tz=str(value["tz"]),
            wfo=str(value["wfo"]),
            zone=str(value["zone"]),
            county=str(value["county"]),
            per_day=float(str(value["per_day"])),
        )


def load(path: Path | None = None) -> tuple[Airport, ...]:
    """The committed airports (:data:`AIRPORTS_FILE` unless ``path``), busiest first."""
    rows = json.loads((path or AIRPORTS_FILE).read_text(encoding="utf-8"))
    return tuple(Airport.from_json(row) for row in rows)


def dump(airports: Sequence[Airport], path: Path) -> None:
    """Write the airports table (one row per line, so a change reads in a diff)."""
    lines = [
        json.dumps(asdict(airport), sort_keys=True, ensure_ascii=False) for airport in airports
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[\n" + ",\n".join(lines) + "\n]\n", encoding="utf-8")


@dataclass(frozen=True, slots=True)
class _Named:
    icao: str
    name: str
    lat: float
    lon: float
    scheduled: bool


def read_ourairports(path: Path) -> dict[str, list[_Named]]:
    """OurAirports rows in US areas by IATA code, and by ``K`` + code for those without one."""
    found: dict[str, list[_Named]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["iso_country"] not in US_AREAS:
                continue
            named = _Named(
                icao=row["icao_code"] or row["gps_code"] or row["ident"],
                name=row["name"],
                lat=float(row["latitude_deg"]),
                lon=float(row["longitude_deg"]),
                scheduled=row["scheduled_service"] == "yes",
            )
            for key in {row["iata_code"], row["ident"]}:
                if key:
                    found.setdefault(key, []).append(named)
    return found


def read_stations(paths: Iterable[Path]) -> dict[str, dict[str, object]]:
    """IEM ASOS stations by id: properties plus ``lat`` and ``lon``."""
    stations: dict[str, dict[str, object]] = {}
    for path in paths:
        for feature in json.loads(path.read_text(encoding="utf-8")).get("features", []):
            lon, lat = feature["geometry"]["coordinates"]
            stations[feature["id"]] = {**feature["properties"], "lat": lat, "lon": lon}
    return stations


def _name_of(code: str, named: Mapping[str, list[_Named]]) -> _Named | None:
    rows = named.get(code, []) or named.get(f"K{code}", [])
    rows = sorted(rows, key=lambda row: not row.scheduled)
    return rows[0] if rows else None


def _station_of(
    code: str, icao: str | None, stations: Mapping[str, Mapping[str, object]]
) -> str | None:
    candidates = [code]
    if icao:
        candidates += [icao[1:]] if icao.startswith("K") else [icao]
    candidates.append(f"K{code}")
    return next((c for c in candidates if c in stations), None)


ZONE_BY_STATE: Final[Mapping[str, str]] = {
    "VI": "America/Puerto_Rico",
    "PR": "America/Puerto_Rico",
}
"""Places on Atlantic Standard Time all year, by state: the station table gives the US Virgin
Islands a zone that keeps daylight time (``Atlantic/Bermuda``), an hour off from March to
November. ``America/Puerto_Rico`` is the canonical zone of that time (``America/St_Thomas`` is a
link to it)."""


def zone_of(state: str, tzname: str) -> str:
    """An airport's time zone: its state's own where :data:`ZONE_BY_STATE` names one, else the
    station table's."""
    return ZONE_BY_STATE.get(state, tzname)


def build(
    dep: pl.DataFrame,
    places: pl.DataFrame,
    named: Mapping[str, list[_Named]],
    stations: Mapping[str, Mapping[str, object]],
    bulletin: frozenset[str] | None = None,
) -> tuple[list[Airport], list[str]]:
    """The airports of the last 12 months' departures (``dep``: the ``dep`` compact table of those
    months), busiest first, and the codes left out (no weather station found) with why.

    ``bulletin``: the station ids of a forecast bulletin; an airport's ``icao`` is then the id the
    bulletin uses for it (Palm Beach is still ``KPBI`` there)."""
    dep = dep.with_columns(current_code("apt"))
    places = places.with_columns(current_code("apt"))
    days = dep.select(pl.col("day").n_unique()).item()
    per_day = (
        dep.group_by("apt")
        .agg(pl.col("n").sum().alias("n"))
        .with_columns((pl.col("n") / days).alias("per_day"))
        .sort("per_day", descending=True)
    )
    city = places.sort("n", descending=True).unique("apt", keep="first")
    city_of = {row["apt"]: (row["city"], row["state"]) for row in city.iter_rows(named=True)}
    out: list[Airport] = []
    left: list[str] = []
    for row in per_day.iter_rows(named=True):
        code: str = row["apt"]
        known = _name_of(code, named)
        icao = known.icao if known else None
        station = _station_of(code, icao, stations)
        if station is None:
            left.append(f"{code}: no weather station")
            continue
        props = stations[station]
        if bulletin is not None:
            olds = [old for old, new in RENAMED.items() if new == code]
            ids = [icao, f"K{code}", *[f"K{old}" for old in olds], f"K{station}", station]
            icao = next((i for i in ids if i and i in bulletin), icao)
        town, state = city_of.get(code, (code, ""))
        out.append(
            Airport(
                code=code,
                icao=icao or (f"K{station}" if len(station) == 3 else station),  # noqa: PLR2004
                wx=station,
                name=known.name if known else str(props.get("sname", code)).title(),
                city=town.split(",")[0],
                state=state,
                lat=round(known.lat if known else float(str(props["lat"])), 4),
                lon=round(known.lon if known else float(str(props["lon"])), 4),
                tz=zone_of(state, str(props["tzname"])),
                wfo=str(props.get("wfo") or ""),
                zone=str(props.get("ugc_zone") or ""),
                county=str(props.get("ugc_county") or ""),
                per_day=round(float(row["per_day"]), 1),
            )
        )
    return out, left
