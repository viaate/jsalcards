"""The live days' history: every change of what the map showed, and the day timelines built from it.

Owner decisions on replays (2026-10-14): replays come only from days the live
pipeline read, so every published change is kept, per school and local day, with
its time (:class:`ChangeLog`), and each day with statuses gets a public timeline
(:class:`~snowlight.schemas.live.DayTimeline`) a page can scrub through.

**The change log** is private (it names sources and row keys, never raw text). It is
one JSON Lines file per local day, ``changes/<day>.jsonl``, in the state store, each
rewritten whole and atomically on every commit (a process killed mid-write leaves the
old file or the new one; a line that does not read, from an older torn append, is
skipped and counted, never fatal). Each
successful publish compares what it shows with what the last one showed, school-day
by school-day (by NCES id, so a new directory edition changes nothing), and appends
one line per difference:

* ``lit``: a status shows where none did;
* ``changed``: another status, or the same one with another reason, shift or clock;
* ``dark``: the status is no longer shown (taken back, withheld, or a blank publish);
* ``expired``: the day is over for the school (its status left the file with its day).

A line holds the publish time (``at``: when the map changed), the status codes, the
row's first sighting (``hi``) and announcement, and where it came from (source id,
row key, edition): a day can be rebuilt at any minute. A ``dark`` line written because
``snowlight live blank`` held the map dark carries ``"by": "hold"``; a line rebuilt
from the public day file (a successor that lost its state) carries ``"by": "seed"``.

**A day timeline** lists, for each school that showed a status that day, each change
as the minute of the day in the school's own zone (negative before the day began),
the status (or ``null`` when it went dark) and its details. The day's ending
(``expired``) is not a change. A day in progress is published on every publish
with ``final`` false; once the day is over everywhere it is published one last
time with ``final`` true. It records the directory content its school indexes were
built from (:func:`content_of`), as the stamp alone cannot tell two contents built on
one day apart: a successor continues a day only from a file built from its own.

**The emergency stop is not history.** The operator holds the map dark because
something it showed was false, and which status was false is not recorded. So a
status the hold darkened is left out of the timeline from when it was lit: the
replay never shows it, and a status shown again after the release appears from
then on.
"""

import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

from snowlight.live.merge import day_start
from snowlight.live.resolve import LiveDirectory
from snowlight.output import JSONValue, dumps_json, write_bytes_atomic
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import (
    MAX_LEAD_MINUTES,
    Closing,
    DayEntry,
    DayIndex,
    DayTimeline,
    local_days,
)
from snowlight.schemas.scalars import MINUTES_PER_DAY
from snowlight.schemas.vocab import SHIFTED, Reason, Status

LOG: Final = logging.getLogger(__name__)
KEEP_DAYS: Final = 30
"""How many days of change log the state store keeps once a durable copy holds them."""
DURABLE: Final = "durable.json"
"""``changes/durable.json``: ``{"through": "YYYY-MM-DD"}``, written by the durable push
(spec 19) once the days up to then are kept elsewhere. Without it nothing is pruned."""
FOLD_DAYS: Final = 3
"""How many days before the newest logged day still matter for what the map shows."""
INDEX_DAYS: Final = 30
"""How many days the public day index lists."""
BY: Final = "by"
"""The change-line field naming what wrote a line that is not a publish's own."""
BY_HOLD: Final = "hold"
BY_SEED: Final = "seed"
_SUFFIX: Final = ".jsonl"


class Event(StrEnum):
    LIT = "lit"
    CHANGED = "changed"
    DARK = "dark"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class Shown:
    """What the map shows for one school on one day."""

    status: int
    reason: int | None
    shift: int | None
    clock: int | None

    @classmethod
    def of(cls, closing: Closing) -> "Shown":
        return cls(
            status=int(closing.status),
            reason=None if closing.reason is None else int(closing.reason),
            shift=closing.shift_minutes,
            clock=closing.clock_minute,
        )


@dataclass(frozen=True, slots=True)
class Change:
    """One line of the change log."""

    at: datetime
    day: date
    nces_id: str
    event: Event
    shown: Shown | None
    fields: Mapping[str, JSONValue]
    """Where it came from: school index, edition, source id, row key, ``hi``, announcement."""

    def to_json(self) -> dict[str, JSONValue]:
        shown = self.shown
        return {
            **self.fields,
            "at": self.at.astimezone(UTC).isoformat(),
            "day": self.day.isoformat(),
            "nces_id": self.nces_id,
            "event": self.event.value,
            "status": None if shown is None else shown.status,
            "reason": None if shown is None else shown.reason,
            "shift_minutes": None if shown is None else shown.shift,
            "clock_minute": None if shown is None else shown.clock,
        }

    @classmethod
    def from_json(cls, value: object) -> "Change":
        """Raises ``ValueError`` (or ``KeyError``/``TypeError``) on a line of another shape."""
        if not isinstance(value, dict):
            raise TypeError("a change is an object")
        status = value["status"]
        shown = (
            None
            if status is None
            else Shown(
                status=int(status),
                reason=_opt_int(value["reason"]),
                shift=_opt_int(value["shift_minutes"]),
                clock=_opt_int(value["clock_minute"]),
            )
        )
        known = {"at", "day", "nces_id", "event", "status", "reason", "shift_minutes"}
        known.add("clock_minute")
        return cls(
            at=datetime.fromisoformat(str(value["at"])),
            day=date.fromisoformat(str(value["day"])),
            nces_id=str(value["nces_id"]),
            event=Event(str(value["event"])),
            shown=shown,
            fields={key: item for key, item in value.items() if key not in known},
        )


def _opt_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("a code is a whole number")
    return value


type Key = tuple[str, date]
"""A school-day: NCES id and local day."""


class ChangeLog:
    """The private change log, one file per local day under ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.shown: dict[Key, Shown] = {}
        """What the last publish showed, folded from the log of the newest days (a status
        is only ever shown for a day that is today or tomorrow somewhere)."""
        self.last_at: datetime | None = None
        """The newest change's time, of those folded or committed."""
        days = self.days()
        for day in days:
            if day >= days[-1] - timedelta(days=FOLD_DAYS):
                for change in self.changes(day):
                    self._apply(change)

    def days(self) -> list[date]:
        """The days with a log, oldest first."""
        if not self.root.is_dir():
            return []
        found = []
        for path in self.root.glob(f"*{_SUFFIX}"):
            try:
                found.append(date.fromisoformat(path.stem))
            except ValueError:
                continue
        return sorted(found)

    def _path(self, day: date) -> Path:
        return self.root / f"{day.isoformat()}{_SUFFIX}"

    def changes(self, day: date) -> list[Change]:
        """A day's changes, in the order they were logged (a line that does not read is
        skipped and counted in the log: it can only be an older torn append)."""
        path = self._path(day)
        if not path.is_file():
            return []
        found: list[Change] = []
        skipped = 0
        for line in path.read_bytes().splitlines():
            if not line.strip():
                continue
            try:
                found.append(Change.from_json(json.loads(line)))
            except (KeyError, TypeError, ValueError):
                skipped += 1
        if skipped:
            LOG.warning("change log %s: %d lines do not read and are skipped", day, skipped)
        return found

    def _apply(self, change: Change) -> None:
        if self.last_at is None or change.at > self.last_at:
            self.last_at = change.at
        key = (change.nces_id, change.day)
        if change.shown is None:
            self.shown.pop(key, None)
        else:
            self.shown[key] = change.shown

    def diff(
        self,
        at: datetime,
        shown: Mapping[Key, tuple[Shown, Mapping[str, JSONValue]]],
        *,
        past: Callable[[str, date], bool],
    ) -> list[Change]:
        """The changes from what the log shows to ``shown`` (nothing is written).

        ``past(nces_id, day)`` says whether the day is over for the school at ``at``.
        """
        changes: list[Change] = []
        for key in sorted(shown):
            now, fields = shown[key]
            before = self.shown.get(key)
            if before != now:
                event = Event.LIT if before is None else Event.CHANGED
                changes.append(Change(at, key[1], key[0], event, now, fields))
        for key in sorted(set(self.shown) - set(shown)):
            event = Event.EXPIRED if past(*key) else Event.DARK
            changes.append(Change(at, key[1], key[0], event, None, {}))
        return changes

    def commit(self, changes: Iterable[Change]) -> None:
        """Add ``changes`` to their days' files (after the publish that shows them). Each
        file is rewritten whole and atomically; a torn last line is dropped."""
        by_day: dict[date, list[Change]] = {}
        for change in changes:
            by_day.setdefault(change.day, []).append(change)
        for day, found in sorted(by_day.items()):
            path = self._path(day)
            kept = path.read_bytes() if path.is_file() else b""
            if kept and not kept.endswith(b"\n"):
                kept = kept[: kept.rfind(b"\n") + 1]  # a torn append: its tail never read
            added = b"".join(dumps_json(change.to_json()) + b"\n" for change in found)
            write_bytes_atomic(path, kept + added)
            for change in found:
                self._apply(change)

    def durable_through(self) -> date | None:
        """The last day a durable copy holds (:data:`DURABLE`), or ``None``."""
        path = self.root / DURABLE
        try:
            return date.fromisoformat(str(json.loads(path.read_bytes())["through"]))
        except (OSError, KeyError, TypeError, ValueError):
            return None

    def prune(self, today: date, keep: int = KEEP_DAYS) -> list[date]:
        """Remove the files of days more than ``keep`` days before ``today`` that a durable
        copy already holds (:meth:`durable_through`); without one, nothing."""
        through = self.durable_through()
        if through is None:
            return []
        removed = [
            day for day in self.days() if day < today - timedelta(days=keep) and day <= through
        ]
        for day in removed:
            self._path(day).unlink()
        return removed


def _minute(at: datetime, day: date, zone: str) -> int:
    start = day_start(day, (zone,))
    minutes = int((at.astimezone(UTC) - start).total_seconds() // 60)
    return max(-MAX_LEAD_MINUTES, min(minutes, 2 * MINUTES_PER_DAY - 1))


_DIGEST: Final = re.compile(r"[0-9a-f]{64}")


def content_of(directory: LiveDirectory) -> str:
    """The content digest a day file records for ``directory``: its edition, which is the
    directory's ``content_sha256`` (an edition id that is not a digest is hashed)."""
    edition = directory.edition
    if _DIGEST.fullmatch(edition):
        return edition
    return hashlib.sha256(edition.encode()).hexdigest()


def timeline(  # noqa: PLR0913 - the day, its changes and the directory they index into
    day: date,
    changes: Sequence[Change],
    *,
    directory: LiveDirectory,
    stamp: DirectoryStamp,
    generated_at: datetime,
    final: bool,
) -> DayTimeline | None:
    """The day's public timeline, or ``None`` when no school showed a status that day.

    Schools are placed by NCES id in ``directory`` (the edition ``stamp`` names); a
    school no longer in it is left out.
    """
    runs: dict[int, list[tuple[int, Shown | None]]] = {}
    for change in sorted(changes, key=lambda found: found.at):
        if change.event is Event.EXPIRED or change.day != day:
            continue
        school = directory.schools.get(change.nces_id)
        if school is None or not school.zones:
            continue
        run = runs.setdefault(school.index, [])
        shown = change.shown
        if shown is None and change.fields.get(BY) == BY_HOLD:
            while run and run[-1][1] is not None:
                run.pop()  # the emergency stop: what it darkened is no part of the record
            continue
        if (not run and shown is None) or (run and run[-1][1] == shown):
            continue
        run.append((_minute(change.at, day, school.zones[0]), shown))
    if not any(runs.values()):
        return None
    schools = sorted(index for index, run in runs.items() if run)
    gaps = [
        school - previous - 1 for previous, school in zip([-1, *schools], schools, strict=False)
    ]
    flat = [entry for school in schools for entry in runs[school]]
    shifted = [shown for _, shown in flat if shown is not None and Status(shown.status) in SHIFTED]
    return DayTimeline.model_validate(
        {
            "schema_version": 1,
            "day": day,
            "generated_at": generated_at.astimezone(UTC).replace(microsecond=0),
            "directory": stamp,
            "content_sha256": content_of(directory),
            "final": final,
            "gaps": tuple(gaps),
            "counts": tuple(len(runs[school]) for school in schools),
            "minutes": tuple(minute for minute, _ in flat),
            "statuses": tuple(None if shown is None else Status(shown.status) for _, shown in flat),
            "reasons": tuple(
                None if shown is None or shown.reason is None else Reason(shown.reason)
                for _, shown in flat
            ),
            "shifts": tuple(shown.shift for shown in shifted),
            "clocks": tuple(shown.clock for shown in shifted),
        }
    )


def seed_changes(made: DayTimeline, directory: LiveDirectory) -> list[Change]:
    """The change lines a published day timeline holds, at the minutes it gives (for a
    successor that lost its change log: its next publish then continues the day rather than
    starting it again). A school not in ``directory`` is left out."""
    by_index = {school.index: (nces_id, school) for nces_id, school in directory.schools.items()}
    changes: list[Change] = []
    position = shifted = 0
    school = -1
    for gap, count in zip(made.gaps, made.counts, strict=True):
        school += gap + 1
        found = by_index.get(school)
        before: Shown | None = None
        for _ in range(count):
            minute, status = made.minutes[position], made.statuses[position]
            reason = made.reasons[position]
            position += 1
            shown = None
            if status is not None:
                shift = clock = None
                if status in SHIFTED:
                    shift, clock = made.shifts[shifted], made.clocks[shifted]
                    shifted += 1
                shown = Shown(int(status), None if reason is None else int(reason), shift, clock)
            if found is None or not found[1].zones:
                before = shown
                continue
            nces_id, record = found
            at = day_start(made.day, (record.zones[0],)) + timedelta(minutes=minute)
            event = Event.LIT if before is None else Event.CHANGED
            if shown is None:
                event = Event.DARK
            changes.append(Change(at, made.day, nces_id, event, shown, {BY: BY_SEED}))
            before = shown
    return changes


def day_index(entries: Mapping[date, tuple[int, bool]], generated_at: datetime) -> DayIndex:
    """The public index of the days with a timeline: (schools, final) per day, newest first."""
    newest = sorted(entries, reverse=True)[:INDEX_DAYS]
    return DayIndex.model_validate(
        {
            "schema_version": 1,
            "generated_at": generated_at.astimezone(UTC).replace(microsecond=0),
            "days": tuple(
                DayEntry(day=day, schools=entries[day][0], final=entries[day][1]) for day in newest
            ),
        }
    )


def is_final(day: date, generated_at: datetime) -> bool:
    """Whether ``day`` is over everywhere at ``generated_at``."""
    return day < local_days(generated_at)[0]


def school_past(directory: LiveDirectory, at: datetime) -> Callable[[str, date], bool]:
    """``past(nces_id, day)``: whether the day is over for the school at ``at``."""

    def past(nces_id: str, day: date) -> bool:
        school = directory.schools.get(nces_id)
        zones = school.zones if school is not None and school.zones else ("America/New_York",)
        return day < max(at.astimezone(ZoneInfo(zone)).date() for zone in zones)

    return past
