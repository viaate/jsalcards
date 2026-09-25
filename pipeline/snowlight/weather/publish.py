"""The published live alerts file, ``live/alerts.json``, and its internal manifest.

Published shape (compact UTF-8 JSON, keys sorted; every time is UTC ISO 8601
with a ``Z``)::

    {
      "schema": 1,
      "asOf": "2026-09-24T23:43:14Z",      # when the NWS generated the feed
      "generatedAt": "2026-09-24T23:45:02Z",
      "alerts": [
        {
          "id": "3f9a1c2b4d5e",             # 12 hex chars, stable for the same member alerts
          "event": "Winter Storm Warning",   # NWS event name, from the allowlist
          "hazard": "winter",               # winter|cold|flood|tropical|heat|wind|severe
          "level": "warning",               # warning|watch|advisory
          "severity": "Severe",             # CAP severity: Extreme|Severe|Moderate|Minor|Unknown
          "onset": "2026-09-25T06:00:00Z",   # when it applies from
          "ends": "2026-09-26T00:00:00Z",    # when it applies until; null = until further notice
          "bbox": [-97.1, 35.2, -94.8, 37.0],  # [west, south, east, north] of the polygons
          "polygons": [[[[-97.1, 35.2], ...]]] # GeoJSON MultiPolygon coordinates
        }
      ]
    }

``polygons`` follows RFC 7946: ``[lon, lat]`` pairs, closed rings, exterior
rings counter-clockwise and holes clockwise, coordinates on a 0.001 degree grid
(finer only for an area too small to survive that grid). Alerts that share an
event, severity, onset and end are merged into one entry whose polygons are the
union of theirs, so neighbouring offices' identical warnings draw as one shape.
Entries are ordered warnings, then watches, then advisories, then by event,
onset, end and id.

The file never holds alert text, links, identifiers of the issuing service or
source names. Polygons are simplified (topology preserved) with the smallest
tolerance, from :data:`TOLERANCES`, that fits the whole file in the size budget
(:data:`DEFAULT_MAX_BYTES` unless the caller sets another). Parts smaller than
a square :data:`SPECK_SIDE` tolerances on a side (marsh islets along a coastal
flood zone, say: about 400 m across at the finest tolerance) are left out as too
small to see at the scale that tolerance serves; an entry always keeps its
largest part. The exact footprints stay available to the pipeline's own
weather check, which never uses these simplified shapes.
The tolerance used and every source record behind each entry go to the
internal manifest instead, which is never published.
"""

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import shapely
from shapely.geometry import LinearRing, MultiPolygon, Polygon

from snowlight.output import JSONValue, dumps_json
from snowlight.sources.nws.http import iso_utc
from snowlight.sources.nws.shapefile import Polygonal, polygonal
from snowlight.weather.live import LiveAlert

SCHEMA_VERSION = 1
DEFAULT_MAX_BYTES = 1_000_000
TOLERANCES: tuple[float, ...] = (0.002, 0.004, 0.008, 0.016, 0.032, 0.064)
GRIDS: tuple[float, ...] = (0.001, 0.0001, 0.00001)
SPECK_SIDE = 2.0
LEVEL_ORDER = {"warning": 0, "watch": 1, "advisory": 2}
FORBIDDEN_IN_PUBLISHED: tuple[str, ...] = (
    "http",
    "www.",
    "weather.gov",
    "noaa",
    "national weather service",
    "nws",
    "mesonet",
    "iastate",
    "urn:oid",
    "vtec",
)


class BudgetError(RuntimeError):
    """The alerts do not fit the size budget even at the coarsest tolerance."""


class PublishedContentError(RuntimeError):
    """A published file would contain text that must never be published."""


@dataclass(frozen=True, slots=True)
class AlertGroup:
    """Alerts drawn as one published entry."""

    id: str
    members: tuple[LiveAlert, ...]
    footprint: Polygonal

    @property
    def first(self) -> LiveAlert:
        """The member whose fields the entry shows (all members share them)."""
        return self.members[0]


def group_alerts(alerts: Sequence[LiveAlert]) -> list[AlertGroup]:
    """Merge alerts with the same event, severity, onset and end; order the groups."""
    buckets: dict[tuple[str, str, datetime, datetime | None], list[LiveAlert]] = defaultdict(list)
    for alert in alerts:
        key = (alert.kind.event, alert.alert.severity, alert.start, alert.end)
        buckets[key].append(alert)
    groups: list[AlertGroup] = []
    for members in buckets.values():
        members.sort(key=lambda item: item.alert.id)
        ids = "\n".join(item.alert.id for item in members)
        pieces = [item.footprint for item in members]
        footprint = pieces[0] if len(pieces) == 1 else polygonal(shapely.union_all(pieces))
        if footprint is None:  # pragma: no cover - a union of polygons is polygonal
            continue
        digest = hashlib.sha256(ids.encode("utf-8")).hexdigest()[:12]
        groups.append(AlertGroup(digest, tuple(members), footprint))
    groups.sort(
        key=lambda group: (
            LEVEL_ORDER[group.first.kind.level],
            group.first.kind.event,
            group.first.start,
            group.first.end is None,
            group.first.end or group.first.start,
            group.id,
        )
    )
    return groups


def _ring(ring: LinearRing, digits: int) -> list[JSONValue]:
    coords = np.round(shapely.get_coordinates(ring), digits)
    return [[float(x), float(y)] for x, y in coords.tolist()]


def _without_specks(geometry: Polygonal, min_area: float) -> Polygonal:
    parts = [part for part in shapely.get_parts(geometry) if isinstance(part, Polygon)]
    kept = [part for part in parts if part.area >= min_area]
    if not kept:
        kept = [max(parts, key=lambda part: part.area)]
    return kept[0] if len(kept) == 1 else MultiPolygon(kept)


def _encode(geometry: Polygonal, tolerance: float) -> tuple[list[JSONValue], list[JSONValue]]:
    simplified = polygonal(shapely.simplify(geometry, tolerance, preserve_topology=True))
    if simplified is None:  # pragma: no cover - topology-preserving simplification keeps area
        return [], []
    simplified = _without_specks(simplified, (SPECK_SIDE * tolerance) ** 2)
    for grid in GRIDS:
        snapped = polygonal(shapely.set_precision(simplified, grid))
        if snapped is None:
            continue
        oriented = shapely.orient_polygons(snapped, exterior_cw=False)
        parts: list[Polygon] = (
            list(oriented.geoms) if isinstance(oriented, MultiPolygon) else [oriented]
        )
        digits = len(f"{grid:.10f}".rstrip("0").split(".")[1])
        polygons: list[JSONValue] = [
            [
                _ring(part.exterior, digits),
                *(_ring(hole, digits) for hole in part.interiors),
            ]
            for part in parts
        ]
        west, south, east, north = oriented.bounds
        bbox: list[JSONValue] = [
            round(west, digits),
            round(south, digits),
            round(east, digits),
            round(north, digits),
        ]
        return polygons, bbox
    return [], []


def _time(moment: datetime | None) -> str | None:
    return None if moment is None else iso_utc(moment)


def build_document(
    groups: Sequence[AlertGroup],
    *,
    as_of: datetime | None,
    generated_at: datetime,
    tolerance: float,
) -> tuple[dict[str, JSONValue], list[str]]:
    """Return the published document at one tolerance, and the ids too small to draw."""
    entries: list[JSONValue] = []
    too_small: list[str] = []
    for group in groups:
        polygons, bbox = _encode(group.footprint, tolerance)
        if not polygons:
            too_small.append(group.id)
            continue
        first = group.first
        entries.append(
            {
                "id": group.id,
                "event": first.kind.event,
                "hazard": first.kind.hazard,
                "level": first.kind.level,
                "severity": first.alert.severity,
                "onset": _time(first.start),
                "ends": _time(first.end),
                "bbox": bbox,
                "polygons": polygons,
            }
        )
    document: dict[str, JSONValue] = {
        "schema": SCHEMA_VERSION,
        "asOf": _time(as_of),
        "generatedAt": iso_utc(generated_at),
        "alerts": entries,
    }
    return document, too_small


@dataclass(frozen=True, slots=True)
class Rendered:
    """The published bytes and how they were made."""

    data: bytes
    tolerance: float
    alerts: int
    too_small: tuple[str, ...]


def check_published(data: bytes) -> None:
    """Refuse bytes that name a source, carry a link or an issuing-service identifier.

    Raises:
        PublishedContentError: a forbidden string occurs in ``data``.
    """
    text = data.decode("utf-8").lower()
    found = [needle for needle in FORBIDDEN_IN_PUBLISHED if needle in text]
    if found:
        raise PublishedContentError(f"published alerts would contain {found}")


def render(
    groups: Sequence[AlertGroup],
    *,
    as_of: datetime | None,
    generated_at: datetime,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Rendered:
    """Serialize ``groups`` at the smallest tolerance that fits ``max_bytes``.

    Raises:
        BudgetError: the file is too large even at the coarsest tolerance.
        PublishedContentError: the file would contain a forbidden string.
    """
    size = 0
    for tolerance in TOLERANCES:
        document, too_small = build_document(
            groups, as_of=as_of, generated_at=generated_at, tolerance=tolerance
        )
        data = dumps_json(document)
        size = len(data)
        if size <= max_bytes:
            check_published(data)
            alerts = document["alerts"]
            count = len(alerts) if isinstance(alerts, list) else 0
            return Rendered(data, tolerance, count, tuple(too_small))
    raise BudgetError(
        f"{len(groups)} alerts take {size} bytes at tolerance {TOLERANCES[-1]}, "
        f"over the {max_bytes}-byte budget"
    )
