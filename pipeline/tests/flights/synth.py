"""Synthetic Flights inputs for the tests: made-up airports, flights, bulletins and reports.

Nothing here describes a real flight, forecast or report: codes are AAA, BBB and CCC, the
carriers ZZ and YY, and every number is chosen to exercise the code.
"""

import csv
import io
import zipfile
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

from snowlight.flights.airports import Airport
from snowlight.flights.bts import COLUMNS
from snowlight.flights.nbs import ELEMENTS

AIRPORTS = (
    Airport(
        code="AAA",
        icao="KAAA",
        wx="AAA",
        name="Synthetic Field One",
        city="Synthetic City",
        state="MO",
        lat=39.0,
        lon=-94.0,
        tz="America/Chicago",
        wfo="XXX",
        zone="MOZ001",
        county="MOC001",
        per_day=200.0,
    ),
    Airport(
        code="BBB",
        icao="KBBB",
        wx="BBB",
        name="Synthetic Field Two",
        city="Synthetic Town",
        state="GA",
        lat=33.0,
        lon=-84.0,
        tz="America/New_York",
        wfo="YYY",
        zone="GAZ001",
        county="GAC001",
        per_day=150.0,
    ),
)

HOURS = tuple(range(6, 73, 3))


def bulletin(
    run: datetime, stations: Mapping[str, Mapping[str, Sequence[int | None]]], version: str = ""
) -> str:
    """A bulletin in the NBS layout: per station, each element's 23 values (``None`` blank)."""
    lines = [""]
    for station, values in stations.items():
        label = f"NBM {version} NBS GUIDANCE" if version else "NBM  NBS GUIDANCE"
        lines.append(
            f" {station:<7} {label}    {run.month}/{run.day:02d}/{run.year}  {run:%H}00 UTC"
        )
        lines.append(" DT /SYNTHETIC")
        lines.append(" UTC " + "".join(f"{(run + timedelta(hours=h)).hour:3d}" for h in HOURS))
        lines.append(" FHR " + "".join(f"{h:3d}" for h in HOURS))
        for element in ELEMENTS:
            row = values.get(element)
            if row is None:
                continue
            cells = "".join("   " if v is None else f"{v:3d}" for v in row)
            lines.append(f" {element} {cells}")
    return "\n".join(lines) + "\n"


def calm(**changes: Sequence[int | None]) -> dict[str, Sequence[int | None]]:
    """A quiet forecast's rows, with ``changes`` in place of some."""
    six = [None if i % 2 else 0 for i in range(len(HOURS))]
    rows: dict[str, Sequence[int | None]] = {
        "TMP": [40] * len(HOURS),
        "WSP": [8] * len(HOURS),
        "GST": [12] * len(HOURS),
        "P06": six,
        "PZR": [0] * len(HOURS),
        "PSN": [0] * len(HOURS),
        "T03": [0] * len(HOURS),
        "S06": six,
        "I06": six,
        "VIS": [100] * len(HOURS),
        "CIG": [-88] * len(HOURS),
    }
    rows.update(changes)
    return rows


def bts_rows(day: date, flights: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    """BTS rows (all text) for ``flights`` on ``day``: each gives carrier, number, dep, arr,
    dep_time, arr_time and optionally cancelled, dep_delay and arr_delay."""
    out = []
    for flight in flights:
        out.append(
            {
                "FlightDate": day.isoformat(),
                "Reporting_Airline": str(flight.get("carrier", "ZZ")),
                "Flight_Number_Reporting_Airline": str(flight.get("number", "100")),
                "Origin": str(flight["dep"]),
                "OriginCityName": "Synthetic City, MO",
                "OriginState": "MO",
                "Dest": str(flight["arr"]),
                "DestCityName": "Synthetic Town, GA",
                "DestState": "GA",
                "CRSDepTime": f"{flight.get('dep_time', 900):04d}",
                "DepDelay": str(flight.get("dep_delay", "0.00")),
                "CRSArrTime": f"{flight.get('arr_time', 1200):04d}",
                "ArrDelay": str(flight.get("arr_delay", "0.00")),
                "Cancelled": "1.00" if flight.get("cancelled") else "0.00",
                "Diverted": "0.00",
            }
        )
    return out


def write_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> Path:
    """A BTS-shaped CSV (an extra column BTS has, as BTS writes it) at ``path``."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Year", *COLUMNS], quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        for row in rows:
            writer.writerow({"Year": row["FlightDate"][:4], **row})
    return path


def zipped(rows: Sequence[Mapping[str, str]]) -> bytes:
    """The rows as a BTS month's zip."""
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=list(COLUMNS))
    writer.writeheader()
    writer.writerows(rows)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        bundle.writestr("On_Time_Synthetic.csv", text.getvalue())
        bundle.writestr("readme.html", "synthetic")
    return data.getvalue()


def world(raw: Path, first: date, last: date, seed: int = 1) -> set[date]:
    """A made-up history under ``raw`` (bts/, nbs/, obs/ as the fetchers keep them) for the two
    synthetic airports: AAA has a snow day now and then, cancels half its flights on one and few
    on others; BBB never sees snow. The snow days."""
    import random  # noqa: PLC0415

    import polars as pl  # noqa: PLC0415

    from snowlight.flights import bts  # noqa: PLC0415
    from snowlight.flights.live import rows_of  # noqa: PLC0415
    from snowlight.flights.nbs import parse  # noqa: PLC0415

    rng = random.Random(seed)  # noqa: S311 - made-up data, not a secret
    snowy: set[date] = set()
    by_month: dict[tuple[int, int], list[dict[str, str]]] = {}
    day = first
    (raw / "nbs").mkdir(parents=True, exist_ok=True)
    (raw / "obs").mkdir(parents=True, exist_ok=True)
    hours: list[dict[str, object]] = []
    while day <= last:
        snow = rng.random() < 0.15
        if snow:
            snowy.add(day)
        flights = []
        times = (
            600,
            610,
            700,
            1000,
            1010,
            1020,
            1300,
            1400,
            1500,
            1800,
            1810,
            1900,
            2200,
            2210,
            2230,
        )
        for number, dep_time in enumerate(times):
            for dep, arr in (("AAA", "BBB"), ("BBB", "AAA")):
                hit = snow and dep == "AAA" and rng.random() < 0.6
                hit = hit or rng.random() < 0.01
                late = not hit and rng.random() < (0.4 if snow and dep == "AAA" else 0.05)
                flights.append(
                    {
                        "carrier": "ZZ" if number % 2 else "YY",
                        "number": 100 + number,
                        "dep": dep,
                        "arr": arr,
                        "dep_time": dep_time,
                        "arr_time": dep_time + 200,
                        "cancelled": hit,
                        "dep_delay": "" if hit else ("60.00" if late else "0.00"),
                        "arr_delay": "" if hit else ("60.00" if late else "0.00"),
                    }
                )
        by_month.setdefault((day.year, day.month), []).extend(bts_rows(day, flights))
        # The 00Z run on the day (the evening before in AAA): snow through AAA's whole day.
        run = datetime(day.year, day.month, day.day, tzinfo=UTC_ZONE)
        heavy = [None if i % 2 else (60 if 12 <= HOURS[i] <= 30 else 0) for i in range(len(HOURS))]
        chance = [None if i % 2 else (90 if 12 <= HOURS[i] <= 30 else 0) for i in range(len(HOURS))]
        quiet = calm()
        aaa = calm(S06=heavy, P06=chance, PSN=[95] * len(HOURS)) if snow else quiet
        text = bulletin(run, {"KAAA": aaa, "KBBB": quiet})
        rows_of(list(parse(text))).write_parquet(raw / "nbs" / f"{run.date().isoformat()}.parquet")
        for hour in range(24):
            moment = datetime(day.year, day.month, day.day, hour, tzinfo=UTC_ZONE)
            hours.append(
                {
                    "station": "AAA",
                    "hour": moment,
                    "frz": False,
                    "snow": snow and 12 <= hour <= 23,
                    "thunder": False,
                    "fog": False,
                    "wind": False,
                }
            )
            hours.append(
                {
                    "station": "BBB",
                    "hour": moment,
                    "frz": False,
                    "snow": False,
                    "thunder": hour == 20,
                    "fog": False,
                    "wind": False,
                }
            )
        day += timedelta(days=1)
    for (year, month), rows in by_month.items():
        frame = pl.LazyFrame(rows, schema=dict.fromkeys(COLUMNS, pl.String))
        bts.write_month(raw / "bts", bts.Month(year, month), bts.reduce_rows(bts.read_rows(frame)))
    flags = pl.DataFrame(hours).with_columns(pl.col("hour").cast(pl.Datetime("us", "UTC")))
    for (year, month), part in flags.group_by(
        pl.col("hour").dt.year().alias("y"), pl.col("hour").dt.month().alias("m")
    ):
        part.write_parquet(raw / "obs" / f"{bts.Month(int(year), int(month)).key}.parquet")
    return snowy


UTC_ZONE = __import__("datetime").timezone.utc
