"""Observed weather at 5 AM on the label dates, at each labeled district's nearest airport
(calc-research plan C2c; internal).

The 5 AM form of the rain/snow-line candidate reads what the airports reported just before the
morning decision: air temperature and present weather (rain, snow, sleet, freezing rain, a mix).
It is never an input of the 21:00 chance: it serves only the 05:00 pass, is scored against the
05:00 class, and uses only a report at or before 05:00 local on D (:func:`morning_report`).

Source: the Iowa Environmental Mesonet's ASOS archive (``cgi-bin/request/asos.py``, routine
reports, free for any lawful purpose), and its station lists per state network
(``geojson/network/<ST>_ASOS.geojson``). Requests go one a second with the site's User-Agent and
are cached under the gitignored ``.cache/predict/asos``. Kept: the station, its distance, the
report's time, temperature and METAR weather codes, and the flags read from them.
"""

import csv
import io
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import polars as pl

from snowlight.predict.config import PIPELINE_ROOT

ASOS_URL: Final = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
NETWORK_URL: Final = "https://mesonet.agron.iastate.edu/geojson/network/{state}_ASOS.geojson"
CACHE: Final = PIPELINE_ROOT / ".cache" / "predict" / "asos"
MORNING: Final = time(5, 0)
MAX_AGE: Final = timedelta(minutes=90)
"""A report older than this at 05:00 says nothing about 05:00."""
MAX_KM: Final = 40.0
"""A district farther than this from every station has no station."""
EARTH_KM: Final = 6371.0


class ObsError(ValueError):
    """A station list or an observations file does not read."""


@dataclass(frozen=True, slots=True)
class Station:
    """One ASOS station: its id (``BDL``), where it is, its state."""

    sid: str
    lat: float
    lon: float
    state: str


def parse_network(payload: bytes, state: str) -> list[Station]:
    """The stations of one state's ASOS network (IEM GeoJSON).

    Raises:
        ObsError: it is not a feature collection of points with ids.
    """
    try:
        data = json.loads(payload)
        found = []
        for feature in data["features"]:
            lon, lat = feature["geometry"]["coordinates"][:2]
            sid = feature["properties"].get("sid") or feature["id"]
            found.append(Station(str(sid), float(lat), float(lon), state))
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise ObsError(f"{state}: not a station list ({error})") from error
    return sorted(found, key=lambda item: item.sid)


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def nearest(
    stations: Sequence[Station], lat: float, lon: float, max_km: float = MAX_KM
) -> tuple[Station, float] | None:
    """The nearest station within ``max_km`` and how far it is (ties to the smaller id)."""
    best: tuple[float, str, Station] | None = None
    for station in stations:
        far = distance_km(lat, lon, station.lat, station.lon)
        if far <= max_km and (best is None or (far, station.sid) < best[:2]):
            best = (far, station.sid, station)
    return None if best is None else (best[2], round(best[0], 3))


def asos_query(stations: Iterable[str], day: date) -> str:
    """The request of routine reports of ``stations`` from 06 to 15 UTC on ``day`` (03:00 to
    05:00 local in every contiguous zone, with an hour to spare), in UTC."""
    start = datetime.combine(day, time(6), tzinfo=UTC)
    end = datetime.combine(day, time(15), tzinfo=UTC)
    params: list[tuple[str, str]] = [("station", sid) for sid in sorted(set(stations))]
    params += [("data", "tmpf"), ("data", "wxcodes")]
    for prefix, moment in (("1", start), ("2", end)):
        params += [
            (f"year{prefix}", str(moment.year)),
            (f"month{prefix}", str(moment.month)),
            (f"day{prefix}", str(moment.day)),
            (f"hour{prefix}", str(moment.hour)),
            (f"minute{prefix}", "0"),
        ]
    params += [
        ("tz", "Etc/UTC"),
        ("format", "onlycomma"),
        ("latlon", "no"),
        ("missing", "M"),
        ("trace", "T"),
        ("direct", "no"),
        ("report_type", "3"),
    ]
    return urlencode(params)


OBS_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "station": pl.String,
    "valid": pl.Datetime("us", "UTC"),
    "tmpf": pl.Float64,
    "wxcodes": pl.String,
}


def parse_asos(text: str) -> pl.DataFrame:
    """The reports of an ``onlycomma`` answer: station, time (UTC), temperature, weather codes
    (``None`` where missing).

    Raises:
        ObsError: a column is missing or a value does not read.
    """
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not {"station", "valid", "tmpf", "wxcodes"} <= set(
        reader.fieldnames
    ):
        raise ObsError(f"not an ASOS answer: {reader.fieldnames}")
    rows: list[dict[str, object]] = []
    try:
        for record in reader:
            tmpf = record["tmpf"]
            codes = record["wxcodes"]
            rows.append(
                {
                    "station": record["station"],
                    "valid": datetime.strptime(record["valid"], "%Y-%m-%d %H:%M").replace(
                        tzinfo=UTC
                    ),
                    "tmpf": None if tmpf in {"M", ""} else float(tmpf),
                    "wxcodes": None if codes in {"M", ""} else codes,
                }
            )
    except ValueError as error:
        raise ObsError(f"a report does not read: {error}") from error
    return pl.DataFrame(rows, schema=OBS_SCHEMA)


@dataclass(frozen=True, slots=True)
class Present:
    """What METAR weather codes report (``-SN BR``, ``FZRA``, ``RASN``, ``PL``)."""

    rain: bool = False
    snow: bool = False
    sleet: bool = False
    freezing: bool = False
    drizzle: bool = False

    @property
    def mix(self) -> bool:
        """Liquid and frozen together, or sleet with anything else."""
        liquid = self.rain or self.drizzle
        return (liquid and (self.snow or self.sleet)) or (self.sleet and self.snow)


def present(codes: str | None) -> Present:
    """The precipitation a report's weather codes name (``None``: none reported)."""
    if not codes:
        return Present()
    found = {"rain": False, "snow": False, "sleet": False, "freezing": False, "drizzle": False}
    for token in codes.split():
        body = token.lstrip("+-").removeprefix("VC")
        if body.startswith("FZ"):
            found["freezing"] = True
            body = body[2:]
        if body.startswith(("BL", "DR")):
            continue  # blowing or drifting snow, dust or sand: nothing falling
        for kind in ("SH", "TS"):
            body = body.removeprefix(kind)
        parts = {body[i : i + 2] for i in range(0, len(body) - 1, 2)}
        found["rain"] |= "RA" in parts
        found["drizzle"] |= "DZ" in parts
        found["snow"] |= bool(parts & {"SN", "SG"})
        found["sleet"] |= bool(parts & {"PL", "GS"})
    return Present(**found)


def morning_report(
    reports: pl.DataFrame, station: str, day: date, zone: str, max_age: timedelta = MAX_AGE
) -> dict[str, object] | None:
    """The station's latest report at or before 05:00 local on ``day`` and at most ``max_age``
    old then, or ``None``."""
    at = datetime.combine(day, MORNING, tzinfo=ZoneInfo(zone)).astimezone(UTC)
    mine = reports.filter(
        (pl.col("station") == station) & (pl.col("valid") <= at) & (pl.col("valid") >= at - max_age)
    ).sort("valid")
    if mine.is_empty():
        return None
    last = mine.row(-1, named=True)
    flags = present(last["wxcodes"])
    return {
        "valid": last["valid"],
        "minutes_before": round((at - last["valid"]).total_seconds() / 60),
        "tmpf": last["tmpf"],
        "wxcodes": last["wxcodes"],
        "rain": flags.rain,
        "snow": flags.snow,
        "sleet": flags.sleet,
        "freezing": flags.freezing,
        "drizzle": flags.drizzle,
        "mix": flags.mix,
    }


type Get = Callable[[str], bytes]
"""Fetch a URL's bytes."""


def cached_get(url: str, path: Path, get: Get, sleep: Callable[[], None]) -> tuple[bytes, bool]:
    """``url``'s bytes from ``path`` when cached, else fetched (after ``sleep``) and cached;
    and whether it was fetched."""
    if path.exists():
        return path.read_bytes(), False
    sleep()
    body = get(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    part.write_bytes(body)
    part.replace(path)
    return body, True


def district_points(schools: pl.DataFrame) -> pl.DataFrame:
    """Each district's point: the median latitude and longitude of its eligible schools
    (:func:`snowlight.predict.train.eligible_schools`; all its public schools when it has
    none)."""
    from snowlight.predict.train import eligible_schools  # noqa: PLC0415

    public = schools.filter((pl.col("kind") == "public") & pl.col("district_id").is_not_null())
    eligible = eligible_schools(schools)
    chosen = pl.concat(
        [
            eligible,
            public.filter(~pl.col("district_id").is_in(eligible["district_id"].unique().to_list())),
        ]
    )
    return (
        chosen.group_by(pl.col("district_id").alias("district"))
        .agg(pl.col("lat").median(), pl.col("lon").median(), pl.col("state").first())
        .sort("district")
    )


def label_rows(
    labels: pl.DataFrame,
    table: pl.DataFrame,
    points: pl.DataFrame,
    stations: Mapping[str, Sequence[Station]],
) -> pl.DataFrame:
    """Each known label's district, day, zone and nearest station (``None``: none in range),
    from the stations of its own and neighbouring networks (``stations`` by state)."""
    known = labels.filter(pl.col("outcome").is_in(["no_school", "delayed", "open"]))
    rows = known.select("district", "day").join(
        table.select("district", "time_zone"), on="district"
    )
    where = {r["district"]: r for r in points.iter_rows(named=True)}
    every = [station for group in stations.values() for station in group]
    found: dict[str, tuple[str | None, float | None]] = {}
    out: list[dict[str, object]] = []
    for district, day, zone in rows.iter_rows():
        if district not in found:
            point = where.get(district)
            hit = None if point is None else nearest(every, point["lat"], point["lon"])
            found[district] = (None, None) if hit is None else (hit[0].sid, hit[1])
        sid, far = found[district]
        out.append({"district": district, "day": day, "time_zone": zone, "station": sid, "km": far})
    return pl.DataFrame(
        out,
        schema={
            "district": pl.String,
            "day": pl.Date,
            "time_zone": pl.String,
            "station": pl.String,
            "km": pl.Float64,
        },
    )
