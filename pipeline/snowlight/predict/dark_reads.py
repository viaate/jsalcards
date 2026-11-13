"""The chance job's loaders of what the map showed, read through ``as_dark``.

Everything that teaches or serves the prediction reads a status whose reason is not a named
:class:`~snowlight.schemas.vocab.Reason` code (0-7), a stated cause that is not the weather
or a code this code does not know, exactly as it read the dark that status replaces
(docs/predict.md, "Stated causes read as dark"). One loader per input does it, so a new
reader of that input gets it for free:

* :func:`closings`: ``live/closings.json`` (:func:`~snowlight.schemas.live.as_dark_closings`);
* :func:`timeline`: a day timeline (:func:`~snowlight.schemas.live.as_dark`);
* :class:`DarkChanges`: the private change log, one day at a time
  (:func:`~snowlight.live.history.as_dark_changes`).

Each reads the file first as :mod:`snowlight.predict.host_files` does, which stays the raw
reader for everyone else (the notifier reads every status as it is). On today's files, whose
reasons are all 0-7, each loader returns what the raw read returns.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from snowlight.live.history import Change, as_dark_changes
from snowlight.predict import host_files
from snowlight.schemas.live import ClosingsFile, DayTimeline, as_dark, as_dark_closings


def closings(data: bytes | str, *, where: str) -> ClosingsFile:
    """``live/closings.json`` as the prediction reads it."""
    return as_dark_closings(host_files.closings(data, where=where))


def timeline(data: bytes | str, *, where: str) -> DayTimeline:
    """A day timeline, ``live/days/<day>.json``, as the prediction reads it."""
    return as_dark(host_files.timeline(data, where=where))


class ChangeDays(Protocol):
    """The change log's days and each day's changes (:class:`~snowlight.live.history.
    ChangeLog`, :class:`DarkChanges`, or :class:`~snowlight.predict.live_read.
    LoadedChanges`)."""

    def days(self) -> list[date]: ...

    def changes(self, day: date) -> list[Change]: ...


@dataclass(slots=True)
class DarkChanges:
    """A change log as the prediction reads it: each day's lines through
    :func:`~snowlight.live.history.as_dark_changes`. A day all of whose lines were such
    statuses is left out of :meth:`days`, as the base holds no log for it; every other day
    is listed as the log lists it. Each day is read once."""

    log: ChangeDays
    _read: dict[date, tuple[bool, list[Change]]] = field(default_factory=dict, init=False)

    def _day(self, day: date) -> tuple[bool, list[Change]]:
        if day not in self._read:
            lines = self.log.changes(day)
            self._read[day] = (bool(lines), as_dark_changes(lines))
        return self._read[day]

    def days(self) -> list[date]:
        return [day for day in self.log.days() if not (found := self._day(day))[0] or found[1]]

    def changes(self, day: date) -> list[Change]:
        return list(self._day(day)[1])
