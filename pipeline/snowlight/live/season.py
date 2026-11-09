"""The season counts (``live/season.json``): each school's closed, delayed, remote and
early-dismissal days this school year, counted from the final day timelines.

Owner decision (2026-11-09): exact, never inflated, and honest about when counting began.

**What counts** (:func:`final_statuses`): only a day timeline marked ``final`` (the day is
over everywhere; a day in progress never counts). Each school on it counts once, under the
status its run of changes ends on: what the map showed at the end of the day, after any
correction. A run that ends dark (the status was taken back, corrected away or retracted)
counts nowhere, and a status changed during the day counts only as the one it ended as. The
admin's manual statuses are in the timelines like any other and count the same. A status
the emergency hold darkened is no part of a timeline (:func:`~snowlight.live.history.timeline`),
so it never counts.

**The school year** runs July 1 to June 30 (:func:`school_year`). The file counts the days
from ``since`` through ``through``: ``through`` is the last day over everywhere when it is
built (:func:`last_final_day`), ``since`` the school year's first day, or the later day
counting began.

**Directory editions.** A timeline's school indexes point into the edition it was built from
(its stamp and ``content_sha256``). Each day is turned into NCES ids with that edition's
own ids (:func:`final_statuses`), and the counts are placed into the current edition by NCES
id: never by position across editions. A timeline whose edition's ids are not known is left
out whole, and counting begins after it (:func:`build_season`); a school the current edition
does not hold is left out, never guessed.

**The ledger** (``season.json`` in the reader's private state, :class:`SeasonLedger`) keeps
each counted day's final statuses by NCES id, written by the publisher after an upload that
published the day's final timeline (:meth:`~snowlight.live.publish.LivePublisher.publish`),
so a day whose change log has left the state, or that was built from another edition, still
counts, mapped by id. ``since`` is set when the ledger is first written: the oldest final day
it was filled with then (the change log's, up to the 30 days a pass rebuilds), or, with none,
the first day not yet over. A ledger that does not read starts again, with a later
``since``. Rebuilding from the same days gives the same bytes (sorted everywhere, no clock).
NCES ids, days and status codes only.
"""

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final

from snowlight.live.history import content_of
from snowlight.live.resolve import LiveDirectory
from snowlight.output import JSONValue, dumps_json, write_bytes_atomic
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import (
    SEASON_STATUSES,
    DayTimeline,
    SeasonFile,
    SeasonRow,
    local_days,
)
from snowlight.schemas.scalars import school_year_bounds
from snowlight.schemas.vocab import Status

LOG: Final = logging.getLogger(__name__)
SEASON: Final = "live/season.json"
"""Where the file is published, under the mode's prefix (beside ``live/closings.json``)."""
LEDGER: Final = "season.json"
"""The ledger's name in the private state folder."""
_JULY: Final = 7

type DayStatuses = Mapping[str, Status]
"""One day's final statuses, by NCES id."""


def school_year(day: date) -> str:
    """The school year ``day`` belongs to, July 1 to June 30: ``"2026-2027"``."""
    start = day.year if day.month >= _JULY else day.year - 1
    return f"{start}-{start + 1}"


def last_final_day(generated_at: datetime) -> date:
    """The last day over everywhere at ``generated_at`` (the newest a final timeline can be)."""
    return local_days(generated_at)[0] - timedelta(days=1)


def final_statuses(made: DayTimeline, ids: Mapping[int, str]) -> dict[str, Status]:
    """Each school's final status on ``made``'s day, by NCES id: the status its run ends on,
    for each run that does not end dark. ``ids`` gives the NCES id of each index of the
    edition ``made`` was built from; a school it does not name is left out.

    Raises:
        ValueError: ``made`` is not final (its day is still in progress).
    """
    if not made.final:
        raise ValueError(f"{made.day}: a day in progress is never counted")
    found: dict[str, Status] = {}
    end = 0
    for school, count in zip(made.schools(), made.counts, strict=True):
        end += count
        last = made.statuses[end - 1]
        nces_id = ids.get(school)
        if last is not None and nces_id is not None:
            found[nces_id] = last
    return found


def tally(days: Mapping[date, DayStatuses], *, since: date, through: date) -> dict[str, list[int]]:
    """Each school's days of each status (:data:`~snowlight.schemas.live.SEASON_STATUSES`
    order) over the days from ``since`` through ``through``, by NCES id."""
    counts: dict[str, list[int]] = {}
    for day in sorted(days):
        if not since <= day <= through:
            continue
        for nces_id, status in days[day].items():
            counts.setdefault(nces_id, [0, 0, 0, 0])[SEASON_STATUSES.index(status)] += 1
    return counts


def season_file(
    days: Mapping[date, DayStatuses],
    *,
    since: date,
    through: date,
    directory: LiveDirectory,
    stamp: DirectoryStamp,
) -> SeasonFile | None:
    """The season file of ``through``'s school year: the days from ``since`` (or the year's
    first day, when that is later) through ``through``, placed into ``directory`` (the
    edition ``stamp`` names) by NCES id. ``None`` while counting has not begun by
    ``through``."""
    season = school_year(through)
    first, _ = school_year_bounds(season)
    since = max(since, first)
    if since > through:
        return None
    rows: dict[int, SeasonRow] = {}
    for nces_id, (closed, delayed, remote, early) in tally(
        days, since=since, through=through
    ).items():
        school = directory.schools.get(nces_id)
        if school is not None:
            rows[school.index] = (closed, delayed, remote, early)
    return SeasonFile.encode(
        rows,
        season=season,
        since=since,
        through=through,
        directory=stamp,
        content_sha256=content_of(directory),
    )


def build_season(
    archives: Iterable[DayTimeline],
    *,
    ids_of: Callable[[DayTimeline], Mapping[int, str] | None],
    through: date,
    directory: LiveDirectory,
    stamp: DirectoryStamp,
) -> SeasonFile | None:
    """The season file from the day timelines themselves, the one rule the ledger keeps.

    Only the final timelines of ``through``'s school year up to ``through`` count.
    ``ids_of(made)`` gives the NCES ids of the edition ``made`` was built from, or ``None``
    when they are not known: that day is left out whole, and counting begins the day after
    it. Counting begins with the first timeline counted otherwise. ``None`` when no
    timeline is counted.

    Raises:
        ValueError: two timelines for one day.
    """
    first, _ = school_year_bounds(school_year(through))
    seen: set[date] = set()
    days: dict[date, DayStatuses] = {}
    unknown: date | None = None
    for made in archives:
        if made.day in seen:
            raise ValueError(f"{made.day}: two timelines for one day")
        seen.add(made.day)
        if not made.final or not first <= made.day <= through:
            continue
        ids = ids_of(made)
        if ids is None:
            unknown = made.day if unknown is None else max(unknown, made.day)
            continue
        days[made.day] = final_statuses(made, ids)
    counted = [day for day in days if unknown is None or day > unknown]
    if not counted:
        return None
    since = min(counted) if unknown is None else unknown + timedelta(days=1)
    return season_file(days, since=since, through=through, directory=directory, stamp=stamp)


def edition_ids(directory: LiveDirectory) -> dict[int, str]:
    """The NCES id of each index of ``directory``."""
    return {school.index: nces_id for nces_id, school in directory.schools.items()}


def _by_status(statuses: DayStatuses) -> dict[str, JSONValue]:
    """One day of the ledger: the NCES ids of each status, sorted, by status code."""
    found: dict[str, JSONValue] = {}
    for status in SEASON_STATUSES:
        ids: list[JSONValue] = [
            nces_id for nces_id in sorted(statuses) if statuses[nces_id] == status
        ]
        found[str(int(status))] = ids
    return found


@dataclass(frozen=True, slots=True)
class SeasonLedger:
    """The ledger of counted days (see the module): each day's final statuses by NCES id."""

    since: date | None = None
    """The first day counted, set when the ledger is first written; ``None`` before."""
    days: Mapping[date, DayStatuses] = field(default_factory=dict)

    def with_days(self, found: Mapping[date, DayStatuses], *, through: date) -> "SeasonLedger":
        """The ledger with each of ``found`` (the days whose final timelines a publish
        carries) put in, replacing what it held for them; only ``through``'s school year
        is kept. A first ledger counts from the oldest of ``found``, or with none from the
        day after ``through``."""
        since = self.since
        if since is None:
            since = min(found, default=through + timedelta(days=1))
        first, last = school_year_bounds(school_year(through))
        days = {**self.days, **found}
        return SeasonLedger(
            since=since,
            days={day: days[day] for day in sorted(days) if first <= day <= last},
        )

    def season(
        self, *, through: date, directory: LiveDirectory, stamp: DirectoryStamp
    ) -> SeasonFile | None:
        """The season file this ledger holds through ``through`` (:func:`season_file`)."""
        if self.since is None:
            return None
        return season_file(
            self.days, since=self.since, through=through, directory=directory, stamp=stamp
        )

    def to_json_bytes(self) -> bytes:
        return dumps_json(
            {
                "schema_version": 1,
                "since": None if self.since is None else self.since.isoformat(),
                "days": {
                    day.isoformat(): _by_status(statuses)
                    for day, statuses in sorted(self.days.items())
                },
            }
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "SeasonLedger":
        """Raises ``ValueError`` (or ``KeyError``/``TypeError``) on another shape."""
        value = json.loads(data)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("not a season ledger")
        since = value["since"]
        days: dict[date, dict[str, Status]] = {}
        for day, by_status in value["days"].items():
            statuses: dict[str, Status] = {}
            for code, ids in by_status.items():
                status = Status(int(code))
                for nces_id in ids:
                    if not isinstance(nces_id, str) or nces_id in statuses:
                        raise ValueError("a school counts once a day")
                    statuses[nces_id] = status
            days[date.fromisoformat(day)] = statuses
        return cls(since=None if since is None else date.fromisoformat(since), days=days)

    @classmethod
    def load(cls, path: Path) -> "SeasonLedger":
        """The ledger at ``path``; an empty one when there is none, or it does not read (a
        warning: counting begins again)."""
        if not path.is_file():
            return cls()
        try:
            return cls.from_bytes(path.read_bytes())
        except (KeyError, TypeError, ValueError):
            LOG.warning("%s does not read: season counting begins again", path.name)
            return cls()

    def save(self, path: Path) -> None:
        write_bytes_atomic(path, self.to_json_bytes())
