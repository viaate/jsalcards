"""A SYNTHETIC NBM bucket for the night chart's tests: 1-hour snowfall messages made with eccodes on
the NBM grid, their ``.idx`` files (with the percentile, probability and 6-hour lines a real one
holds beside the deterministic line) and S3 listings. Every value here is made up for the tests;
nothing is read from NOAA."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import eccodes  # type: ignore[import-untyped]
import numpy as np
import numpy.typing as npt

from predict import grib
from snowlight.predict import nbm, ndfd

GRID: Mapping[str, Any] = {
    "Nx": nbm.NX,
    "Ny": nbm.NY,
    "latitudeOfFirstGridPointInDegrees": nbm.LA1_DEG,
    "longitudeOfFirstGridPointInDegrees": nbm.LO1_DEG,
}
HOUR = timedelta(hours=1)


def coded(true_order: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """NBM grid values (rows south to north, west to east) in the file's order."""
    found = np.array(true_order, dtype=np.float64).reshape(nbm.NY, nbm.NX)
    found[1::2] = found[1::2, ::-1].copy()
    return found.reshape(-1)


def asnow(  # noqa: PLR0913 - one message's fields
    cycle: datetime,
    hour: int,
    metres: npt.NDArray[np.float64] | float = 0.0,
    *,
    grid: Mapping[str, Any] | None = None,
    parameter: tuple[int, int, int] = nbm.PARAMETER,
    span_hours: int = 1,
    statistic: int = 1,
) -> bytes:
    """A deterministic 1-hour snowfall message of ``cycle``'s forecast hour ``hour``: values in
    metres, in true order (flipped here) or one constant."""
    values = metres if isinstance(metres, float) else coded(metres)
    raw = grib.message(
        parameter,
        cycle,
        lead_hours=hour - span_hours,
        end=cycle + hour * HOUR,
        values=values if isinstance(values, float) else np.asarray(values),
        grid={**GRID, **(grid or {})},
        bits=16,
        span_hours=span_hours,
    )
    handle = eccodes.codes_new_from_message(raw)
    try:
        eccodes.codes_set(handle, "typeOfStatisticalProcessing", statistic)
        # Packed in whole millimetres, as NBM packs its snowfall (decimal scale 3).
        found = eccodes.codes_get_values(handle)
        eccodes.codes_set(handle, "decimalScaleFactor", 3)
        eccodes.codes_set_values(handle, found)
        return bytes(eccodes.codes_get_message(handle))
    finally:
        eccodes.codes_release(handle)


def core_file(cycle: datetime, hour: int, message: bytes, *, lines: int = 1) -> tuple[bytes, bytes]:
    """A core file holding filler messages and ``message`` (``lines`` deterministic lines in its
    ``.idx``: 1 as NBM has, 0 or 2 for the broken cases), and its ``.idx``."""
    filler = b"GRIB" + b"\0" * 60 + b"7777"
    stamp = f"d={cycle:%Y%m%d%H}"
    parts: list[tuple[str, bytes]] = [
        (f"APTMP:2 m above ground:{hour} hour fcst:", filler),
        *[
            (
                f"ASNOW:surface:{hour - 1}-{hour} hour acc@(fcst,dt=1 hour),missing=0:{p}% level",
                filler,
            )
            for p in (5, 50, 95)
        ],
    ]
    deterministic = f"ASNOW:surface:{hour - 1}-{hour} hour acc fcst:"
    parts += [(deterministic, message)] * lines
    parts += [
        (f"{deterministic}prob >0.00254:prob fcst 255/255", filler),
        (f"ASNOW:surface:{max(hour - 6, 0)}-{hour} hour acc fcst:", filler),
        ("TMP:2 m above ground:anl:", filler),
    ]
    body = bytearray()
    idx = []
    for n, (line, raw) in enumerate(parts, start=1):
        idx.append(f"{n}:{len(body)}:{stamp}:{line}")
        body += raw
    return bytes(body), ("\n".join(idx) + "\n").encode()


@dataclass
class Bucket:
    """Files by key, each with its LastModified; listings and reads as S3 answers them, counted."""

    files: dict[str, tuple[bytes, datetime]] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)
    fail: Callable[[str], bool] = field(default=lambda _url: False)

    def add_cycle(
        self,
        cycle: datetime,
        hours: Mapping[int, bytes],
        posted: datetime,
        *,
        late: Mapping[int, datetime] | None = None,
        lines: int = 1,
    ) -> None:
        """A cycle's CONUS core files (and a filler Alaska file per hour, as a listing holds)."""
        for hour, message in hours.items():
            body, idx = core_file(cycle, hour, message, lines=lines)
            when = (late or {}).get(hour, posted)
            key = nbm.core_key(cycle, hour)
            self.files[key] = (body, when)
            self.files[f"{key}.idx"] = (idx, when + timedelta(seconds=3))
            alaska = key.replace(".co.", ".ak.")
            self.files[alaska] = (b"", posted)

    def get(self, url: str) -> bytes:
        self.requests.append(url)
        if self.fail(url):
            raise ndfd.NdfdError(f"HTTP 503 for {url}")
        if "?list-type=2" in url:
            return self._listing(url)
        key = url.removeprefix(f"{nbm.BUCKET_ROOT}/")
        if key not in self.files:
            raise ndfd.NotFoundError(f"HTTP 404 for {url}")
        return self.files[key][0]

    def ranged(self, url: str) -> ndfd.Ranged:
        key = url.removeprefix(f"{nbm.BUCKET_ROOT}/")

        def read(offset: int, size: int) -> bytes:
            self.requests.append(f"{url} [{offset}+{size}]")
            if self.fail(url):
                raise ndfd.ShortReadError(f"cut short: {url}")
            return self.files[key][0][offset : offset + size]

        return read

    def _listing(self, url: str) -> bytes:
        query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        prefix, after, most = query["prefix"], query.get("start-after", ""), int(query["max-keys"])
        keys = sorted(k for k in self.files if k.startswith(prefix) and k > after)[:most]
        blocks = "".join(
            f"<Contents><Key>{k}</Key><LastModified>{self.files[k][1]:%Y-%m-%dT%H:%M:%S}.000Z"
            f"</LastModified><Size>{len(self.files[k][0])}</Size></Contents>"
            for k in keys
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?><ListBucketResult><Name>noaa-nbm-grib2-pds'
            f"</Name><Prefix>{prefix}</Prefix>{blocks}</ListBucketResult>"
        ).encode()
