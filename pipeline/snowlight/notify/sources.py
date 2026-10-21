"""The published files as the notification rules read them, by school id.

* :func:`statuses` and :func:`open_days`: the live closings and opens files (what the map
  shows), each row's school index turned into its id through the deployed directory.
* :func:`outlooks`: the predictions file's chance of no school per day for each school,
  from its district's forecast, or its own for a private school (S7-2).

A file is read only when it is the deployed directory's (its stamp) and fresh: a status
older than :data:`FRESH` is never sent as current (the page stops calling the file live
then too).
"""

from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Final

from snowlight.notify.rules import Outlook, Shown
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import ClosingsFile, OpensFile
from snowlight.schemas.predictions import Forecast, PredictionsFile

FRESH: Final = timedelta(minutes=20)
"""How old a closings file may be (``LIVE_FRESH_MS`` in the web)."""
AHEAD: Final = timedelta(seconds=60)


def fresh(generated_at: datetime, now: datetime) -> bool:
    """Whether a live file written at ``generated_at`` is current at ``now``."""
    age = now - generated_at
    return -AHEAD <= age <= FRESH


def statuses(
    closings: ClosingsFile, ids: Sequence[str], wanted: Collection[str]
) -> dict[str, dict[date, Shown]]:
    """Each wanted school's status by local day, as the file shows it."""
    found: dict[str, dict[date, Shown]] = {}
    for row in closings.closings():
        if row.school >= len(ids):
            continue
        school = ids[row.school]
        if school not in wanted:
            continue
        found.setdefault(school, {})[row.day] = Shown(
            status=row.status, shift=row.shift_minutes, clock=row.clock_minute
        )
    return found


def open_days(
    opens: OpensFile | None, ids: Sequence[str], wanted: Collection[str]
) -> frozenset[tuple[str, date]]:
    """The wanted schools' explicit open statements, as (id, local day)."""
    if opens is None:
        return frozenset()
    return frozenset(
        (ids[item.school], item.day)
        for item in opens.opens
        if item.school < len(ids) and ids[item.school] in wanted
    )


def _percent(day: object) -> int | None:
    if isinstance(day, Forecast):
        return round(day.p_no_school * 100)
    return None


def outlooks(
    file: PredictionsFile,
    ids: Sequence[str],
    district_of: Sequence[int | None],
    wanted: Collection[str],
) -> dict[str, Outlook]:
    """Each wanted school's chance of no school by day: its district's, or for a school with
    no district its own (the file's private schools). A school the file gives no chance
    (its district or itself left out) gets none."""
    index = {school: position for position, school in enumerate(ids)}
    districts = {entry.district: entry for entry in file.districts}
    private = {entry.school: entry for entry in file.schools}
    found: dict[str, Outlook] = {}
    for school in wanted:
        position = index.get(school)
        if position is None or position >= len(district_of):
            continue
        district = district_of[position]
        if district is not None:
            entry = districts.get(district)
            if entry is None:
                continue
            days = {
                day: _percent(forecast) for day, forecast in zip(file.days, entry.days, strict=True)
            }
            found[school] = Outlook(zone=entry.time_zone, percent=days)
            continue
        own = private.get(position)
        if own is None:
            continue
        days = {
            day: _percent(file.outlooks[outlook])
            for day, outlook in zip(file.days, own.days, strict=True)
        }
        found[school] = Outlook(zone=file.zones[own.zone], percent=days)
    return found


def status_days(
    closings: ClosingsFile | None,
    stamp: DirectoryStamp,
    ids: Sequence[str],
    wanted: Collection[str],
    now: datetime,
) -> frozenset[tuple[str, date]]:
    """The wanted school-days the closings file shows a status for (none when the file is
    missing, stale or for another directory)."""
    if closings is None or closings.directory != stamp or not fresh(closings.generated_at, now):
        return frozenset()
    return frozenset(
        (school, day) for school, days in statuses(closings, ids, wanted).items() for day in days
    )


def zones_for(
    wanted: Collection[str], index: Mapping[str, int], zone_of: Mapping[int, str]
) -> dict[str, str]:
    """Each wanted school's time zone by id (a school without one is left out)."""
    return {
        school: zone_of[index[school]]
        for school in wanted
        if school in index and index[school] in zone_of
    }
