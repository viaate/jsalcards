"""The live path of the weather class: NWS active alerts as events, and where they reach.

Each actual alert or update with a P-VTEC code of
:data:`~snowlight.predict.situations.CLASS_BY_CODE` (and not only cancelled, upgraded or
expired) becomes one :class:`~snowlight.predict.situations.Event` per VTEC string:

* ``issued``: the alert's ``sent``;
* the span: ``[onset or effective, ends or the VTEC end)``, open-ended when the NWS
  gives neither (a tropical warning "until further notice").

An event reaches the schools of the UGC codes it lists (``geocode.UGC``): the public
forecast zone and the county each school lies in (:class:`UgcIndex`), as the history
path reaches the schools in the zone versions its rows were issued for. When the alert names
heights for where it applies ("above 8,000 feet", :mod:`snowlight.sources.nws.elevation`), the
event keeps them, and the pass counts only the schools of those zones within them
(:func:`snowlight.predict.serve.school_classes`). History has no such lines (the season CSVs
carry no text), so this too is a place the live path is stricter than the training snapshot.

The pass keeps every event it has seen in the last ``memory_hours`` (:class:`Memory`), so
an alert that ended at 2 AM still counts for the 6 AM pass, as it does at the training
snapshot. An event that left the feed before its stated end ends when it was last seen.
An event the NWS cancels or upgrades (a ``CAN`` or ``UPG`` product, for some or all of its
zones) is dropped from the memory for those zones at once: the why never names a warning
the weather service withdrew. (History counts the first product's window whatever came
after, so this is the one place the live path is stricter than the training snapshot.)

When the memory has a gap (a lost or stale state), the pass rebuilds it from the NWS alert
history (``api.weather.gov/alerts?start=...``): every product issued since, in order, as the
live feed would have shown them (:meth:`Memory.rebuild`).
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Final

import numpy as np
import numpy.typing as npt
import shapely

from snowlight.predict.situations import CLASS_BY_CODE, Event
from snowlight.sources.nws.alerts import ActiveFeed, NwsAlert
from snowlight.sources.nws.elevation import ElevationLimit

ENDING_ACTIONS: Final = frozenset({"CAN", "UPG", "EXP"})
WITHDRAWN_ACTIONS: Final = frozenset({"CAN", "UPG"})
"""Actions that take an event back for the zones they list (expiry is a natural end)."""


@dataclass(frozen=True, slots=True)
class LiveEvent:
    """One VTEC event of one alert, the UGC codes it lists, and its change key."""

    key: str
    """``OFFICE.PH.S.ETN``: the same event through every update."""
    ugcs: frozenset[str]
    event: Event
    action: str
    elevation: ElevationLimit | None = None
    """The heights the alert names for where it applies; ``None``: it names none (every
    school of its zones is reached)."""

    @property
    def change_key(self) -> str:
        """What a change compares: event, action, times, area and heights."""
        end = "" if self.event.end is None else self.event.end.isoformat()
        parts = [
            self.key,
            self.action,
            self.event.start.isoformat(),
            end,
            ",".join(sorted(self.ugcs)),
        ]
        if self.elevation is not None:
            parts.append(json.dumps(self.elevation.as_json()))
        return "|".join(parts)


def live_events(feed: ActiveFeed) -> list[LiveEvent]:
    """The class-making events of the feed (see the module docstring)."""
    found: list[LiveEvent] = []
    for alert in feed.alerts:
        found.extend(_events(alert))
    return found


def _events(alert: NwsAlert) -> list[LiveEvent]:
    if alert.status != "Actual" or alert.message_type not in {"Alert", "Update"}:
        return []
    start = alert.onset or alert.effective
    if start is None or not alert.ugc:
        return []
    found: list[LiveEvent] = []
    for vtec in alert.vtec:
        code = f"{vtec.phenomena}.{vtec.significance}"
        if code not in CLASS_BY_CODE or vtec.action in ENDING_ACTIONS:
            continue
        end = alert.ends or vtec.end
        key = f"{vtec.office}.{code}.{vtec.etn:04d}"
        found.append(
            LiveEvent(
                key=key,
                ugcs=frozenset(alert.ugc),
                event=Event(code=code, issued=alert.sent, start=start, end=end),
                action=vtec.action,
                elevation=alert.elevation,
            )
        )
    return found


def withdrawn(alerts: Iterable[NwsAlert]) -> list[tuple[str, frozenset[str]]]:
    """The (event key, zones) that ``CAN`` and ``UPG`` products take back."""
    found: list[tuple[str, frozenset[str]]] = []
    for alert in alerts:
        if alert.status != "Actual" or not alert.ugc:
            continue
        for vtec in alert.vtec:
            code = f"{vtec.phenomena}.{vtec.significance}"
            if code in CLASS_BY_CODE and vtec.action in WITHDRAWN_ACTIONS:
                found.append((f"{vtec.office}.{code}.{vtec.etn:04d}", frozenset(alert.ugc)))
    return found


def alerts_digest(events: Iterable[LiveEvent]) -> str:
    """A digest of the live events' change keys: it moves when an alert is issued, upgraded,
    extended or cancelled anywhere (the addendum's rerun trigger)."""
    keys = sorted({event.change_key for event in events})
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Remembered:
    """An event as last seen."""

    event: LiveEvent
    last_seen: datetime


@dataclass(slots=True)
class Memory:
    """The events seen in the last ``hours`` (the pass's private state)."""

    hours: int
    seen: dict[tuple[str, frozenset[str]], Remembered] = field(default_factory=dict)
    unread_heights: int = 0
    """Entries of the kept state whose heights did not read: each is kept as reaching its
    whole zones (as before heights were read), and the pass says how many."""

    def withdraw(self, taken: Iterable[tuple[str, frozenset[str]]]) -> None:
        """Drop the zones a cancel or upgrade took back from every remembered entry of its
        event (an entry left with no zone is dropped)."""
        for key, zones in taken:
            for entry in [item for item in self.seen if item[0] == key]:
                remembered = self.seen.pop(entry)
                left = entry[1] - zones
                if left:
                    event = replace(remembered.event, ugcs=left)
                    self.seen[(key, left)] = Remembered(event, remembered.last_seen)

    def rebuild(self, alerts: Sequence[NwsAlert], now: datetime) -> None:
        """Take in the alert history (every product issued since some moment), in the order it
        was issued: each event as its latest product gave it, less what was later cancelled or
        upgraded. An event already remembered keeps its own entry."""
        for alert in sorted(alerts, key=lambda item: item.sent):
            self.withdraw(withdrawn([alert]))
            for event in _events(alert):
                entry = (event.key, event.ugcs)
                kept = self.seen.get(entry)
                if kept is None or kept.event.event.issued <= event.event.issued:
                    self.seen[entry] = Remembered(event, now)

    def update(
        self,
        events: Sequence[LiveEvent],
        now: datetime,
        taken: Iterable[tuple[str, frozenset[str]]] = (),
    ) -> list[LiveEvent]:
        """Record ``events`` as seen at ``now`` (after dropping what ``taken`` withdrew) and
        return every event to count: those in the feed, and those remembered (ended when last
        seen, if before their stated end)."""
        self.withdraw(taken)
        current = {(event.key, event.ugcs): event for event in events}
        for key, event in current.items():
            self.seen[key] = Remembered(event, now)
        horizon = now - timedelta(hours=self.hours)
        self.seen = {key: item for key, item in self.seen.items() if item.last_seen >= horizon}
        found = list(current.values())
        for key, item in sorted(
            self.seen.items(), key=lambda pair: (pair[0][0], sorted(pair[0][1]))
        ):
            if key in current:
                continue
            kept = item.event.event
            end = item.last_seen if kept.end is None else min(kept.end, item.last_seen)
            found.append(replace(item.event, event=replace(kept, end=end)))
        return found

    def as_json(self) -> list[dict[str, object]]:
        """The memory, for the state store."""
        return [
            {
                "key": item.event.key,
                "ugcs": sorted(item.event.ugcs),
                "code": item.event.event.code,
                "issued": item.event.event.issued.isoformat(),
                "start": item.event.event.start.isoformat(),
                "end": None if item.event.event.end is None else item.event.event.end.isoformat(),
                "action": item.event.action,
                "last_seen": item.last_seen.isoformat(),
                **(
                    {}
                    if item.event.elevation is None
                    else {"elevation": item.event.elevation.as_json()}
                ),
            }
            for _key, item in sorted(
                self.seen.items(), key=lambda pair: (pair[0][0], sorted(pair[0][1]))
            )
        ]

    @classmethod
    def from_json(cls, hours: int, items: Iterable[Mapping[str, object]]) -> "Memory":
        """The memory the state store kept. An entry whose heights do not read is kept with
        none, so it reaches its whole zones (counted in :attr:`unread_heights`).

        Raises:
            ValueError: an entry's times are not ISO 8601.
        """
        memory = cls(hours)
        for item in items:
            end = item.get("end")
            try:
                elevation = ElevationLimit.from_json(item.get("elevation"))
            except ValueError:
                elevation = None
                memory.unread_heights += 1
            event = LiveEvent(
                key=str(item["key"]),
                ugcs=frozenset(str(ugc) for ugc in item["ugcs"]),  # type: ignore[attr-defined]
                event=Event(
                    code=str(item["code"]),
                    issued=datetime.fromisoformat(str(item["issued"])),
                    start=datetime.fromisoformat(str(item["start"])),
                    end=None if end is None else datetime.fromisoformat(str(end)),
                ),
                action=str(item["action"]),
                elevation=elevation,
            )
            memory.seen[(event.key, event.ugcs)] = Remembered(
                event, datetime.fromisoformat(str(item["last_seen"]))
            )
        return memory


@dataclass(frozen=True, slots=True)
class UgcIndex:
    """The schools each UGC code reaches: its public forecast zone and its county."""

    schools: Mapping[str, npt.NDArray[np.int64]]

    def reached(self, ugcs: Iterable[str]) -> npt.NDArray[np.int64]:
        """The schools of any of ``ugcs``, sorted and unique."""
        parts = [self.schools[ugc] for ugc in ugcs if ugc in self.schools]
        if not parts:
            return np.zeros(0, dtype=np.int64)
        return np.unique(np.concatenate(parts))

    @classmethod
    def build(
        cls,
        lon: npt.NDArray[np.float64],
        lat: npt.NDArray[np.float64],
        areas: Mapping[str, shapely.Geometry],
    ) -> "UgcIndex":
        """Place every school (by position) in the areas (UGC code to polygon) covering it."""
        codes = sorted(areas)
        tree = shapely.STRtree([areas[code] for code in codes])
        school, area = tree.query(shapely.points(lon, lat), predicate="intersects")
        found: dict[str, list[int]] = defaultdict(list)
        for s, a in zip(school.tolist(), area.tolist(), strict=True):
            found[codes[a]].append(s)
        return cls({code: np.array(sorted(items), dtype=np.int64) for code, items in found.items()})
