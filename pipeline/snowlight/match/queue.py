"""The unmatched queue: listings the matcher did not accept, with their best candidates.

:func:`update_queue` folds one run's results into the queue file. Each listing
that was not accepted gets an entry keyed by its market and
:func:`~snowlight.match.aliases.alias_key` text, carrying the reason, the
confidence and the top candidates, so a person can check it and pin it in
``config/aliases.yaml``. An entry already in the queue keeps its ``first_seen``
and counts how often it came back; an entry whose listing was accepted in this
run (by an alias or by name) leaves the queue.

The queue is an internal file for the pipeline's maintainers. It is never
published with the site.
"""

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from snowlight.match.aliases import alias_key
from snowlight.match.matcher import Candidate, MatchResult
from snowlight.output import write_json


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QueuedCandidate(_Strict):
    """One candidate for an unmatched listing."""

    id: str
    name: str
    kind: Literal["district", "school"]
    district_id: str | None
    state: str
    county_fips: str | None
    city: str | None
    score: float = Field(ge=0.0, le=1.0)
    distance_km: float | None = Field(default=None, ge=0.0)

    @classmethod
    def of(cls, candidate: Candidate) -> "QueuedCandidate":
        """Describe a matcher :class:`~snowlight.match.matcher.Candidate`."""
        record = candidate.record
        distance = candidate.distance_km
        return cls(
            id=record.id,
            name=record.name,
            kind=record.kind,
            district_id=record.district_id,
            state=record.state,
            county_fips=record.county_fips,
            city=record.city,
            score=candidate.score,
            distance_km=None if distance is None else round(distance, 1),
        )


class QueueEntry(_Strict):
    """A listing waiting for a person to place it."""

    market: str | None
    listing: str
    states: tuple[str, ...]
    counties: tuple[str, ...] | None
    level: Literal["district", "school", "unknown"]
    reason: str
    detail: str
    confidence: float = Field(ge=0.0, le=1.0)
    candidates: tuple[QueuedCandidate, ...]
    first_seen: AwareDatetime
    last_seen: AwareDatetime
    times_seen: int = Field(ge=1)
    category: str | None = None
    """The section the list filed the listing under (``"Schools"``, ``"Churches"``)."""

    @property
    def key(self) -> tuple[str, str]:
        """The queue key: market (empty when none) and the listing's alias key."""
        return (self.market or "", alias_key(self.listing))


class UnmatchedQueue(_Strict):
    """The queue file."""

    schema_version: Literal[1] = 1
    updated_at: AwareDatetime
    entries: tuple[QueueEntry, ...]


def _key(result: MatchResult) -> tuple[str, str]:
    return (result.market or "", alias_key(result.listing))


def _entry(result: MatchResult, now: datetime, previous: QueueEntry | None) -> QueueEntry:
    ranked = [c for c in (result.best, *result.runners_up) if c is not None]
    return QueueEntry(
        market=result.market,
        listing=result.listing,
        states=result.states,
        counties=result.counties,
        level=result.level.value,
        reason=result.reason.value,
        detail=result.detail,
        confidence=result.confidence,
        candidates=tuple(QueuedCandidate.of(c) for c in ranked),
        first_seen=previous.first_seen if previous is not None else now,
        last_seen=now,
        times_seen=previous.times_seen + 1 if previous is not None else 1,
        category=result.category,
    )


def read_queue(path: Path) -> UnmatchedQueue | None:
    """Read the queue at ``path``, or ``None`` when there is no file yet."""
    if not path.exists():
        return None
    return UnmatchedQueue.model_validate(json.loads(path.read_text(encoding="utf-8")))


def update_queue(path: Path, results: Iterable[MatchResult], *, now: datetime) -> UnmatchedQueue:
    """Fold one run's results into the queue at ``path`` and write it.

    Results that were not accepted are added or refreshed; results that were
    accepted remove their listing from the queue. Entries this run did not see
    stay as they were. Entries are sorted by market and listing, and the file is
    written atomically with sorted keys, so the same queue is always the same
    bytes.

    Raises:
        ValueError: if ``now`` has no time zone.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    existing = read_queue(path)
    entries = {entry.key: entry for entry in existing.entries} if existing else {}
    for result in results:
        key = _key(result)
        if result.accepted:
            entries.pop(key, None)
        else:
            entries[key] = _entry(result, now, entries.get(key))
    queue = UnmatchedQueue(
        updated_at=now,
        entries=tuple(entries[key] for key in sorted(entries)),
    )
    write_json(path, queue.model_dump(mode="json"))
    return queue
