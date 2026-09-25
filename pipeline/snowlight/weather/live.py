"""Select today's school-relevant alerts from the NWS feed and resolve where they apply.

:func:`select_alerts` keeps an alert only when all of these hold, and records
the reason for every alert it drops:

1. its CAP ``status`` is ``Actual``, its ``messageType`` is ``Alert`` or
   ``Update`` (a ``Cancel`` ends an alert rather than issuing one), and not all
   of its VTEC actions are ``CAN`` or ``UPG`` (cancelled, or replaced by the
   upgraded alert, which is listed on its own);
2. its ``event`` is on the allowlist in :mod:`snowlight.weather.hazards`;
3. it names at least one UGC in the contiguous states or DC;
4. it has not ended by the time the feed was generated;
5. its area can be resolved: its own polygon when it has one (a storm-based
   warning), otherwise the NWS public forecast zones and counties it lists,
   looked up in the boundary release in effect today. Zones outside the
   contiguous states and zone types without a published boundary file (fire
   weather zones) are left out and recorded; an alert with nothing left is
   dropped.

Times: an alert applies from ``onset`` (when the hazard begins) or, when the
NWS gives none, from ``effective``; it applies until ``ends``, or, when the NWS
gives none, the end time in its VTEC string; with neither, it is "until further
notice" and has no end. ``expires`` is when the message expires, not when the
hazard ends, and is not used.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

import shapely

from snowlight.sources.nws.alerts import ActiveFeed, NwsAlert
from snowlight.sources.nws.boundaries import BoundarySet
from snowlight.sources.nws.shapefile import Polygonal, polygonal
from snowlight.weather.hazards import CONUS_STATES, AlertType, alert_type_for_event
from snowlight.weather.index import AlertArea, AlertInfo

ZONE_KINDS = frozenset({"forecast", "public"})
_ENDING_ACTIONS = frozenset({"CAN", "UPG"})
COUNTY_KINDS = frozenset({"county"})


@dataclass(frozen=True, slots=True)
class LiveAlert:
    """An allowlisted alert and where it applies."""

    alert: NwsAlert
    kind: AlertType
    start: datetime
    end: datetime | None
    footprint: Polygonal
    areas: tuple[AlertArea, ...]
    basis: str
    zones: tuple[str, ...]
    unresolved: tuple[str, ...]

    @property
    def info(self) -> AlertInfo:
        """The alert's description as the weather check reports it."""
        return self.areas[0].alert


@dataclass(frozen=True, slots=True)
class Dropped:
    """An alert that was left out, and why."""

    id: str
    event: str
    reason: str


@dataclass(frozen=True, slots=True)
class Selection:
    """The outcome of :func:`select_alerts`."""

    kept: tuple[LiveAlert, ...]
    dropped: tuple[Dropped, ...]

    def reasons(self) -> dict[str, int]:
        """Count dropped alerts by reason."""
        return dict(sorted(Counter(item.reason for item in self.dropped).items()))


def alert_times(alert: NwsAlert) -> tuple[datetime | None, datetime | None]:
    """Return when an alert applies from and until (see the module docstring)."""
    start = alert.onset or alert.effective
    end = alert.ends
    if end is None:
        ends = {vtec.end for vtec in alert.vtec if vtec.end is not None}
        end = max(ends) if ends else None
    return start, end


def _states(alert: NwsAlert) -> set[str]:
    return {code[:2] for code in alert.ugc} | {zone.ugc[:2] for zone in alert.zones}


def _resolve(
    alert: NwsAlert,
    info: AlertInfo,
    span: tuple[datetime, datetime | None],
    zones: BoundarySet,
    counties: BoundarySet,
) -> tuple[list[AlertArea], list[Polygonal], list[str], list[str]]:
    start, end = span
    areas: list[AlertArea] = []
    pieces: list[Polygonal] = []
    resolved: list[str] = []
    unresolved: list[str] = [f"unparsed zone reference {url}" for url in alert.unparsed_zones]
    county_fips: set[str] = set()
    for ref in alert.zones:
        if ref.ugc[:2] not in CONUS_STATES:
            unresolved.append(f"{ref.kind} {ref.ugc}: outside the contiguous states")
            continue
        if ref.kind in ZONE_KINDS:
            geometry = zones.areas.get(ref.ugc)
            basis = "zone"
        elif ref.kind in COUNTY_KINDS:
            geometry = counties.areas.get(ref.ugc)
            basis = "county"
            fips = counties.county_fips.get(ref.ugc)
            if fips is not None:
                county_fips.add(fips)
        else:
            unresolved.append(f"{ref.kind} {ref.ugc}: no boundary file for this zone type")
            continue
        if geometry is None:
            unresolved.append(f"{ref.kind} {ref.ugc}: not in the boundary release in effect")
            continue
        resolved.append(f"{ref.kind} {ref.ugc}")
        if alert.geometry is None:
            pieces.append(geometry)
            areas.append(
                AlertArea(
                    alert=info,
                    start=start,
                    end=end,
                    geometry=geometry,
                    counties=frozenset({counties.county_fips[ref.ugc]})
                    if basis == "county"
                    else frozenset(),
                    basis="county" if basis == "county" else "zone",
                    precision="exact",
                    trace=f"{alert.id} {ref.kind} {ref.ugc}",
                )
            )
    if alert.geometry is not None:
        pieces = [alert.geometry]
        areas = [
            AlertArea(
                alert=info,
                start=start,
                end=end,
                geometry=alert.geometry,
                counties=frozenset(),
                basis="polygon",
                precision="exact",
                trace=f"{alert.id} polygon",
            )
        ]
        if county_fips:
            areas.append(
                AlertArea(
                    alert=info,
                    start=start,
                    end=end,
                    geometry=None,
                    counties=frozenset(county_fips),
                    basis="county",
                    precision="exact",
                    point_matching=False,
                    trace=f"{alert.id} counties",
                )
            )
    return areas, pieces, resolved, unresolved


def drop_reason(
    alert: NwsAlert,
    kind: AlertType | None,
    span: tuple[datetime | None, datetime | None],
    as_of: datetime | None,
) -> str | None:
    """Return why ``alert`` is left out before its area is resolved, or ``None`` to keep it."""
    start, end = span
    checks = (
        (alert.status != "Actual", f"status {alert.status}"),
        (alert.message_type not in {"Alert", "Update"}, f"message type {alert.message_type}"),
        (
            bool(alert.vtec) and all(vtec.action in _ENDING_ACTIONS for vtec in alert.vtec),
            "cancelled or upgraded (VTEC action)",
        ),
        (kind is None, "event not on the allowlist"),
        (not _states(alert) & CONUS_STATES, "outside the contiguous states"),
        (start is None, "no onset or effective time"),
        (
            end is not None and as_of is not None and end <= as_of,
            "ended before the feed was generated",
        ),
        (end is not None and start is not None and end <= start, "ends before it begins"),
    )
    return next((reason for failed, reason in checks if failed), None)


def select_alerts(feed: ActiveFeed, zones: BoundarySet, counties: BoundarySet) -> Selection:
    """Keep the allowlisted, in-scope, resolvable alerts of ``feed``."""
    kept: list[LiveAlert] = []
    dropped: list[Dropped] = []
    for alert in feed.alerts:
        kind = alert_type_for_event(alert.event)
        start, end = alert_times(alert)
        reason = drop_reason(alert, kind, (start, end), feed.updated)
        if reason is not None:
            dropped.append(Dropped(alert.id, alert.event, reason))
            continue
        if kind is None or start is None:  # pragma: no cover - drop_reason rules these out
            continue
        info = AlertInfo(
            key=alert.id,
            event=kind.event,
            hazard=kind.hazard,
            level=kind.level,
            severity=alert.severity,
        )
        areas, pieces, resolved, unresolved = _resolve(alert, info, (start, end), zones, counties)
        footprint = polygonal(shapely.union_all(pieces)) if pieces else None
        if not areas or footprint is None:
            dropped.append(Dropped(alert.id, alert.event, "no resolvable area"))
            continue
        kept.append(
            LiveAlert(
                alert=alert,
                kind=kind,
                start=start,
                end=end,
                footprint=footprint,
                areas=tuple(areas),
                basis="polygon" if alert.geometry is not None else "zones",
                zones=tuple(resolved),
                unresolved=tuple(unresolved),
            )
        )
    return Selection(tuple(kept), tuple(dropped))
