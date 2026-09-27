"""A read-only look at the station registry, for two optional checks of the priority.

The station registry (``pipeline/config/sources/<platform>.yaml``) belongs to the
station builders; this package never writes it and does not import their code.
It reads only what its checks need, with a reader of its own:

* ``platform.id`` of each file, and of each entry under ``stations``: ``id``,
  ``platform``, ``call_sign``, ``status``, ``dma`` and ``counties`` (``null``, or
  ``basis`` and ``fips``, a list of five-digit strings).

The checks (both reported in the build's manifest and method note, neither
changing a weight or a rank):

* :func:`market_agreement`: every DMA-based county list in the registry is
  compared with the market's counties as :mod:`snowlight.weights.markets` reads
  the pinned crosswalk, so the station priority and the registry are known to use
  the same markets;
* :func:`by_call_sign` feeds :func:`snowlight.weights.priority.gray_cover`, which
  looks up the records the priority leaves out as Gray's.

The registry is optional: when its folder is missing or a file does not read, the
build says so in its outputs and goes on (:class:`RegistryReadError`).
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.output import JSONValue
from snowlight.weights.cache import PIPELINE_ROOT
from snowlight.weights.markets import DmaCounties

DEFAULT_REGISTRY_DIR = PIPELINE_ROOT / "config" / "sources"
DMA_BASIS = "dma"
GRAY_PLATFORM = "gray"
_FIPS_LENGTH = 5


class RegistryReadError(ValueError):
    """A registry file is missing or does not have the fields read here."""


@dataclass(frozen=True, slots=True)
class RegistryStation:
    """The fields of one registry station that the checks read."""

    id: str
    platform: str
    call_sign: str
    status: str
    dma: str | None
    basis: str | None
    """The ``counties.basis`` (``None`` when the station has no county list)."""
    fips: tuple[str, ...]
    """The ``counties.fips`` in the file's order (empty when there is no list)."""


def _text(entry: Mapping[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistryReadError(f"{where}: {key} is not a non-empty string")
    return value


def _optional_text(entry: Mapping[str, Any], key: str, where: str) -> str | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RegistryReadError(f"{where}: {key} is not a string")
    return value


def _counties(entry: Mapping[str, Any], where: str) -> tuple[str | None, tuple[str, ...]]:
    counties = entry.get("counties")
    if counties is None:
        return None, ()
    if not isinstance(counties, dict):
        raise RegistryReadError(f"{where}: counties is neither null nor a mapping")
    basis = _text(counties, "basis", where)
    codes = counties.get("fips")
    if not isinstance(codes, list):
        raise RegistryReadError(f"{where}: counties.fips is not a list")
    fips: list[str] = []
    for code in codes:
        if not (isinstance(code, str) and len(code) == _FIPS_LENGTH and code.isdigit()):
            raise RegistryReadError(f"{where}: county code {code!r} is not five digits")
        fips.append(code)
    return basis, tuple(fips)


def _station(entry: object, file_platform: str, where: str) -> RegistryStation:
    if not isinstance(entry, dict):
        raise RegistryReadError(f"{where}: a station entry is not a mapping")
    station_id = _text(entry, "id", where)
    where = f"{where} {station_id}"
    platform = _text(entry, "platform", where)
    if platform != file_platform:
        raise RegistryReadError(f"{where}: platform {platform!r} in the {file_platform} file")
    basis, fips = _counties(entry, where)
    return RegistryStation(
        id=station_id,
        platform=platform,
        call_sign=_text(entry, "call_sign", where),
        status=_text(entry, "status", where),
        dma=_optional_text(entry, "dma", where),
        basis=basis,
        fips=fips,
    )


def read_registry(folder: Path = DEFAULT_REGISTRY_DIR) -> list[RegistryStation]:
    """Read every station of every ``*.yaml`` file in ``folder`` (files in name order).

    Raises:
        RegistryReadError: no file, a file that is not YAML or lacks a field read
            here, or a station id used twice.
    """
    paths = sorted(folder.glob("*.yaml"))
    if not paths:
        raise RegistryReadError(f"no registry files in {folder}")
    stations: list[RegistryStation] = []
    seen: set[str] = set()
    for path in paths:
        try:
            document: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
            raise RegistryReadError(f"{path.name}: {error}") from error
        if not isinstance(document, dict):
            raise RegistryReadError(f"{path.name}: not a mapping")
        platform = document.get("platform")
        if not isinstance(platform, dict):
            raise RegistryReadError(f"{path.name}: no platform block")
        platform_id = _text(platform, "id", path.name)
        entries = document.get("stations")
        if not isinstance(entries, list):
            raise RegistryReadError(f"{path.name}: stations is not a list")
        for entry in entries:
            station = _station(entry, platform_id, path.name)
            if station.id in seen:
                raise RegistryReadError(f"{path.name}: station id {station.id!r} is used twice")
            seen.add(station.id)
            stations.append(station)
    return stations


def by_call_sign(stations: Sequence[RegistryStation]) -> dict[str, list[RegistryStation]]:
    """Group the stations by call sign, Gray's entry first where a call sign has several.

    A call sign can sit on two platforms (a station the research found under one
    owner and the registry also lists under Gray); the Gray check wants Gray's.
    """
    grouped: dict[str, list[RegistryStation]] = defaultdict(list)
    for station in stations:
        grouped[station.call_sign].append(station)
    return {
        call: sorted(entries, key=lambda s: (s.platform != GRAY_PLATFORM, s.id))
        for call, entries in sorted(grouped.items())
    }


def market_agreement(stations: Sequence[RegistryStation], dmas: DmaCounties) -> JSONValue:
    """Compare every DMA-based county list in the registry with the crosswalk read here.

    A list agrees when it holds exactly the market's counties.
    """
    compared = 0
    differing: list[JSONValue] = []
    for station in stations:
        if station.basis != DMA_BASIS:
            continue
        compared += 1
        listed = set(station.fips)
        market = set(dmas.by_dma.get(station.dma or "", ()))
        if station.dma in dmas.by_dma and listed == market and len(station.fips) == len(listed):
            continue
        differing.append(
            {
                "station": station.id,
                "dma": station.dma,
                "in_crosswalk": station.dma in dmas.by_dma,
                "registry_counties": len(station.fips),
                "market_counties": len(market),
                "only_in_registry": list[JSONValue](sorted(listed - market)),
                "only_in_market": list[JSONValue](sorted(market - listed)),
            }
        )
    return {
        "stations_with_dma_county_lists": compared,
        "agreeing": compared - len(differing),
        "differing": differing,
    }
