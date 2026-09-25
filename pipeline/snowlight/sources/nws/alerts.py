"""Active alerts from the NWS API (https://api.weather.gov/alerts/active).

The request asks for actual (not test or exercise) alerts on land zones and is
made conditionally: the cached response's ``ETag`` goes back as
``If-None-Match``, and a ``304 Not Modified`` reuses the cached bytes. The raw
response stays in the cache with its provenance sidecar so every published
alert can be traced to the exact bytes it came from.

:func:`parse_active` turns the GeoJSON ``FeatureCollection`` into
:class:`NwsAlert` records, keeping only the fields this project uses: no
headline, description, instruction or web link is read.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import shapely
from shapely.geometry import shape

from snowlight.sources.nws.http import CachedFile, HttpCache
from snowlight.sources.nws.shapefile import Polygonal, polygonal
from snowlight.sources.nws.vtec import Vtec, VtecError, parse_vtec

ACTIVE_URL = "https://api.weather.gov/alerts/active?status=actual&region_type=land"
ACCEPT = "application/geo+json"
_ZONE_URL = re.compile(r"^https://api\.weather\.gov/zones/([a-z]+)/([A-Z]{2}[CZ]\d{3})$")


class AlertFormatError(ValueError):
    """The API response is not the GeoJSON this module expects."""


@dataclass(frozen=True, slots=True)
class ZoneRef:
    """One affected zone: its NWS zone type (``forecast``, ``county``, ``fire``...) and UGC."""

    kind: str
    ugc: str


@dataclass(frozen=True, slots=True)
class NwsAlert:
    """The fields of one active alert that this project uses."""

    id: str
    event: str
    status: str
    message_type: str
    severity: str
    sent: datetime
    effective: datetime | None
    onset: datetime | None
    expires: datetime | None
    ends: datetime | None
    geometry: Polygonal | None
    ugc: tuple[str, ...]
    zones: tuple[ZoneRef, ...]
    unparsed_zones: tuple[str, ...]
    vtec: tuple[Vtec, ...]


@dataclass(frozen=True, slots=True)
class ActiveFeed:
    """A parsed ``/alerts/active`` response."""

    updated: datetime | None
    alerts: tuple[NwsAlert, ...]


def _time(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AlertFormatError(f"{field} is not a string: {value!r}")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as error:
        raise AlertFormatError(f"{field} is not an ISO 8601 time: {value!r}") from error
    if moment.tzinfo is None:
        raise AlertFormatError(f"{field} has no UTC offset: {value!r}")
    return moment.astimezone(UTC)


def _text(props: dict[str, object], field: str) -> str:
    value = props.get(field)
    if not isinstance(value, str):
        raise AlertFormatError(f"alert field {field!r} is missing or not text")
    return value


def _strings(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AlertFormatError(f"{field} is not a list of strings")
    return [str(item) for item in value]


def _geometry(value: object) -> Polygonal | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AlertFormatError("geometry is not a GeoJSON object")
    try:
        geometry = shape(value)
    except (ValueError, TypeError, AttributeError, KeyError, IndexError) as error:
        raise AlertFormatError(f"geometry cannot be read: {error}") from error
    if not geometry.is_valid:
        geometry = shapely.make_valid(geometry)
    return polygonal(geometry)


def parse_alert(feature: object) -> NwsAlert:
    """Parse one GeoJSON feature of the active-alerts collection.

    Raises:
        AlertFormatError: a field this project relies on is missing or malformed.
    """
    if not isinstance(feature, dict):
        raise AlertFormatError("feature is not an object")
    props = feature.get("properties")
    if not isinstance(props, dict):
        raise AlertFormatError("feature has no properties")
    alert_id = _text(props, "id")
    zones: list[ZoneRef] = []
    unparsed: list[str] = []
    for url in _strings(props.get("affectedZones"), "affectedZones"):
        match = _ZONE_URL.match(url)
        if match is None:
            unparsed.append(url)
        else:
            zones.append(ZoneRef(match.group(1), match.group(2)))
    geocode = props.get("geocode")
    ugc = _strings(geocode.get("UGC"), "geocode.UGC") if isinstance(geocode, dict) else []
    parameters = props.get("parameters")
    vtec: list[Vtec] = []
    if isinstance(parameters, dict):
        for text in _strings(parameters.get("VTEC"), "parameters.VTEC"):
            try:
                vtec.append(parse_vtec(text))
            except VtecError as error:
                raise AlertFormatError(f"alert {alert_id}: {error}") from error
    sent = _time(props.get("sent"), "sent")
    if sent is None:
        raise AlertFormatError(f"alert {alert_id} has no sent time")
    return NwsAlert(
        id=alert_id,
        event=_text(props, "event"),
        status=_text(props, "status"),
        message_type=_text(props, "messageType"),
        severity=_text(props, "severity"),
        sent=sent,
        effective=_time(props.get("effective"), "effective"),
        onset=_time(props.get("onset"), "onset"),
        expires=_time(props.get("expires"), "expires"),
        ends=_time(props.get("ends"), "ends"),
        geometry=_geometry(feature.get("geometry")),
        ugc=tuple(ugc),
        zones=tuple(zones),
        unparsed_zones=tuple(unparsed),
        vtec=tuple(vtec),
    )


def parse_active(payload: bytes) -> ActiveFeed:
    """Parse the body of an ``/alerts/active`` response.

    Raises:
        AlertFormatError: the body is not a GeoJSON ``FeatureCollection`` of alerts.
    """
    try:
        document = json.loads(payload)
    except ValueError as error:
        raise AlertFormatError(f"response is not JSON: {error}") from error
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise AlertFormatError("response is not a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list):
        raise AlertFormatError("response has no features list")
    return ActiveFeed(
        updated=_time(document.get("updated"), "updated"),
        alerts=tuple(parse_alert(feature) for feature in features),
    )


def fetch_active(
    cache: HttpCache, cache_dir: Path, *, max_age: timedelta = timedelta(0)
) -> tuple[ActiveFeed, CachedFile]:
    """Fetch (conditionally) and parse the active alerts.

    The response is cached at ``<cache_dir>/api.weather.gov/alerts/active.geojson``.
    """
    dest = cache_dir / "api.weather.gov" / "alerts" / "active.geojson"
    fetched = cache.fetch(ACTIVE_URL, dest, max_age=max_age, accept=ACCEPT)
    return parse_active(fetched.path.read_bytes()), fetched
