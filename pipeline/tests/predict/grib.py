"""Synthetic NDFD files for the forecast tests, made with eccodes on the NDFD 2.5 km grid.

Every value here is made up for the tests (no real forecast is read or kept): constant fields,
a ramp of cell numbers, a hole of missing cells.
"""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

import eccodes  # type: ignore[import-untyped]
import numpy as np
import numpy.typing as npt

from snowlight.predict import ndfd

MISSING: Final = 9999.0
_BASE: Final[Mapping[str, Any]] = {
    "shapeOfTheEarth": 1,
    "scaleFactorOfRadiusOfSphericalEarth": 0,
    "scaledValueOfRadiusOfSphericalEarth": 6371200,
    "Nx": ndfd.NX,
    "Ny": ndfd.NY,
    "latitudeOfFirstGridPointInDegrees": ndfd.LA1_DEG,
    "longitudeOfFirstGridPointInDegrees": ndfd.LO1_DEG,
    "LaDInDegrees": ndfd.LATIN_DEG,
    "LoVInDegrees": ndfd.LOV_DEG,
    "Latin1InDegrees": ndfd.LATIN_DEG,
    "Latin2InDegrees": ndfd.LATIN_DEG,
    "DxInMetres": ndfd.DX_M,
    "DyInMetres": ndfd.DX_M,
    "scanningMode": ndfd.SCANNING_MODE,
}


def coded(true_order: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Grid values (rows south to north, west to east) in the file's order: odd rows reversed."""
    grid = np.array(true_order, dtype=np.float64).reshape(ndfd.NY, ndfd.NX)
    grid[1::2] = grid[1::2, ::-1].copy()
    return grid.reshape(-1)


def message(  # noqa: PLR0913 - one message's fields
    parameter: tuple[int, int, int],
    reference: datetime,
    *,
    lead_hours: float,
    end: datetime | None = None,
    values: npt.NDArray[np.float64] | float = 0.0,
    grid: Mapping[str, Any] | None = None,
    bits: int = 24,
    span_hours: float = 6.0,
) -> bytes:
    """One GRIB2 message: template 4.8 (a ``span_hours`` period ending at ``end``, stamped at
    reference + lead) when ``end`` is given, else 4.0 (valid at reference + lead). NDFD stamps
    its periods two ways (:class:`snowlight.predict.ndfd.PeriodStamp`): lead to the period's
    start (the first at 0, the reference time) or, until 2018-10-30, to its end; the span is 6
    hours either way. ``values`` are in true order (flipped here) or one constant; NaN is
    written as missing."""
    keys = {**_BASE, **(grid or {})}
    count = int(keys["Nx"]) * int(keys["Ny"])
    handle = eccodes.codes_grib_new_from_samples("GRIB2")
    try:
        eccodes.codes_set(handle, "gridDefinitionTemplateNumber", 30)
        for key, value in keys.items():
            eccodes.codes_set(handle, key, value)
        eccodes.codes_set(handle, "productDefinitionTemplateNumber", 8 if end else 0)
        discipline, category, number = parameter
        eccodes.codes_set(handle, "discipline", discipline)
        eccodes.codes_set(handle, "parameterCategory", category)
        eccodes.codes_set(handle, "parameterNumber", number)
        eccodes.codes_set(handle, "dataDate", int(reference.strftime("%Y%m%d")))
        eccodes.codes_set(handle, "dataTime", int(reference.strftime("%H%M")))
        eccodes.codes_set(handle, "indicatorOfUnitOfTimeRange", 0)
        eccodes.codes_set(handle, "forecastTime", round(lead_hours * 60))
        if end is not None:
            for name, value in (
                ("year", end.year),
                ("month", end.month),
                ("day", end.day),
                ("hour", end.hour),
                ("minute", end.minute),
                ("second", 0),
            ):
                eccodes.codes_set(handle, f"{name}OfEndOfOverallTimeInterval", value)
            eccodes.codes_set(handle, "indicatorOfUnitForTimeRange", 0)
            eccodes.codes_set(handle, "lengthOfTimeRange", round(span_hours * 60))
        eccodes.codes_set(handle, "packingType", "grid_simple")
        eccodes.codes_set(handle, "bitsPerValue", bits)
        if isinstance(values, float):
            data = np.full(count, values)
        else:
            data = coded(values) if values.shape[0] == ndfd.NX * ndfd.NY else values
        holes = np.isnan(data)
        if holes.any():
            eccodes.codes_set(handle, "missingValue", MISSING)
            eccodes.codes_set(handle, "bitmapPresent", 1)
            data = np.where(holes, MISSING, data)
        eccodes.codes_set_values(handle, data)
        return bytes(eccodes.codes_get_message(handle))
    finally:
        eccodes.codes_release(handle)


def framed(messages: Iterable[bytes], heading: str = "YSUZ98 KWBN 060246") -> bytes:
    """Messages as the WMO-framed AWS and tgftp files hold them."""
    out = bytearray()
    for raw in messages:
        out += f"****{len(raw) + 24:010d}****\n{heading}\r\r\n".encode()
        out += raw
        out += b"\r\r\n"
    return bytes(out)


def utc(text: str) -> datetime:
    """A UTC time from ``YYYY-MM-DDTHH:MM``."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def as_probability(raw: bytes, end: datetime, span_hours: float) -> bytes:
    """A template 4.8 message (:func:`message`) as template 4.9, the chance of precipitation's:
    the same interval, the probability octets before its end."""
    handle = eccodes.codes_new_from_message(raw)
    try:
        eccodes.codes_set(handle, "productDefinitionTemplateNumber", 9)
        for name, value in (
            ("year", end.year),
            ("month", end.month),
            ("day", end.day),
            ("hour", end.hour),
            ("minute", end.minute),
            ("second", 0),
        ):
            eccodes.codes_set(handle, f"{name}OfEndOfOverallTimeInterval", value)
        eccodes.codes_set(handle, "indicatorOfUnitForTimeRange", 0)
        eccodes.codes_set(handle, "lengthOfTimeRange", round(span_hours * 60))
        return bytes(eccodes.codes_get_message(handle))
    finally:
        eccodes.codes_release(handle)


def with_strings(raw: bytes, strings: Iterable[str], bits: int = 7) -> bytes:
    """A message with NDFD's weather strings in a section 2 put after its section 1 (local use,
    version 1, one group of simple packed characters, each string ending in a zero)."""
    chars = b"".join(text.encode("ascii") + b"\0" for text in strings)
    packed = np.packbits(
        np.unpackbits(np.frombuffer(chars, dtype=np.uint8)[:, None], axis=1)[:, 8 - bits :]
    ).tobytes()
    body = (
        bytes([1])
        + (1).to_bytes(2, "big")
        + len(chars).to_bytes(4, "big")
        + bytes(4)  # reference value 0.0
        + bytes(2)  # binary scale factor 0
        + bytes([bits, 1])
        + packed
    )
    section = (len(body) + 5).to_bytes(4, "big") + bytes([2]) + body
    first = int.from_bytes(raw[16:20], "big")
    out = bytearray(raw[: 16 + first] + section + raw[16 + first :])
    out[8:16] = len(out).to_bytes(8, "big")
    return bytes(out)
