"""The schools' heights for the serving pass: the pinned elevation table, checked.

The pass reads the table ``config/elevation.yaml`` pins (built in Actions and kept in the data
mirror's release, :mod:`snowlight.elevation`), from its download cache when the cached bytes
have the pinned SHA-256, else from the pin's URL, and uses it only when its bytes have that
digest and its counts are the pin's. It never reads the terrain tiles.

A school's height is known only when the table has a row for its NCES id at its very point
in the deployed directory (:func:`snowlight.elevation.table.heights_for`). With no table
pinned or none readable, no height is known: every alert then reaches its whole zones, as
before alerts' heights were read, and the pass says so.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import numpy.typing as npt

from snowlight.directory.points import Points
from snowlight.elevation.pins import ElevationPins, TablePin
from snowlight.elevation.table import Table, TableError, heights_for
from snowlight.predict.alerts_live import LiveEvent, UgcIndex
from snowlight.predict.serve import reached_by

type Get = Callable[[str], bytes]
"""Reads a URL's bytes (raises ``OSError`` when it cannot)."""


@dataclass(frozen=True, slots=True)
class Loaded:
    """The table the pass uses (``None``: none), and why there is none."""

    table: Table | None
    problem: str | None = None
    retry: bool = False
    """The table is pinned but did not read (a download or its bytes failed): reading it
    again later may give it (:class:`PinnedTable`)."""


def _checked(data: bytes, pin: TablePin) -> Table:
    if hashlib.sha256(data).hexdigest() != pin.sha256:
        raise TableError("its bytes are not the pinned table's (SHA-256)")
    table = Table.from_bytes(data)
    if len(table.rows) != pin.schools or table.unknown != pin.unknown:
        raise TableError("its counts are not the pinned table's")
    return table


def load_pinned(pins: ElevationPins, cache_dir: Path, get: Get) -> Loaded:
    """The pinned table, from the cache or its URL (see the module docstring); never raises."""
    pin = pins.table
    if pin is None:
        return Loaded(None, "no elevation table is pinned")
    cached = cache_dir / pin.url.rsplit("/", 1)[-1]
    if cached.is_file():
        try:
            return Loaded(_checked(cached.read_bytes(), pin))
        except (OSError, TableError):
            pass
    try:
        data = get(pin.url)
        table = _checked(data, pin)
    except (OSError, TableError) as error:
        return Loaded(None, f"the pinned elevation table cannot be read ({error})", retry=True)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        part = cached.with_suffix(".part")
        part.write_bytes(data)
        part.replace(cached)
    except OSError:
        pass
    return Loaded(table)


@dataclass(slots=True)
class PinnedTable:
    """The pinned table for a pass loop that runs for hours: read when first asked, and read
    again after a failed read once ``retry`` has passed (a transient release error then costs
    one stretch of passes, not the whole run). A table that read, or a pin with no table, is
    kept."""

    read: Callable[[], Loaded]
    retry: timedelta
    clock: Callable[[], datetime]
    _loaded: Loaded | None = None
    _at: datetime | None = None

    def current(self) -> Loaded:
        """The table as last read, read again when due."""
        now = self.clock()
        loaded = self._loaded
        if loaded is None or self._at is None or (loaded.retry and now - self._at >= self.retry):
            loaded = self.read()
            self._loaded = loaded
            self._at = now
        return loaded


def school_heights(
    loaded: Loaded, school_ids: Sequence[str] | None, points: Points
) -> npt.NDArray[np.float64] | None:
    """Feet per school position of a directory (NaN where not known), or ``None`` with no
    table."""
    if loaded.table is None:
        return None
    return heights_for(loaded.table, school_ids, points)


@dataclass(frozen=True, slots=True)
class HeightsSaid:
    """What the pass says of the alerts that name heights."""

    alerts: int
    """Events (distinct VTEC keys) that name heights."""
    left_out: int
    """Schools of their zones that lie outside every band named (not reached)."""
    unknown: int
    """Schools of their zones with no known height (counted as reached)."""

    def line(self) -> str | None:
        """The pass's log line, or ``None`` when no alert names heights."""
        if not self.alerts:
            return None
        return (
            f"predict: {self.alerts} alerts name heights; {self.left_out:,} schools of their "
            f"zones lie outside them, {self.unknown:,} with no known height counted as reached"
        )


def heights_said(
    events: Sequence[LiveEvent],
    ugcs: UgcIndex,
    heights: npt.NDArray[np.float64] | None,
    margin: float,
) -> HeightsSaid:
    """Count, over the distinct schools of the zones of the events that name heights, those
    no such event reaches (outside every band) and those with no known height."""
    keys: set[str] = set()
    zones: set[int] = set()
    kept: set[int] = set()
    for event in events:
        if event.elevation is None:
            continue
        keys.add(event.key)
        zones.update(ugcs.reached(event.ugcs).tolist())
        kept.update(reached_by(event, ugcs, heights, margin)[0].tolist())
    if heights is None:
        unknown = len(zones)
    else:
        unknown = sum(1 for school in zones if np.isnan(heights[school]))
    return HeightsSaid(len(keys), len(zones - kept), unknown)
