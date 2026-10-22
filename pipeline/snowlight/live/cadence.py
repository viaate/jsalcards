"""When each live source is read (spec 7.3; owner decision Q3, 2026-10-13).

* **Windows.** 18:00-23:00 and 04:00-09:00 in the station's local zone: the zone most of
  its counties are in (:func:`station_zones`; on a tie every tied zone, so the earliest
  window open in any of them counts). Real zone rules are used, so the windows follow
  daylight saving time (it ends Sun 2026-11-01).
* **Alerts.** An active, allowlisted NWS alert touching any of the station's counties
  (:func:`alert_counties`, from the alert's SAME county codes). The feed is read every
  5 minutes through the same pacer (:class:`AlertWatch`); when it fails, the last good
  set is kept for up to 2 hours, then windows alone decide.
* **Cadence.** Every 5 minutes in a window or an alert; otherwise
  ``max(30 minutes, the registry's poll_minutes)``.
* **Failures.** A source the pass did not get to read (``late``) is due at the next pass.
  One whose server answered badly (``error``: a 429 or 5xx without ``Retry-After``, a
  failed connection, or a list judged stale on a good answer; ``partial``) keeps its
  cadence: the next pass in a window or an alert, else its calm interval, so a throttled
  host is never read more often than the owner's cadence allows. A ``deferred`` source
  is due once its ``Retry-After`` has passed, a ``blocked`` one (403) after 24 hours.
* **Grid.** Passes start on a 5-minute grid; a source is due when its cadence's number of
  grid slots lies between the slot of the pass that last read it and this pass's slot,
  and at least its cadence less a minute's grace has passed (grid jitter only). So a
  5-minute source is read at every pass of a window, while a second run inside the same
  slot (``live once``) or an off-grid start a minute or two later reads nothing again.

:class:`Cadence` keeps each source's last pass, outcome and earliest next read in
``cadence.json`` in the private state (ids, codes and times only).
"""

import json
import logging
from collections import Counter, deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

from snowlight.live.ledger import Outcome
from snowlight.output import write_bytes_atomic
from snowlight.sources.stations.registry import Station
from snowlight.weather.hazards import alert_type_for_event

LOG: Final = logging.getLogger(__name__)

WINDOWS: Final = ((time(18), time(23)), (time(4), time(9)))
"""The local reading windows, each from its start up to (not including) its end."""
BOOSTED: Final = timedelta(minutes=5)
CALM_FLOOR: Final = timedelta(minutes=30)
GRID: Final = timedelta(minutes=5)
GRACE: Final = timedelta(minutes=1)
ALERT_EVERY: Final = timedelta(minutes=5)
ALERT_KEEP: Final = timedelta(hours=2)
BLOCKED_FOR: Final = timedelta(hours=24)
DUE_WINDOW: Final = timedelta(minutes=15)
"""G12b counts the sources due in passes of the last 15 minutes."""
CADENCE_VERSION: Final = 1
_UNREAD: Final = frozenset({Outcome.LATE})
"""Outcomes of a pass that did not get to read the source: it is due at the next pass."""
_EPOCH: Final = datetime(2000, 1, 1, tzinfo=UTC)


def grid_slot(moment: datetime) -> int:
    """The number of the 5-minute grid slot ``moment`` falls in."""
    return (moment - _EPOCH) // GRID


def in_window(zone: str, now: datetime) -> bool:
    """Whether ``now`` is inside a reading window in ``zone``."""
    local = now.astimezone(ZoneInfo(zone)).time()
    return any(start <= local < end for start, end in WINDOWS)


def county_zones(schools: Iterable[tuple[str | None, str | None]]) -> dict[str, str]:
    """Each county's zone: the zone most of its schools are in (``(county_fips, zone)``
    pairs; ties go to the zone named first alphabetically)."""
    counts: dict[str, Counter[str]] = {}
    for fips, zone in schools:
        if fips and zone:
            counts.setdefault(fips, Counter())[zone] += 1
    return {
        fips: sorted(found.items(), key=lambda item: (-item[1], item[0]))[0][0]
        for fips, found in counts.items()
    }


def station_zones(station: Station, zones: Mapping[str, str]) -> tuple[str, ...]:
    """The zone most of the station's counties are in; every tied zone on a tie; none when
    no county's zone is known."""
    fips = station.counties.fips if station.counties is not None else ()
    found = Counter(zones[code] for code in fips if code in zones)
    if not found:
        return ()
    most = max(found.values())
    return tuple(sorted(zone for zone, count in found.items() if count == most))


def alert_counties(payload: bytes, now: datetime) -> frozenset[str]:
    """The county FIPS codes under an active alert in an NWS ``/alerts/active`` body: alerts
    that are actual, not cancelled, of an allowlisted type and not yet expired (or ended).

    Raises:
        ValueError: the body is not a GeoJSON collection of alerts.
    """
    document = json.loads(payload)
    if not isinstance(document, dict) or not isinstance(document.get("features"), list):
        raise ValueError("not an alerts collection")
    found: set[str] = set()
    for feature in document["features"]:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict):
            continue
        if props.get("status") != "Actual" or props.get("messageType") == "Cancel":
            continue
        if alert_type_for_event(str(props.get("event") or "")) is None:
            continue
        if any(_past(props.get(name), now) for name in ("expires", "ends")):
            continue
        geocode = props.get("geocode")
        same = geocode.get("SAME") if isinstance(geocode, dict) else None
        for code in same if isinstance(same, list) else ():
            text = str(code)
            if len(text) == 6 and text.isdigit():  # noqa: PLR2004 - 0SSCCC
                found.add(text[1:])
    return frozenset(found)


def _past(value: object, now: datetime) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return False
    return when.tzinfo is not None and when <= now


class AlertWatch:
    """The counties under an active alert, read at most every 5 minutes.

    ``read`` returns an ``/alerts/active`` body (through the pool's pacer). A read that
    fails keeps the last good set for up to :data:`ALERT_KEEP` after it was read; after
    that the set is empty (windows alone decide) until a read succeeds. When the feed asks
    for a ``Retry-After`` (a read that raised one, as the pool's deferral does), it is not
    read again until that wait ends.
    """

    def __init__(self, read: Callable[[], bytes]) -> None:
        self._read = read
        self._good: tuple[datetime, frozenset[str]] | None = None
        self._tried: datetime | None = None

    def counties(self, now: datetime) -> frozenset[str]:
        """The alerted counties at ``now`` (reading the feed when 5 minutes have passed)."""
        if self._tried is None or now - self._tried >= ALERT_EVERY:
            self._tried = now
            try:
                self._good = (now, alert_counties(self._read(), now))
            except Exception as error:
                LOG.warning("alerts feed: %s", type(error).__name__)
                wait = getattr(error, "retry_after", None)
                if isinstance(wait, int | float) and wait > 0:
                    # Tried again once ALERT_EVERY has passed from the end of the wait.
                    self._tried = now + timedelta(seconds=wait) - ALERT_EVERY
        if self._good is None or now - self._good[0] > ALERT_KEEP:
            return frozenset()
        return self._good[1]

    @property
    def last_good(self) -> datetime | None:
        """When the feed was last read whole."""
        return self._good[0] if self._good is not None else None


@dataclass(frozen=True, slots=True)
class SourceClock:
    """What the cadence keeps for one source (ids, codes and times only)."""

    last_pass: datetime
    """The start of the pass that last read (or tried) it."""
    outcome: Outcome
    not_before: datetime | None = None
    """Not due before this (deferred or blocked)."""


class Cadence:
    """Which sources are due each pass (see the module)."""

    def __init__(
        self,
        stations: Mapping[str, Station],
        zones: Mapping[str, str],
        poll_minutes: Callable[[Station], int],
        *,
        path: Path | None = None,
        alerts: AlertWatch | None = None,
    ) -> None:
        self.stations = stations
        self._county_zones = zones
        self._zones = {sid: station_zones(station, zones) for sid, station in stations.items()}
        self._poll_minutes = poll_minutes
        self.path = path
        self.alerts = alerts
        self.alerted: frozenset[str] = frozenset()
        """The counties under an alert at the last :meth:`due`."""
        self.clocks: dict[str, SourceClock] = self._load(path) if path is not None else {}
        self._picked: deque[tuple[datetime, frozenset[str]]] = deque()

    # What a station's cadence is -------------------------------------------------------

    def in_alert(self, station: Station) -> bool:
        """Whether an active alert touches one of the station's counties."""
        fips = station.counties.fips if station.counties is not None else ()
        return any(code in self.alerted for code in fips)

    def boosted(self, station: Station, now: datetime) -> bool:
        """Whether ``station`` is in a reading window or an alert at ``now``. A station
        whose zone is unknown counts as in a window (read often rather than late)."""
        zones = self._zones.get(station.id)
        if zones is None:
            zones = station_zones(station, self._county_zones)
        if not zones:
            return True
        return self.in_alert(station) or any(in_window(zone, now) for zone in zones)

    def interval(self, station: Station, now: datetime) -> timedelta:
        """How often ``station`` is read at ``now``."""
        if self.boosted(station, now):
            return BOOSTED
        return max(CALM_FLOOR, timedelta(minutes=self._poll_minutes(station)))

    # Each pass --------------------------------------------------------------------------

    def due(self, now: datetime, candidates: Iterable[str]) -> list[Station]:
        """The sources among ``candidates`` due at ``now`` (refreshing the alert set)."""
        if self.alerts is not None:
            self.alerted = self.alerts.counties(now)
        picked = []
        for source_id in sorted(set(candidates)):
            station = self.stations.get(source_id)
            if station is not None and self.is_due(station, now):
                picked.append(station)
        self._picked.append((now, frozenset(station.id for station in picked)))
        return picked

    def is_due(self, station: Station, now: datetime) -> bool:
        """Whether ``station`` is due at ``now`` (see the module)."""
        clock = self.clocks.get(station.id)
        if clock is None:
            return True
        if clock.not_before is not None and now < clock.not_before:
            return False
        if clock.outcome in _UNREAD or clock.not_before is not None:
            return True
        interval = self.interval(station, now)
        slots = grid_slot(now) - grid_slot(clock.last_pass)
        return slots >= interval // GRID and now >= clock.last_pass + interval - GRACE

    def record(
        self, started: datetime, results: Iterable[tuple[str, Outcome, float | None]]
    ) -> None:
        """Keep each source's ``(id, outcome, wait)`` from the pass started at ``started``;
        ``wait`` is, for a deferred source, the seconds from ``started`` until the end of the
        wait its server asked for (when it answered plus its ``Retry-After``)."""
        for source_id, outcome, wait in results:
            not_before = None
            if outcome is Outcome.BLOCKED:
                not_before = started + BLOCKED_FOR
            elif outcome is Outcome.DEFERRED:
                not_before = started + timedelta(seconds=wait or GRID.total_seconds())
            self.clocks[source_id] = SourceClock(started, outcome, not_before)

    def note(self, now: datetime, ids: Iterable[str]) -> None:
        """Count ``ids`` as due at ``now`` (a pass that read sources it was given)."""
        self._picked.append((now, frozenset(ids)))

    def recently_due(self, now: datetime) -> frozenset[str]:
        """The sources due in the passes of the last 15 minutes, and every source blocked
        now (G12b counts over them: a blocked source is not read healthy)."""
        while self._picked and now - self._picked[0][0] > DUE_WINDOW:
            self._picked.popleft()
        found: set[str] = set()
        for _, ids in self._picked:
            found |= ids
        found |= {
            sid
            for sid, clock in self.clocks.items()
            if clock.outcome is Outcome.BLOCKED
            and clock.not_before is not None
            and now < clock.not_before
            and sid in self.stations
        }
        return frozenset(found)

    # Keeping it --------------------------------------------------------------------------

    @staticmethod
    def _load(path: Path) -> dict[str, SourceClock]:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            LOG.warning("cadence state unreadable, starting empty: %s", type(error).__name__)
            return {}
        if not isinstance(document, dict) or document.get("version") != CADENCE_VERSION:
            return {}
        clocks: dict[str, SourceClock] = {}
        for sid, value in (document.get("sources") or {}).items():
            try:
                after = value.get("not_before")
                clocks[str(sid)] = SourceClock(
                    datetime.fromisoformat(value["last_pass"]),
                    Outcome(value["outcome"]),
                    datetime.fromisoformat(after) if after else None,
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
        return clocks

    def save(self) -> None:
        """Write the clocks to ``path`` (atomically)."""
        if self.path is None:
            return
        sources = {
            sid: {
                "last_pass": clock.last_pass.astimezone(UTC).isoformat(),
                "outcome": clock.outcome.value,
                "not_before": clock.not_before.astimezone(UTC).isoformat()
                if clock.not_before is not None
                else None,
            }
            for sid, clock in sorted(self.clocks.items())
        }
        text = json.dumps({"version": CADENCE_VERSION, "sources": sources}, sort_keys=True)
        write_bytes_atomic(self.path, (text + "\n").encode("utf-8"))
