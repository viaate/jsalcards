"""The National Blend of Models' station text guidance (NBS): the forecast weather by airport.

Each run's bulletin is one public text file with every station: ``blend_nbstx.tHHz`` under
``blend.YYYYMMDD/HH/text/`` in the public NBM bucket on AWS (no key), the same file for the
history (runs back to mid 2020) and the live job, so the model learns from exactly what it
reads live. A run gives 3-hourly values from 6 to 72 hours after it (6-hourly for the 6-hour
amounts and chances).

A station's section starts with a line ``KMCI    NBM V4.2 NBS GUIDANCE    1/05/2025  1200 UTC``,
then a ``DT`` line, a ``UTC`` line, an ``FHR`` line (hours after the run) and one line per
element, each value right-aligned in three characters under its hour. A blank cell is no value;
``-88`` in the ceiling row is no ceiling.

Elements read (units as the bulletin gives them, converted here):

* ``TMP`` temperature (F), ``WSP`` wind and ``GST`` gust (knots);
* ``P06`` chance of precipitation in the 6 hours ending then (%), ``PZR`` and ``PSN`` the chance
  that precipitation is freezing rain or snow (%), ``T03`` chance of thunder in the 3 hours
  ending then (%);
* ``S06`` snow (tenths of an inch) and ``I06`` ice (hundredths of an inch) in the 6 hours ending
  then;
* ``VIS`` visibility (tenths of a mile) and ``CIG`` ceiling (hundreds of feet).
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Final

BUCKET: Final = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"

ELEMENTS: Final = ("TMP", "WSP", "GST", "P06", "PZR", "PSN", "T03", "S06", "I06", "VIS", "CIG")
NO_CEILING: Final = -88
CELL: Final = 3
FIRST_CELL: Final = 5
MAX_HOUR: Final = 400
"""No bulletin hour lies past this (the NBS text runs to 264 hours)."""

_HEADER = re.compile(
    r"^\s*(?P<station>[A-Z0-9]{3,6})\s+NBM(?: V[\d.]+)?\s+NBS GUIDANCE\s+"
    r"(?P<month>\d{1,2})/(?P<day>\d{2})/(?P<year>\d{4})\s+(?P<hour>\d{2})00 UTC"
)


def run_url(run: datetime) -> str:
    """The bulletin of the run at ``run`` (a whole UTC hour)."""
    day = run.strftime("%Y%m%d")
    return f"{BUCKET}/blend.{day}/{run.hour:02d}/text/blend_nbstx.t{run.hour:02d}z"


@dataclass(frozen=True, slots=True)
class StationRun:
    """One station's forecast from one run."""

    station: str
    run: datetime
    valid: tuple[datetime, ...]
    """Each column's time (UTC)."""
    values: dict[str, tuple[int | None, ...]] = field(default_factory=dict)
    """Each element's value per column (``None``: no value in that column)."""

    def get(self, element: str) -> tuple[int | None, ...]:
        """An element's row, all ``None`` when the bulletin did not give it."""
        return self.values.get(element, (None,) * len(self.valid))


def _cells(line: str, count: int) -> tuple[int | None, ...]:
    out: list[int | None] = []
    for index in range(count):
        start = FIRST_CELL + index * CELL
        text = line[start : start + CELL].strip()
        try:
            out.append(int(text) if text else None)
        except ValueError:
            out.append(None)
    return tuple(out)


def _section(station: str, run: datetime, lines: list[str]) -> StationRun | None:
    """One station's block; ``None`` when it does not read (that block alone is skipped)."""
    fhr = next((line for line in lines if line[1:4] == "FHR"), None)
    if fhr is None:
        return None
    try:
        hours = [int(text) for text in fhr[FIRST_CELL:].split()]
    except ValueError:
        return None
    if not hours or not all(0 <= hour <= MAX_HOUR for hour in hours):
        return None
    valid = tuple(run + timedelta(hours=hour) for hour in hours)
    values: dict[str, tuple[int | None, ...]] = {}
    for line in lines:
        label = line[1:4]
        if label in ELEMENTS:
            values[label] = _cells(line.ljust(FIRST_CELL + CELL * len(hours)), len(hours))
    return StationRun(station=station, run=run, valid=valid, values=values)


def parse(
    text: str | Iterable[str], wanted: frozenset[str] | None = None, run: datetime | None = None
) -> Iterator[StationRun]:
    """The stations of a bulletin (only ``wanted`` ones when given), in file order; a station
    block that does not read is skipped, never the rest: hours that are not numbers or lie past
    :data:`MAX_HOUR`, or (with ``run``, the run the bulletin was asked for) a header naming
    another run."""
    lines = text.splitlines() if isinstance(text, str) else (line.rstrip("\n") for line in text)
    current: tuple[str, datetime] | None = None
    body: list[str] = []
    for line in lines:
        header = _HEADER.match(line)
        if header is not None:
            if current is not None:
                section = _section(current[0], current[1], body)
                if section is not None:
                    yield section
            station = header["station"]
            if wanted is not None and station not in wanted:
                current = None
                continue
            try:
                stamp = datetime(
                    int(header["year"]),
                    int(header["month"]),
                    int(header["day"]),
                    int(header["hour"]),
                    tzinfo=UTC,
                )
            except ValueError:  # a header that does not read: its block is skipped
                current = None
                continue
            if run is not None and stamp != run:
                current = None
                continue
            current, body = (station, stamp), []
        elif current is not None:
            body.append(line)
    if current is not None:
        section = _section(current[0], current[1], body)
        if section is not None:
            yield section


def runs_between(first: date, last: date, hour: int = 0) -> Iterator[datetime]:
    """The runs at ``hour`` UTC on every day from ``first`` to ``last``."""
    day = first
    while day <= last:
        yield datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
        day += timedelta(days=1)
