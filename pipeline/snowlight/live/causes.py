"""Why each live source's last read went as it did, kept per source and counted at the end of
each live-read run (predict-next LIVE-READS, LEAD-1).

The ledger keeps only ``sources.last_outcome`` (``blocked``, ``error``, ``deferred``, ...): a 401
and a 403 are both ``blocked``, a 429 is ``error`` or ``deferred``, a network timeout an
``error`` with no status, the pass deadline ``late``. The status lives only in the pass's
:class:`~snowlight.live.pool.SourceResult`. :func:`cause_of` reads it there (and in the read's
last health record) into one :class:`Cause`, which :func:`snowlight.live.reads.keep_pass` keeps
beside the outcome in ``cadence.json`` (:mod:`snowlight.live.cadence`).

:func:`causes_line` is ``live state export``'s ``read causes:`` line, beside the cold census:
per tier (``A``: a list with an archive audience, ``audiences.json.gz``; ``B``: a county-proven
list with none, ``read-sources.json.gz``; ``other``: every other source the state holds), the
count of lists by their last cause, those ``never read`` (no cause kept and no ledger row), and
those ``dark`` (no good read in :data:`DARK_DAYS` days: ``sources.last_good_at``). Counts only:
no source ids, no names. It reads read only and never raises, so the export it follows is never
changed by it.
"""

import json
import sqlite3
from collections import Counter
from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final

from snowlight.live.ledger import Outcome
from snowlight.live.pool import SourceResult
from snowlight.sources.stations.model import HealthStatus

DARK_DAYS: Final = 45
"""A list with no good read in this many days is dark (the call time term's required days)."""
HTTP_CLIENT: Final = 400
HTTP_SERVER: Final = 500
HTTP_LAST: Final = 600


class Cause(StrEnum):
    """Why a source's read went as it did (codes only)."""

    OK = "ok"
    EMPTY = "empty"
    STALE = "stale"
    REFUSED_401 = "refused_401"
    REFUSED_403 = "refused_403"
    REFUSED_429 = "refused_429"
    HTTP_4XX = "http_4xx"
    HTTP_5XX = "http_5xx"
    NO_ANSWER = "no_answer"
    TIMEOUT = "timeout"
    """The pass's deadline (``late``)."""
    DEFERRED = "deferred"
    PARTIAL = "partial"
    ERROR = "error"


ORDER: Final = tuple(Cause)
_REFUSED: Final = {401: Cause.REFUSED_401, 403: Cause.REFUSED_403, 429: Cause.REFUSED_429}


_BY_OUTCOME: Final = {
    Outcome.OK: Cause.OK,
    Outcome.NOT_MODIFIED: Cause.OK,
    Outcome.EMPTY: Cause.EMPTY,
    Outcome.LATE: Cause.TIMEOUT,
    Outcome.PARTIAL: Cause.PARTIAL,
}


def cause_of(item: SourceResult) -> Cause:
    """One pass's read of a source as its :class:`Cause`: from the outcome, the HTTP status
    (the pool's, else the read's last health record's) and that record's status."""
    health = [entry for entry in item.result.health if entry.source_id == item.source_id]
    last = health[-1] if health else None
    status = item.http_status
    if status is None and last is not None:
        status = last.http_status
    direct = _BY_OUTCOME.get(item.outcome)
    if direct is not None:
        return direct
    if status is not None and status in _REFUSED:
        return _REFUSED[status]
    if item.outcome is Outcome.BLOCKED:
        return Cause.REFUSED_403
    if item.outcome is Outcome.DEFERRED:
        return Cause.DEFERRED
    return _failed(last.status if last is not None else None, status)


def _failed(health: HealthStatus | None, status: int | None) -> Cause:
    """A failed read's cause: judged stale on a good answer, an HTTP status, or none."""
    if health is HealthStatus.STALE:
        return Cause.STALE
    if status is None:
        return Cause.NO_ANSWER
    if HTTP_CLIENT <= status < HTTP_SERVER:
        return Cause.HTTP_4XX
    if HTTP_SERVER <= status < HTTP_LAST:
        return Cause.HTTP_5XX
    return Cause.ERROR


def kept_causes(state: Path) -> dict[str, str]:
    """Each source's last cause in ``cadence.json`` (none for a source without one).

    Raises:
        OSError, ValueError: the file does not read.
    """
    path = state / "cadence.json"
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    sources = document.get("sources") if isinstance(document, dict) else None
    return {
        str(sid): str(value["cause"])
        for sid, value in (sources or {}).items()
        if isinstance(value, dict) and isinstance(value.get("cause"), str)
    }


def last_good(state: Path) -> dict[str, datetime | None]:
    """Each ledger source's last good read (``None``: never), read only.

    Raises:
        sqlite3.Error: the ledger does not read.
    """
    path = state / "ledger.sqlite"
    if not path.is_file():
        return {}
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {
            str(source): None if at is None else datetime.fromisoformat(str(at))
            for source, at in db.execute("SELECT source_id, last_good_at FROM sources")
        }
    finally:
        db.close()


def tiers_of(
    audiences: Collection[str], counties: Mapping[str, Collection[str]]
) -> dict[str, frozenset[str]]:
    """``A``: the lists with an archive audience; ``B``: the county-proven lists without one."""
    tier_a = frozenset(audiences)
    proven = {source for sources in counties.values() for source in sources}
    return {"A": tier_a, "B": frozenset(proven - tier_a)}


def tally(
    tiers: Mapping[str, Collection[str]],
    causes: Mapping[str, str],
    good: Mapping[str, datetime | None],
    now: datetime,
) -> dict[str, Counter[str]]:
    """Per tier (and ``other``), the lists by cause, ``never read`` and ``dark``."""
    known = set().union(*tiers.values()) if tiers else set()
    other = (set(causes) | set(good)) - known
    found: dict[str, Counter[str]] = {}
    for name, sources in [*tiers.items(), ("other", other)]:
        counts: Counter[str] = Counter()
        for source in sources:
            if source in causes:
                counts[causes[source]] += 1
            elif source not in good:
                counts["never read"] += 1
            at = good.get(source)
            if at is None or now - at > timedelta(days=DARK_DAYS):
                counts["dark"] += 1
        counts["lists"] = len(sources)
        found[name] = counts
    return found


def _part(name: str, counts: Counter[str]) -> str:
    known = [c.value for c in ORDER]
    order = known + sorted(set(counts) - {*known, "lists", "never read", "dark"})
    body = [f"{key} {counts[key]}" for key in order if counts[key]]
    body += [f"never read {counts['never read']}", f"dark {counts['dark']}"]
    return f"{name} {counts['lists']} lists: " + ", ".join(body)


def causes_line(state: Path, now: datetime, *, read_sources: Path, audiences: Path) -> str:
    """``read causes:`` (see the module): counts only. It never raises."""
    try:
        from snowlight.predict.live_read import (  # noqa: PLC0415 - the coverage files' readers
            load_audiences,
            load_read_sources,
        )

        tiers = tiers_of(load_audiences(audiences), load_read_sources(read_sources).counties)
        found = tally(tiers, kept_causes(state), last_good(state), now)
    except Exception as error:  # a counts line never changes the export
        return f"read causes: unreadable ({type(error).__name__})"
    return "read causes: " + "; ".join(_part(name, counts) for name, counts in found.items())


__all__ = ["Cause", "cause_of", "causes_line", "kept_causes", "tally", "tiers_of"]
